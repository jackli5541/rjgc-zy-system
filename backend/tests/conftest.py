from collections.abc import Generator

import pytest
from sqlalchemy import inspect, text

from app.bootstrap import main as bootstrap
from app.database import engine
from app.settings import settings


def _reset_database() -> None:
    if not settings.database_url.rsplit("/", 1)[-1].startswith("coursework_test"):
        raise RuntimeError("Tests must run against an isolated coursework_test database.")

    with engine.begin() as connection:
        table_names = [
            name for name in inspect(connection).get_table_names() if name != "alembic_version"
        ]
        if table_names:
            quoted_names = ", ".join(f'"{name}"' for name in table_names)
            connection.execute(text(f"TRUNCATE TABLE {quoted_names} RESTART IDENTITY CASCADE"))
    bootstrap()


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database() -> Generator[None, None, None]:
    _reset_database()
    yield
    _reset_database()
