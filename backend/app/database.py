from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Select, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(Session, "do_orm_execute")
def apply_sqlserver_lock_hints(execute_state) -> None:
    """Translate SQLAlchemy's row-lock intent to SQL Server table hints."""
    statement = execute_state.statement
    lock_options = getattr(statement, "_for_update_arg", None)
    bind = execute_state.session.get_bind(**execute_state.bind_arguments)
    if bind.dialect.name != "mssql" or not isinstance(statement, Select) or lock_options is None:
        return
    entity = next((item.get("entity") for item in statement.column_descriptions if item.get("entity") is not None), None)
    if entity is None:
        return
    hints = "UPDLOCK, ROWLOCK"
    if lock_options.skip_locked:
        hints += ", READPAST"
    execute_state.statement = statement.with_hint(entity, f"WITH ({hints})", dialect_name="mssql")


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
