"""Add Chinese comments to all business tables and columns.

Revision ID: 20261010_0010
Revises: 20260921_0009
Create Date: 2026-10-10
"""

from alembic import op
from sqlalchemy import text

from app.core.schema_comments import TABLE_COMMENTS


revision = "20261010_0010"
down_revision = "20260921_0009"
branch_labels = None
depends_on = None


def _identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def _literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _default_clause(value: object | None) -> str:
    if value is None:
        return ""
    rendered = str(value)
    if rendered.upper() in {"CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP()"}:
        return f" DEFAULT {rendered.upper()}"
    try:
        float(rendered)
        return f" DEFAULT {rendered}"
    except ValueError:
        return f" DEFAULT {_literal(rendered)}"


def _set_comments(*, include_comments: bool) -> None:
    connection = op.get_bind()
    for table_name, definition in TABLE_COMMENTS.items():
        columns = connection.execute(text(f"SHOW FULL COLUMNS FROM {_identifier(table_name)}")).mappings().all()
        fragments: list[str] = []
        for column in columns:
            field = str(column["Field"])
            comment = str(dict(definition["columns"]).get(field, "")) if include_comments else ""
            nullability = "NULL" if column["Null"] == "YES" else "NOT NULL"
            extra = f" {column['Extra']}" if column["Extra"] else ""
            fragments.append(
                f"MODIFY COLUMN {_identifier(field)} {column['Type']} {nullability}"
                f"{_default_clause(column['Default'])}{extra} COMMENT {_literal(comment)}"
            )
        connection.execute(text(f"ALTER TABLE {_identifier(table_name)} " + ", ".join(fragments)))
        table_comment = str(definition["table"]) if include_comments else ""
        connection.execute(text(f"ALTER TABLE {_identifier(table_name)} COMMENT = {_literal(table_comment)}"))


def upgrade() -> None:
    _set_comments(include_comments=True)


def downgrade() -> None:
    _set_comments(include_comments=False)
