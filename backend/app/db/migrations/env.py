"""Alembic environment. Migrations always run on the connection `bootstrap` supplies."""

from alembic import context

from app.db.schema import metadata

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
context.run_migrations()
