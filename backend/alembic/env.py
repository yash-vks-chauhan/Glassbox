from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.config import get_settings
from app.core.schema_lock import schema_lock
from app.models_db import Base

config = context.config
if config.config_file_name is not None:
    # Keep loggers the app (or a test session) already configured alive.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Callers that drive Alembic programmatically (tests, tooling) can target a
# specific database via `config.attributes["database_url"]`; otherwise use the
# app settings, i.e. DATABASE_URL.
database_url = config.attributes.get("database_url") or get_settings().resolved_database_url
# configparser treats "%" as interpolation syntax, e.g. in URL-encoded passwords.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _ensure_wide_version_table(connection) -> None:
    """Revision ids in this repo are descriptive and can exceed Alembic's
    default VARCHAR(32) version column. SQLite ignores the length; Postgres
    enforces it, so create (or widen) the column before migrating."""
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(128) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    connection.execute(
        text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
    )
    connection.commit()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # The schema lock makes concurrent upgrades (several servers starting at
    # once) run one after another; the later ones find the database at head.
    with connectable.connect() as connection, schema_lock(connection):
        _ensure_wide_version_table(connection)
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
