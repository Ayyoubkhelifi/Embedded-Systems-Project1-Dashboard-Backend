from alembic import op

"""initial schema

Revision ID: 0001
Revises: None — first revision.
Creates all tables from the current declarative metadata via create_all.
Downgrade drops them all. Future incremental migrations build on this base.
"""

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app import models  # noqa: F401 — tables registered on import
    from app.db.base import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app import models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
