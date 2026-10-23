# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The DuckDB connector loads the spatial extension on connect."""

from __future__ import annotations

import duckdb
import pytest

from auto_ontology.connectors.duckdb import DuckDBDatabase


def test_spatial_functions_work_in_memory() -> None:
    db = DuckDBDatabase(":memory:", read_only=False)
    assert (
        db.execute("SELECT ST_AsText(ST_Point(1, 2)) AS wkt").iloc[0, 0]
        == "POINT (1 2)"
    )


def test_geometry_column_in_a_file(tmp_path) -> None:
    """A read-only file with a GEOMETRY column lists its columns and answers spatial SQL."""
    path = tmp_path / "geo.ddb"
    con = duckdb.connect(str(path))
    con.execute("INSTALL spatial; LOAD spatial")
    con.execute(
        "CREATE TABLE wells AS SELECT 1 AS OBJECTID, ST_Point(5.0, 60.0) AS geometry"
    )
    con.close()

    db = DuckDBDatabase(f"duckdb://{path}")
    columns = db.get_columns()
    assert dict(zip(columns["column_name"], columns["data_type"])) == {
        "OBJECTID": "INTEGER",
        "geometry": "GEOMETRY",
    }
    near = db.execute(
        "SELECT count(*) FROM wells WHERE ST_DWithin(geometry, ST_Point(5.0, 60.001), 0.01)"
    )
    assert near.iloc[0, 0] == 1


class _Offline:
    """A connection whose extension directory cannot be reached: INSTALL and LOAD fail."""

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self._con = con

    def execute(self, sql: str, *args):
        if sql.startswith(("INSTALL", "LOAD")):
            raise duckdb.IOException("Failed to download extension (offline)")
        return self._con.execute(sql, *args)

    def __getattr__(self, name: str):
        return getattr(self._con, name)


def test_a_failed_load_keeps_the_connection(monkeypatch, caplog) -> None:
    """Offline or a locked extension directory: warn, and still serve plain SQL."""
    connect = duckdb.connect
    monkeypatch.setattr(duckdb, "connect", lambda **kw: _Offline(connect(**kw)))
    db = DuckDBDatabase(":memory:", read_only=False)
    assert db.execute("SELECT 41 + 1 AS n").iloc[0, 0] == 42
    assert "DuckDB spatial extension not loaded" in caplog.text
    with pytest.raises(duckdb.Error):
        db.execute("SELECT ST_Point(1, 2)")
