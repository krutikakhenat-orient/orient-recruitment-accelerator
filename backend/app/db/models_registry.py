"""Imports all ORM models so Alembic autogenerate and metadata creation see them.

Add new model modules here as they are introduced.
"""

from __future__ import annotations

from app.db.base import Base
from app.modules.applications import models as application_models  # noqa: F401
from app.modules.assessments import models as assessment_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.campaigns import models as campaign_models  # noqa: F401
from app.modules.candidates import models as candidate_models  # noqa: F401
from app.modules.decisions import models as decision_models  # noqa: F401
from app.modules.documents import models as document_models  # noqa: F401
from app.modules.extraction import models as extraction_models  # noqa: F401
from app.modules.forms import models as form_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.interviews import models as interview_models  # noqa: F401
from app.modules.job_descriptions import models as jd_models  # noqa: F401
from app.modules.privacy import models as privacy_models  # noqa: F401
from app.modules.projects import models as project_models  # noqa: F401
from app.modules.review import models as review_models  # noqa: F401
from app.modules.rules import models as rules_models  # noqa: F401
from app.modules.screening import models as screening_models  # noqa: F401
from app.modules.skills import models as skill_models  # noqa: F401
from app.modules.waitlist import models as waitlist_models  # noqa: F401

__all__ = ["Base"]
