"""document ingestion

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13 18:25:24.636290
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import integrity.infrastructure.db.base
from sqlalchemy.dialects import mysql

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hand-reviewed. New NOT NULL columns are added nullable, backfilled, then
    # tightened, so the migration also works on a table that already has rows.
    op.create_table('document_contents',
    sa.Column('version_id', sa.String(length=36), nullable=False),
    sa.Column('organization_id', sa.String(length=36), nullable=False),
    sa.Column('codec', sa.String(length=32), nullable=False),
    sa.Column('payload', sa.LargeBinary().with_variant(mysql.LONGBLOB(), 'mysql'), nullable=False),
    sa.Column('payload_bytes', sa.Integer(), nullable=False),
    sa.Column('payload_sha256', sa.String(length=64), nullable=False),
    sa.Column('created_at', integrity.infrastructure.db.base.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_document_contents_organization_id_organizations')),
    sa.ForeignKeyConstraint(['version_id', 'organization_id'], ['document_versions.id', 'document_versions.organization_id'], name=op.f('fk_document_contents_version_id_document_versions')),
    sa.PrimaryKeyConstraint('version_id', name=op.f('pk_document_contents')),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_bin',
    mysql_engine='InnoDB'
    )
    with op.batch_alter_table('document_contents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_contents_organization_id'), ['organization_id'], unique=False)

    json_type = sa.JSON().with_variant(mysql.JSON(), 'mysql')
    with op.batch_alter_table('document_versions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('idempotency_key', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('upstream_ref', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('producer', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('producer_version', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('pages_failed', json_type, nullable=True))
        batch_op.add_column(sa.Column('pages_needing_ocr', json_type, nullable=True))
        batch_op.add_column(sa.Column('limitations', json_type, nullable=True))

    # Backfill: pre-existing versions get a key that can never collide with a client key
    # (client keys cannot contain '#').
    op.execute("UPDATE document_versions SET idempotency_key = CONCAT('legacy#', id) WHERE idempotency_key IS NULL"
               if op.get_bind().dialect.name == 'mysql' else
               "UPDATE document_versions SET idempotency_key = 'legacy#' || id WHERE idempotency_key IS NULL")
    op.execute("UPDATE document_versions SET pages_failed = '[]' WHERE pages_failed IS NULL")
    op.execute("UPDATE document_versions SET pages_needing_ocr = '[]' WHERE pages_needing_ocr IS NULL")
    op.execute("UPDATE document_versions SET limitations = '[]' WHERE limitations IS NULL")

    with op.batch_alter_table('document_versions', schema=None) as batch_op:
        batch_op.alter_column('idempotency_key', existing_type=sa.String(length=128), nullable=False)
        batch_op.alter_column('pages_failed', existing_type=json_type, nullable=False)
        batch_op.alter_column('pages_needing_ocr', existing_type=json_type, nullable=False)
        batch_op.alter_column('limitations', existing_type=json_type, nullable=False)
        batch_op.create_unique_constraint(batch_op.f('uq_document_versions_organization_id_idempotency_key'), ['organization_id', 'idempotency_key'])


def downgrade() -> None:
    # Dropping the table drops its FK-backing indexes (dropping them first fails on MySQL, errno 1553).
    op.drop_table('document_contents')
    with op.batch_alter_table('document_versions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_document_versions_organization_id_idempotency_key'), type_='unique')
        batch_op.drop_column('limitations')
        batch_op.drop_column('pages_needing_ocr')
        batch_op.drop_column('pages_failed')
        batch_op.drop_column('producer_version')
        batch_op.drop_column('producer')
        batch_op.drop_column('upstream_ref')
        batch_op.drop_column('idempotency_key')
