"""M1 MySQL integration tests.

Run only with an isolated MySQL 5.7+ database URL, never a production library database:
MYSQL_TEST_DATABASE_URL=mysql+pymysql://... uv run pytest tests/integration
"""

import os

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_DATABASE_URL"), reason="需要隔离的MySQL测试库")
def test_mysql_57_or_newer_is_available_for_m1_persistence() -> None:
    engine = create_engine(os.environ["MYSQL_TEST_DATABASE_URL"])
    with engine.connect() as connection:
        version = connection.execute(text("SELECT VERSION()")).scalar_one()
    major, minor = (int(part) for part in version.split(".", 2)[:2])
    assert (major, minor) >= (5, 7)
