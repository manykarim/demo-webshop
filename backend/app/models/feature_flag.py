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


class SpaceFeatureFlag(Base):
    """A flag value set by one workshop space (design D3).

    Only spaces other than ``default`` are stored here; the ``default`` space
    keeps using the global ``feature_flags`` table above. A space row exists
    only for a flag that space has actually set, so everything else falls back
    to the baseline. ``create_all`` creates this table on existing databases,
    so no migration is involved.
    """

    __tablename__ = "space_feature_flags"
    space = Column(String(39), primary_key=True)
    key = Column(String(64), primary_key=True)
    enabled = Column(Boolean, nullable=False)

    def to_dict(self) -> dict:
        return {
            "space": self.space,
            "key": self.key,
            "enabled": self.enabled,
        }
