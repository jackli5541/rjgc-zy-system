from logging.config import fileConfig

from alembic import context

from app.database import Base
from app.models import *  # noqa: F403
from app.settings import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    from app.database import engine
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
