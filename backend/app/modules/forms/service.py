"""Form schema application service (Req 4.1).

Creates a baseline form draft for a campaign, allows adding allowed fields (rejecting
prohibited ones), and approves a version into an immutable state.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.audit.schemas import AuditEventWrite
from app.modules.audit.service import record_event
from app.modules.forms.models import FormField, FormSchema, FormVersion, FormVersionStatus
from app.modules.forms.policy import (
    BASELINE_FIELDS,
    COMPENSATION_FIELDS,
    assert_field_allowed,
)


def create_form_draft(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign_id: uuid.UUID,
    actor_id: uuid.UUID,
    compensation_enabled: bool = False,
) -> FormVersion:
    schema = _get_or_create_schema(db, organisation_id, campaign_id)

    next_number = _next_version_number(db, schema.id)
    version = FormVersion(
        form_schema_id=schema.id,
        organisation_id=organisation_id,
        version_number=next_number,
        status=FormVersionStatus.DRAFT.value,
        compensation_enabled=compensation_enabled,
        created_by=actor_id,
    )
    db.add(version)
    db.flush()

    field_specs = list(BASELINE_FIELDS)
    if compensation_enabled:
        field_specs += list(COMPENSATION_FIELDS)

    for index, spec in enumerate(field_specs):
        assert_field_allowed(
            str(spec["key"]), str(spec["field_class"]),
            compensation_enabled=compensation_enabled,
        )
        raw_options = spec.get("options")
        options = (
            [str(o) for o in raw_options] if isinstance(raw_options, list | tuple) else None
        )
        # Repeating-group fields carry the column definitions of one row in item_fields.
        raw_items = spec.get("item_fields")
        item_schema = (
            [dict(item) for item in raw_items] if isinstance(raw_items, list | tuple) else None
        )
        db.add(
            FormField(
                form_version_id=version.id,
                key=str(spec["key"]),
                label=str(spec["label"]),
                field_class=str(spec["field_class"]),
                field_type=str(spec["field_type"]),
                required=bool(spec["required"]),
                order_index=index,
                options=options,
                item_schema=item_schema,
            )
        )
    db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="form_version.drafted",
            entity_type="form_version",
            entity_id=str(version.id),
            new_state_ref="draft",
        ),
    )
    return version


def approve_form_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    form_version_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> FormVersion:
    version = db.get(FormVersion, form_version_id)
    if version is None or version.organisation_id != organisation_id:
        raise NotFoundError("Form version not found")
    if version.is_approved:
        raise ConflictError("Form version is already approved and immutable")
    if not version.fields:
        raise ValidationError("Cannot approve an empty form version")

    version.status = FormVersionStatus.APPROVED.value
    db.flush()

    # Point the owning campaign at this approved form version so downstream steps (public
    # apply, screening, the campaign readiness check) see it. Without this the campaign's
    # approved_form_version_id stays null.
    from app.modules.campaigns.models import Campaign

    schema = db.get(FormSchema, version.form_schema_id)
    if schema is not None and schema.organisation_id == organisation_id:
        campaign = db.get(Campaign, schema.campaign_id)
        if campaign is not None and campaign.organisation_id == organisation_id:
            if version.form_schema_id == schema.id:
                _supersede_prior_form(db, campaign, version)
            campaign.approved_form_version_id = version.id
            campaign.updated_by = actor_id
            db.flush()

    record_event(
        db,
        AuditEventWrite(
            organisation_id=organisation_id,
            actor_id=actor_id,
            action="form_version.approved",
            entity_type="form_version",
            entity_id=str(version.id),
            previous_state_ref="draft",
            new_state_ref="approved",
        ),
    )
    return version


def _supersede_prior_form(db: Session, campaign: object, version: FormVersion) -> None:
    """Mark a campaign's previously-approved form version as superseded when a new one is
    approved, so only one approved form is active at a time."""
    from app.modules.campaigns.models import Campaign

    assert isinstance(campaign, Campaign)
    previous = campaign.approved_form_version_id
    if previous is not None and previous != version.id:
        prior = db.get(FormVersion, previous)
        if prior is not None and prior.is_approved:
            prior.status = FormVersionStatus.SUPERSEDED.value


def get_approved_form_version(
    db: Session, *, organisation_id: uuid.UUID, form_version_id: uuid.UUID
) -> FormVersion:
    """Fetch an APPROVED form version by id, organisation-scoped.

    Used by the public careers flow to render the correct per-role form. Raises NotFound if
    the version does not exist, belongs to another organisation, or is not approved — a
    candidate must never see a draft/superseded form.
    """
    version = db.get(FormVersion, form_version_id)
    if version is None or version.organisation_id != organisation_id or not version.is_approved:
        raise NotFoundError("Application form is not available")
    return version


def _get_or_create_schema(
    db: Session, organisation_id: uuid.UUID, campaign_id: uuid.UUID
) -> FormSchema:
    stmt = select(FormSchema).where(
        FormSchema.organisation_id == organisation_id,
        FormSchema.campaign_id == campaign_id,
    )
    schema = db.execute(stmt).scalars().first()
    if schema is None:
        schema = FormSchema(organisation_id=organisation_id, campaign_id=campaign_id)
        db.add(schema)
        db.flush()
    return schema


def _next_version_number(db: Session, form_schema_id: uuid.UUID) -> int:
    stmt = (
        select(FormVersion.version_number)
        .where(FormVersion.form_schema_id == form_schema_id)
        .order_by(FormVersion.version_number.desc())
        .limit(1)
    )
    latest = db.execute(stmt).scalars().first()
    return (latest or 0) + 1
