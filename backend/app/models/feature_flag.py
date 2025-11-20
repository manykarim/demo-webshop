from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, String, Text

from .base import Base


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "description": self.description,
            "enabled": self.enabled,
        }
