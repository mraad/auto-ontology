# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Postgres connector against a PostGIS database.

Skipped unless ``POSTGIS_URL`` names a database where the test may create tables, for example::

    docker run -d --name ao-postgis -e POSTGRES_PASSWORD=pg -p 55432:5432 postgis/postgis:17-3.5
    POSTGIS_URL=postgresql://postgres:pg@localhost:55432/postgres uv run pytest auto_ontology/connectors/tests/test_postgis.py
"""

from __future__ import annotations

import os

import pytest

from auto_ontology.connectors.registry import create_connector


@pytest.fixture(scope="module")
def db():
    url = os.environ.get("POSTGIS_URL")
    if not url:
        pytest.skip("POSTGIS_URL not set")
    connector = create_connector(url)
    connector.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    connector.execute("DROP SCHEMA IF EXISTS ao_geo CASCADE")
    connector.execute("CREATE SCHEMA ao_geo")
    connector.execute(
        "CREATE TABLE ao_geo.wells (objectid int PRIMARY KEY, name varchar(40), geometry geometry(Point, 4326))"
    )
    connector.execute(
        "INSERT INTO ao_geo.wells VALUES (1, 'A', ST_SetSRID(ST_Point(5.0, 60.0), 4326)),"
        " (2, 'B', ST_SetSRID(ST_Point(6.0, 61.0), 4326))"
    )
    connector.execute(
        "CREATE TABLE ao_geo.blocks (id int, geom geography(Polygon, 4326))"
    )
    yield connector
    connector.execute("DROP SCHEMA ao_geo CASCADE")
    connector.close()


def test_geometry_columns_keep_type_and_srid(db) -> None:
    columns = db.get_columns()
    mine = columns[columns["table_schema"] == "ao_geo"]
    types = dict(zip(mine["table_name"] + "." + mine["column_name"], mine["data_type"]))
    assert types["wells.geometry"] == "geometry(Point,4326)"
    assert types["blocks.geom"] == "geography(Polygon,4326)"
    assert types["wells.name"] == "character varying"  # other types keep no modifier


def test_postgis_own_tables_are_not_catalogued(db) -> None:
    names = set(db.get_tables()["table_name"])
    assert {"wells", "blocks"} <= names
    assert not names & {"spatial_ref_sys", "geometry_columns", "geography_columns"}
    assert not set(db.get_columns()["table_name"]) & {
        "spatial_ref_sys",
        "geometry_columns",
    }


def test_spatial_sql_runs(db) -> None:
    near = db.execute(
        "SELECT count(*) FROM ao_geo.wells WHERE ST_DWithin(geometry::geography,"
        " ST_SetSRID(ST_Point(5.0, 60.001), 4326)::geography, 500)"
    )
    assert near.iloc[0, 0] == 1
