from app.core.db import Base
from app.core.schema_comments import TABLE_COMMENTS
import app.models  # noqa: F401


def test_every_business_table_and_column_has_a_chinese_comment() -> None:
    assert set(TABLE_COMMENTS) == set(Base.metadata.tables)
    for table_name, definition in TABLE_COMMENTS.items():
        table = Base.metadata.tables[table_name]
        assert table.comment == definition["table"]
        assert set(definition["columns"]) == set(table.c.keys())
        assert all(column.comment for column in table.columns)
