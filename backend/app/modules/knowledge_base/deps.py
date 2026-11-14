"""FastAPI dependencies for the chatbot (overridable in tests)."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.deps import settings_dep
from app.core.config import Settings
from app.db.session import get_db
from app.modules.documents.scanning import MalwareScanner, default_scanner
from app.modules.documents.storage import ObjectStore
from app.modules.knowledge_base.factory import build_knowledge_base, policy_file_store
from app.modules.knowledge_base.types import KnowledgeBase


def get_knowledge_base(
    db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)
) -> KnowledgeBase:
    return build_knowledge_base(settings, db)


def get_policy_file_store(settings: Settings = Depends(settings_dep)) -> ObjectStore:
    return policy_file_store(settings)


def get_malware_scanner() -> MalwareScanner:
    return default_scanner
