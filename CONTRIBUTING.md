# Contributing

## Setup

```bash
uv sync                      # deps, incl. nlr from its pinned public git tag
cp .env.example .env         # PG* for the NYC public-record Postgres (see docs/data.md)
uv run python -m bor.build_lwc   # build landlords_with_connections from wow_landlords
```

See [`docs/data.md`](docs/data.md) for the required tables and where they come from.

## Tests

```bash
make test        # or: uv run pytest -q
```

- **Unit tests** (`tests/test_unit.py`) are pure logic — no database — and run anywhere.
- **Integration tests** (`tests/test_integration.py`) are regression checks against the reference
  `justfixwow` Postgres and **skip** unless `PG*` is set. They run the resolutions (~15 min) and
  assert the frozen targets in `tests/expected.py` (Splink-dependent counts use a tolerance; see
  [`docs/parity.md`](docs/parity.md)).

## Lint

```bash
make lint        # ruff, pyflakes-only (real issues); style is intentionally not enforced
```

## Conventions

- **Vendored modules** (`deed_edges`, `splink_bridge`, `curated_owners`, `llc_edges`,
  `aggregator_officer_audit`, `eval/gate`, `sql/landlords_with_connections.sql`) are forked
  byte-faithfully from WatchlineNYC/WoW so BOR's output matches the reference graph. Keep changes
  minimal and mirror upstream where practical; the shared kernel lives in `bor/_edges.py`.
- **Reproducibility:** `splink==4.0.16` is pinned (the resolution version behind the published
  partition). Owner Portfolio groups are deterministic; the operational-network Louvain tail and the deed
  layer are near- but not bit-exact. Don't assert exact counts — use a tolerance.
- **Person-free by default:** the dataset export withholds owner names unless `--include-names`.
