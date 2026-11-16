"""baseline application schema"""
revision = "0001_baseline"
down_revision = None
from alembic import op
from tender.db import Base
def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql": op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind)
def downgrade():
    pass
