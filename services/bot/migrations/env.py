from alembic import context
from sqlalchemy import create_engine

from bot.db import Base

url = context.config.get_main_option("sqlalchemy.url")
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(
            connection=connection, target_metadata=Base.metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
