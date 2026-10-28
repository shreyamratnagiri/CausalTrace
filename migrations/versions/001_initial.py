"""Initial schema; supports both PostgreSQL and local SQLite.

Revision ID: 001_initial
Revises:
"""
from alembic import op
from causaltrace.db import Base
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)

def downgrade():
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
