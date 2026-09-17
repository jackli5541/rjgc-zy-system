from collections.abc import Generator

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from app.bootstrap import main as bootstrap
from app.database import Base, engine
from app.settings import settings


def _reset_database() -> None:
    if make_url(settings.database_url).database != "coursework_test":
        raise RuntimeError("Tests must run against an isolated coursework_test database.")

    with engine.begin() as connection:
        table_names = set(inspect(connection).get_table_names())
        preparer = connection.dialect.identifier_preparer
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in table_names:
                connection.execute(text(f"DELETE FROM {preparer.quote(table.name)}"))
    bootstrap()


@pytest.fixture(autouse=True)
def isolated_test_database() -> Generator[None, None, None]:
    _reset_database()
    yield
    _reset_database()
