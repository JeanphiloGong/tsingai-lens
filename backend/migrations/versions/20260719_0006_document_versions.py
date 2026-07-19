"""Add canonical document versions and collection membership.

Revision ID: 20260719_0006
Revises: 20260719_0005
Create Date: 2026-07-19
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0006"
down_revision: str | Sequence[str] | None = "20260719_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_documents")),
    )
    op.create_table(
        "document_versions",
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name=op.f("ck_document_versions_sha256_length"),
        ),
        sa.CheckConstraint(
            "sha256 = lower(sha256)",
            name=op.f("ck_document_versions_sha256_lowercase"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "document_version_id",
            name=op.f("pk_document_versions"),
        ),
        sa.UniqueConstraint("sha256", name=op.f("uq_document_versions_sha256")),
        sa.UniqueConstraint(
            "document_id",
            "document_version_id",
            name="uq_document_versions_document_version_identity",
        ),
    )
    op.create_index(
        op.f("ix_document_versions_document_id"),
        "document_versions",
        ["document_id"],
        unique=False,
    )
    op.create_table(
        "collection_documents",
        sa.Column("collection_document_id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.collection_id"],
            name=op.f("fk_collection_documents_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "document_version_id"],
            ["document_versions.document_id", "document_versions.document_version_id"],
            name="fk_collection_documents_document_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "collection_document_id",
            name=op.f("pk_collection_documents"),
        ),
        sa.UniqueConstraint(
            "collection_id",
            "document_id",
            name="uq_collection_documents_collection_document",
        ),
        sa.UniqueConstraint(
            "collection_id",
            "collection_document_id",
            name="uq_collection_documents_collection_membership_identity",
        ),
    )
    op.create_index(
        op.f("ix_collection_documents_collection_id"),
        "collection_documents",
        ["collection_id"],
        unique=False,
    )
    op.add_column(
        "stored_objects",
        sa.Column("document_version_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "collection_files",
        sa.Column("collection_document_id", sa.String(length=64), nullable=True),
    )

    connection = op.get_bind()
    stored_objects = sa.table(
        "stored_objects",
        sa.column("object_id", sa.String(length=64)),
        sa.column("sha256", sa.String(length=64)),
        sa.column("media_type", sa.String(length=255)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("document_version_id", sa.String(length=64)),
    )
    collection_files = sa.table(
        "collection_files",
        sa.column("file_id", sa.String(length=64)),
        sa.column("collection_id", sa.String(length=64)),
        sa.column("object_id", sa.String(length=64)),
        sa.column("collection_document_id", sa.String(length=64)),
    )
    collections = sa.table(
        "collections",
        sa.column("collection_id", sa.String(length=64)),
        sa.column("paper_count", sa.Integer()),
    )
    document_table = sa.table(
        "documents",
        sa.column("document_id", sa.String(length=64)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    version_table = sa.table(
        "document_versions",
        sa.column("document_version_id", sa.String(length=64)),
        sa.column("document_id", sa.String(length=64)),
        sa.column("sha256", sa.String(length=64)),
        sa.column("media_type", sa.String(length=255)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    membership_table = sa.table(
        "collection_documents",
        sa.column("collection_document_id", sa.String(length=64)),
        sa.column("collection_id", sa.String(length=64)),
        sa.column("document_id", sa.String(length=64)),
        sa.column("document_version_id", sa.String(length=64)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    existing_rows = connection.execute(
        sa.select(
            stored_objects.c.object_id,
            stored_objects.c.sha256,
            stored_objects.c.media_type,
            stored_objects.c.created_at,
            collection_files.c.file_id,
            collection_files.c.collection_id,
        )
        .select_from(
            stored_objects.join(
                collection_files,
                collection_files.c.object_id == stored_objects.c.object_id,
            )
        )
        .order_by(stored_objects.c.created_at, stored_objects.c.object_id)
    ).mappings()
    documents_by_id: dict[str, dict[str, object]] = {}
    versions_by_id: dict[str, dict[str, object]] = {}
    memberships_by_id: dict[str, dict[str, object]] = {}
    object_links: list[tuple[str, str]] = []
    file_links: list[tuple[str, str]] = []
    for row in existing_rows:
        digest = str(row["sha256"])
        document_id = f"doc_{uuid5(NAMESPACE_URL, f'lens:document:{digest}').hex}"
        document_version_id = (
            f"docver_{uuid5(NAMESPACE_URL, f'lens:document-version:{digest}').hex}"
        )
        collection_document_id = (
            "coldoc_"
            + uuid5(
                NAMESPACE_URL,
                f"lens:collection-document:{row['collection_id']}:{document_id}",
            ).hex
        )
        documents_by_id.setdefault(
            document_id,
            {"document_id": document_id, "created_at": row["created_at"]},
        )
        versions_by_id.setdefault(
            document_version_id,
            {
                "document_version_id": document_version_id,
                "document_id": document_id,
                "sha256": digest,
                "media_type": row["media_type"],
                "created_at": row["created_at"],
            },
        )
        memberships_by_id.setdefault(
            collection_document_id,
            {
                "collection_document_id": collection_document_id,
                "collection_id": row["collection_id"],
                "document_id": document_id,
                "document_version_id": document_version_id,
                "created_at": row["created_at"],
            },
        )
        object_links.append((str(row["object_id"]), document_version_id))
        file_links.append((str(row["file_id"]), collection_document_id))

    if documents_by_id:
        op.bulk_insert(document_table, list(documents_by_id.values()))
        op.bulk_insert(version_table, list(versions_by_id.values()))
        op.bulk_insert(membership_table, list(memberships_by_id.values()))
    for object_id, document_version_id in object_links:
        connection.execute(
            stored_objects.update()
            .where(stored_objects.c.object_id == object_id)
            .values(document_version_id=document_version_id)
        )
    for file_id, collection_document_id in file_links:
        connection.execute(
            collection_files.update()
            .where(collection_files.c.file_id == file_id)
            .values(collection_document_id=collection_document_id)
        )
    membership_counts = {
        str(collection_id): int(count)
        for collection_id, count in connection.execute(
            sa.select(
                membership_table.c.collection_id,
                sa.func.count(membership_table.c.collection_document_id),
            ).group_by(membership_table.c.collection_id)
        )
    }
    for collection_id in connection.scalars(sa.select(collections.c.collection_id)):
        connection.execute(
            collections.update()
            .where(collections.c.collection_id == collection_id)
            .values(paper_count=int(membership_counts.get(collection_id, 0)))
        )

    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.alter_column(
            "document_version_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.create_foreign_key(
            op.f("fk_stored_objects_document_version_id_document_versions"),
            "document_versions",
            ["document_version_id"],
            ["document_version_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            op.f("ix_stored_objects_document_version_id"),
            ["document_version_id"],
            unique=False,
        )
    with op.batch_alter_table("collection_files") as batch_op:
        batch_op.alter_column(
            "collection_document_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_collection_files_collection_document",
            "collection_documents",
            ["collection_id", "collection_document_id"],
            ["collection_id", "collection_document_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    connection = op.get_bind()
    collections = sa.table(
        "collections",
        sa.column("collection_id", sa.String(length=64)),
        sa.column("paper_count", sa.Integer()),
    )
    collection_files = sa.table(
        "collection_files",
        sa.column("collection_id", sa.String(length=64)),
    )
    file_counts = {
        str(collection_id): int(count)
        for collection_id, count in connection.execute(
            sa.select(
                collection_files.c.collection_id,
                sa.func.count(),
            ).group_by(collection_files.c.collection_id)
        )
    }
    for collection_id in connection.scalars(sa.select(collections.c.collection_id)):
        connection.execute(
            collections.update()
            .where(collections.c.collection_id == collection_id)
            .values(paper_count=int(file_counts.get(collection_id, 0)))
        )

    with op.batch_alter_table("collection_files") as batch_op:
        batch_op.drop_constraint(
            "fk_collection_files_collection_document",
            type_="foreignkey",
        )
        batch_op.drop_column("collection_document_id")
    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.drop_index(op.f("ix_stored_objects_document_version_id"))
        batch_op.drop_constraint(
            op.f("fk_stored_objects_document_version_id_document_versions"),
            type_="foreignkey",
        )
        batch_op.drop_column("document_version_id")
    op.drop_index(
        op.f("ix_collection_documents_collection_id"),
        table_name="collection_documents",
    )
    op.drop_table("collection_documents")
    op.drop_index(
        op.f("ix_document_versions_document_id"),
        table_name="document_versions",
    )
    op.drop_table("document_versions")
    op.drop_table("documents")
