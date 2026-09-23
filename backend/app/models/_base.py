from __future__ import annotations

from sqlalchemy import ForeignKey as SAForeignKey, ForeignKeyConstraint as SAForeignKeyConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID, uuid4


def uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


def ForeignKey(column: str, **kwargs):
    """Avoid multiple cascade paths, which SQL Server rejects."""
    kwargs.pop("ondelete", None)
    return SAForeignKey(column, **kwargs)


def ForeignKeyConstraint(columns, refcolumns, **kwargs):
    kwargs.pop("ondelete", None)
    return SAForeignKeyConstraint(columns, refcolumns, **kwargs)
