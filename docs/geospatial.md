# Geospatial data in Auto Ontology

Status: 2026-10-23 · Fork: `mraad/auto-ontology` · Base: NVIDIA `main` at `643993e7` (1.1.0) · Test data: NorthSea (ArcGIS project, 3 layers, 11,056 features)

This document is for the Auto Ontology engineers at NVIDIA. It tells what this fork changes so that Auto Ontology can answer questions on spatial data. It also gives the problems that we found when we ran the full stack, and a proposed fix for each problem.

The changes are small. They are on two branches of the fork. They do not change the catalog schema, the API or the text-to-SQL graph.

## 1. Summary

- The DuckDB connector loads the DuckDB `spatial` extension. Before this change, each `ST_*` function failed.
- The Docker image installs `spatial` when it is built. Before this change, the install failed at runtime because the app user cannot write its home directory.
- The Postgres connector shows a PostGIS geometry column with its shape and SRID, for example `geometry(Point,4326)`. It does not show the tables of an extension, for example `spatial_ref_sys`.
- An Apache Ossie model from [geo-ontology](https://github.com/mraad/geo-ontology) imports into Auto Ontology. Each spatial rule becomes a custom analysis. Each spatial relation becomes a link table that text-to-SQL joins by key.
- With these changes, Auto Ontology gave the correct answer to three NorthSea questions, two of them spatial (§5).

## 2. Changes in this fork

| Commit | Branch | File | Change |
|---|---|---|---|
| `af9331a6` | `feat/duckdb-spatial` | `auto_ontology/connectors/duckdb.py` | `DuckDBDatabase._load_spatial()` runs `INSTALL spatial` and `LOAD spatial` after it connects. If that fails (no network, or a locked extension directory), it writes a warning and continues. Non-spatial SQL continues to work. |
| `af9331a6` | `feat/duckdb-spatial` | `auto_ontology/connectors/tests/test_duckdb.py` | Three tests: spatial functions in memory; a read-only file with a `GEOMETRY` column; a failed load that keeps the connection. |
| `699d5fd0` | `feat/duckdb-spatial` | `Dockerfile` | Creates `/app/.duckdb` for the user `auto_ontology` and runs `INSTALL spatial` when the image is built. `LOAD spatial` then works without network. |
| `e1df3008` | `feat/postgis-spatial` | `auto_ontology/connectors/postgres.py` | `get_columns` keeps the type modifier of `geometry` and `geography` columns (`format_type(atttypid, atttypmod)`). `get_tables` and `get_columns` leave out relations that belong to an extension (`pg_depend.deptype = 'e'`). |
| `e1df3008` | `feat/postgis-spatial` | `auto_ontology/connectors/tests/test_postgis.py` | Three tests against a PostGIS database. They are skipped when `POSTGIS_URL` has no value. |

### 2.1 Why the DuckDB connector must load `spatial`

DuckDB 1.5.5 does not load an installed extension automatically when a query uses one of its functions. A plain connection gives this error:

```text
Catalog Error: Scalar Function with name "st_x" is not in the catalog, but it exists in the spatial extension.
```

Without the change, a `GEOMETRY` column imports, but each query that uses it fails.

### 2.2 Why the image must install `spatial`

The user `auto_ontology` has the home directory `/app`. The user `root` owns `/app`. DuckDB keeps its extensions in `~/.duckdb`. Thus `INSTALL spatial` at runtime fails:

```text
DuckDB spatial extension not loaded: IO Error: Failed to create directory "/app/.duckdb": Permission denied
```

A runtime install also needs network access, which many deployments do not have.

### 2.3 Why the Postgres connector must keep the SRID

`format_type(atttypid, NULL)` gives `geometry` for each PostGIS column. Text-to-SQL then does not know the SRID. It cannot select the correct transform for a distance in metres. With the change, the catalog shows `geometry(MultiPolygon,4326)`. PostGIS also adds `spatial_ref_sys`, `geometry_columns` and `geography_columns`. These tables describe the database, not the data. Before the change, the catalog showed them as user tables.

## 3. How spatial relations get to Auto Ontology

Auto Ontology joins tables only on equal keys. It has no spatial join. geo-ontology writes each spatial relation of a rule as data, in a link table with two columns: `(primary_id, target_id)`. The Ossie model declares the link table as a dataset with foreign keys to the two layers. Text-to-SQL can then follow the relation with a normal join.

| Link table | Rows | Relation |
|---|---:|---|
| `WellNearGasLine__Pipelines` | 75 | A well is within 500 m of an in-service gas pipeline. |
| `GasWellInGasDiscovery__Discoveries` | 1181 | A gas well is within a gas or gas/condensate discovery. |
| `ConcurrentDrilling__Wells` | 221 | A dated well is within 2 km of another dated well and was drilled during it. |

Each rule also becomes an Ossie metric. Ossie's converter `converters/nvidia` makes it a custom analysis with the SQL unchanged.

| Custom analysis | Rows | Spatial |
|---|---:|---|
| `DatedWell` | 7325 | no |
| `GasWell` | 1730 | no |
| `InServiceGasPipeline` | 45 | no |
| `ProducingDiscovery` | 536 | no |
| `ConcurrentDrilling` | 185 | yes |
| `GasWellInGasDiscovery` | 1140 | yes |
| `WellNearGasLine` | 65 | yes |

Without §2.1, only the four analyses without a spatial predicate run. With §2.1, all seven run. The PostGIS connection (§2.3) gives the same counts.

## 4. Run the stack on NorthSea

Prerequisites:

- Docker with Compose v2.
- `NVIDIA_API_KEY`, exported in the shell.
- `NorthSea.ddb` with DuckDB storage version 1.x, with the link tables. geo-ontology `docs/OSSIE.md` §6.2 gives the procedure.
- `NorthSea.ossie.yaml` from geo-ontology.
- This fork on branch `feat/duckdb-spatial`.

Procedure:

1. Copy `.env.example` to `.env`.
2. In `.env`, set `CONNECTION_STRINGS=duckdb:///data/NorthSea/NorthSea.ddb`.
3. In `.env`, delete each `*_API_KEY` line. Each model role then uses `NVIDIA_API_KEY`.
4. In a Compose override file, mount the NorthSea folder read-only at `/data/NorthSea` for `auto-ontology` and `ingestion-service`.
5. In the override file, set `DEFAULT_MODELS_MODEL`, `REASONING_MODEL` and `NON_REASONING_MODEL` to `nvidia/nemotron-3.5-super-vl-120b-a12b` (problem 4 in §6).
6. Build the images: `docker compose -f docker-compose.yml -f compose.northsea.yml build`.
7. Start Postgres and the migration: `docker compose -f docker-compose.yml -f compose.northsea.yml up -d postgres auto-ontology-migrate`.
8. Start the backend without its dependencies: `docker compose -f docker-compose.yml -f compose.northsea.yml up -d --no-deps auto-ontology`.
9. Import the model:

   ```sh
   curl --fail-with-body -X POST 'http://127.0.0.1:3001/api/model/import?replace=true&embed=true' \
       -H 'Content-Type: application/x-yaml' --data-binary @NorthSea.ossie.yaml
   ```

10. Start the remaining containers: `docker compose -f docker-compose.yml -f compose.northsea.yml up -d`.

The import of step 9 created 1 database, 1 schema, 6 tables, 60 columns, 6 terms, 60 column attributes, 5 semantic foreign keys and 7 custom analyses. It embedded 66 data rows and 73 semantic rows. The first ingest after step 10 found the database by its name and added the table `sp_ref`.

geo-ontology `docs/OSSIE.md` §6.6 gives each step with the full commands and the override file.

## 5. Results

Questions sent to `POST /api/chat/completions` on the backend:

| Question | SQL of Auto Ontology | Answer | Correct |
|---|---|---|---|
| How many gas wells are there? | `SELECT COUNT(*) FROM "Wells" WHERE content_type IN (2, 7)` | 1730 | yes |
| How many wells are within 500 m of an in-service gas pipeline? | `COUNT(DISTINCT primary_id)` on `WellNearGasLine__Pipelines` joined to `Pipelines` on `target_id = OBJECTID`, gas and `IN SERVICE` | 65 | yes |
| Which in-service gas pipelines have the most wells within 500 m? | the same join, grouped by pipeline, in descending order of distinct wells | SLEIPNER R–EASINGTON (8), NYHAMNA–SLEIPNER R (8), DRAUPNER E–DUNKERQUE (7), MARTIN LINGE A–FRIGG TP1-Y (6) | yes |

For the two spatial questions, text-to-SQL used the link table. It did not use a spatial function. Each answer took approximately 4 minutes because of problem 5 in §6.

## 6. Problems found, and proposed fixes for `main`

| # | Problem | Cause | Proposed fix |
|---|---|---|---|
| 1 | Spatial SQL fails on a DuckDB connection. | §2.1. | Merge `af9331a6`. |
| 2 | In the Docker image, the spatial install fails. | §2.2. | Merge `699d5fd0`, or set `extension_directory` to a writable path. |
| 3 | The import of a model fails with `duplicate key value violates unique constraint "uq_catalog_database_name"`. This occurs with `replace=false` and with `replace=true`. | The ingestion service makes the catalog database first, from `CONNECTION_STRINGS`. `_resolve_entities_batch` finds an existing row only by `imported_id` or `id`, not by name. The import then tries to make a second row with the same name. | When no row has the `imported_id`, find the database (and its schemas, tables and columns) by name, and set `imported_id` on that row. A workaround is to import before the first ingest (§4, steps 7 to 10). |
| 4 | Each answer is `LLM failed to produce a response.` The log has `[410] Gone ... 'nvidia/nemotron-3-nano-30b-a3b' has reached its end of life on 2026-09-01`. | The default model of `.env.example` is retired. | Change the default model in `.env.example`, in the Helm values and in `README.md`. |
| 5 | An answer takes approximately 4 minutes. The log has `[400] unknown field guided_json` for `QuestionIntentModel`, `QuestionExtractionModel` and `TableRelevanceModel`. | The structured-output request of `langchain_nvidia_ai_endpoints` sends a field that the hosted endpoint refuses. Each step tries 3 times, then uses a default value. | Upgrade `langchain_nvidia_ai_endpoints`, or send the JSON schema in the form that the endpoint accepts (for example `response_format`). We did not try this. |
| 6 | The import fails with `ON CONFLICT DO UPDATE command cannot affect row a second time`. | The primary key of `table__join` is `(source_table_id, target_table_id)`. A model cannot have two joins between the same two tables. Our link table `ConcurrentDrilling__Wells` has two foreign keys to `Wells` (`primary_id` and `target_id`). | Give each join its own key, or include `join_columns` in the key. A table with two foreign keys to one table is common (for example `flight.origin` and `flight.destination` to `airport`). geo-ontology now declares only the first join of such a link table. |
| 7 | The DuckDB connector shows a geometry column as `GEOMETRY`, without an SRID. | DuckDB 1.5 `GEOMETRY` has no CRS. | Optional: read the CRS from a table such as `sp_ref`, or from the column comment, and add it to the column description. |
| 8 | Text-to-SQL has no instructions for spatial SQL. For SQLite, the prompt prohibits spatial functions. | The prompt has no section for spatial dialects. | Optional: when a column type is `GEOMETRY` or `geometry(...)`, add the dialect's distance and transform functions to the prompt. Link tables made this unnecessary for the questions in §5. |

## 7. Tests

| Test | Result |
|---|---|
| `auto_ontology/connectors/tests/test_duckdb.py` | 3 passed |
| `auto_ontology/connectors/tests/test_postgis.py` with `POSTGIS_URL` | 3 passed |
| DuckDB connector on `NorthSea.ddb`: 7 custom analyses and 3 link tables | counts as in §3 |
| Postgres connector on PostGIS (`pg-multi-ext`, schema `northsea`): 7 custom analyses and 3 link tables | counts as in §3 |
| Docker image: `ST_X(geometry)` on the mounted `NorthSea.ddb` | runs, no warning |
| Full stack: 3 questions of §5 | 3 correct |

Not done: questions through the user interface on port 3000; the MCP server; a question that uses a custom analysis.
