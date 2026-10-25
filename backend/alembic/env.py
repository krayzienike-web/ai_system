from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import app.experiments.models
import app.insights.models
import app.tasks.models
import app.tenancy.models  # noqa: F401
from app.core.config import get_settings
from app.core.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # Migrations run as the schema owner, never as the application role.
    url = config.attributes.get("url") or get_settings().migrations_database_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
