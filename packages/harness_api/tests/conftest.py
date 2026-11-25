import sqlite3
from contextlib import closing
from pathlib import Path

import pytest


@pytest.fixture
def legacy_database(tmp_path):
    schema = Path(__file__).with_name("fixtures") / "legacy_versions.sql"

    def create(version):
        path = tmp_path / "goals.sqlite3"
        prefix, marker, _ = schema.read_text(encoding="utf-8").partition(
            f"PRAGMA user_version = {version};"
        )
        assert marker, f"Missing fixture for schema version {version}"
        with closing(sqlite3.connect(path, autocommit=True)) as connection:
            connection.executescript(prefix + marker)
        return path

    return create
