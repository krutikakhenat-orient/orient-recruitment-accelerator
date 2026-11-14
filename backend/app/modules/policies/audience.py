"""Audience tags: who may receive a policy's content (Req 4.2, CB-AC-04).

A policy's audience is a list of tags; empty means everyone. An asker always holds
``everyone`` plus ``role:<role name>`` for each role. ``department:<name>`` and
``location:<name>`` tags are accepted on policies for when the user profile carries those
fields (open question 2 in requirements.md); until then only HR managers see them.
"""

from __future__ import annotations

import re

from app.core.errors import ValidationError
from app.modules.identity.schemas import AuthenticatedActor
from app.modules.knowledge_base.types import EVERYONE, AudienceFilter

_TAG = re.compile(
    r"^(everyone|role:[a-z_]{2,40}|department:[a-z0-9 _-]{1,60}|location:[a-z0-9 _-]{1,60})$"
)
MAX_TAGS = 10


def normalise_audience(tags: list[str] | None) -> list[str] | None:
    """Validate and normalise tags from HR input. None/empty/['everyone'] => None (everyone)."""
    if not tags:
        return None
    cleaned: list[str] = []
    for raw in tags:
        tag = raw.strip().lower()
        if not tag:
            continue
        if not _TAG.match(tag):
            raise ValidationError(
                f"Unknown audience '{raw[:60]}'. Use 'everyone', 'role:<role>', "
                "'department:<name>' or 'location:<name>'."
            )
        if tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_TAGS:
        raise ValidationError(f"Use at most {MAX_TAGS} audience tags.")
    if not cleaned or cleaned == [EVERYONE] or EVERYONE in cleaned:
        return None
    return cleaned


def parse_audience_field(value: str | None) -> list[str] | None:
    """Comma-separated form field (multipart upload) to normalised tags."""
    if value is None:
        return None
    return normalise_audience(value.split(","))


def actor_audience(actor: AuthenticatedActor) -> AudienceFilter:
    tags = {EVERYONE} | {f"role:{name.lower()}" for name in actor.role_names}
    return AudienceFilter(organisation_id=actor.organisation_id, tags=frozenset(tags))
