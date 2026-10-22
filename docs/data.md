# Data & setup

BOR resolves ownership over a **Postgres** holding NYC public-record tables. It depends on the
*data*, not on any WatchlineNYC pipeline: given the tables below, BOR builds the one derived table
it needs (`landlords_with_connections`) itself, then runs.

## Where the data comes from

Almost everything ships in JustFix's **`justfixwow`** database dump — the same public dump that
backs [Who Owns What](https://github.com/JustFixNYC/who-owns-what), built by JustFix's loader from
NYC open data (HPD registrations/contacts, ACRIS, PLUTO). Restore that dump into a Postgres and you
have every *input* table. BOR then materializes `landlords_with_connections` from it.

> The maximally reproducible, dump-free form — DuckDB directly over the public HPD/ACRIS/PLUTO CSVs
> — is the **v2** roadmap milestone (mirrors `nlr`'s public-CSV path). Until then, the JustFix dump
> is the practical seed.

## Required tables

| Table | Provides | Source | Used by |
|---|---|---|---|
| `wow_landlords` | one contact per (bbl, registration) with a standardized business address | JustFix dump | **input to `landlords_with_connections`** |
| `landlords_with_connections` (lwc) | nodes (name, bizaddr, bbls) + precomputed name/address edges | **BOR builds it** (`bor.build_lwc`) | every layer |
| `hpd_contacts`, `hpd_registrations` | raw owner contacts / registrations | JustFix dump (HPD) | record linkage (`nlr`), co-op/condo, servicer audit |
| `hpd_registrations_grouped_by_bbl_with_contacts` | registration→bbl grouping | JustFix dump | co-op/condo classification |
| `real_property_master`, `real_property_legals`, `real_property_parties` | ACRIS deeds (grantor/grantee, docamount, doctype) | JustFix dump (ACRIS open data) | deed veil-pierce (`bor.deed_edges`) |
| `pluto_latest` | DOF owner name, building class | JustFix dump (PLUTO) | registered-LLC edges, co-op/condo guard |
| `wow.wow_portfolios` | WoW's own portfolio clustering `(orig_id, bbls, landlord_names)` | JustFix dump | the paired benchmark (`bor.eval`) |

All are read **unqualified**; in `justfixwow` they resolve via `search_path` to the `wow` schema
(where the connecting `wow` user's schema is first). `nlr` reads the same Postgres via the same
`PG*` config.

## What the release fingerprints

A contract release records, for each of nine of these tables, a row count and a fingerprint (`bor.manifest.fingerprint_sql`): `hpd_contacts`, `hpd_registrations`, `hpd_registrations_grouped_by_bbl_with_contacts`, `wow_landlords`, `landlords_with_connections`, `pluto_latest`, `real_property_master`, `real_property_legals` and `real_property_parties`. A consumer compares them with its own load before trusting the release, and a different dump or a rebuilt `landlords_with_connections` (its node ids come from an unordered `row_number()`) gives different ones. `wow.wow_portfolios` is read only by the benchmark.

## Setup

```bash
# 1. Restore the JustFix `justfixwow` dump into a local Postgres (see the WoW project for the dump).
# 2. Point BOR at it:
cp .env.example .env            # set PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD
# 3. Build the one derived table BOR needs (pg_trgm self-join over wow_landlords, ~1-2 min):
uv run python -m bor.build_lwc
#    (or check an existing one: uv run python -m bor.build_lwc --verify-only)
```

After that, all layers run: `resolve_owner_portfolios`, `resolve_operational_networks`,
`bor.deed_edges.deed_edges`, and the benchmark `python -m bor.eval.divergence`.

## What BOR writes

- **The contract release** (`bor.release`, `make build-release`): 25 CSV tables, a generated `DATA.md` and `manifest.json`, in `release/contract`. Run-local opaque ids, no names. See [release-contract.md](release-contract.md) and [release.md](release.md).
- **The legacy dataset** (`bor.export`): four membership CSVs in `release/`. Person-free by default.
- **The evaluation** (`bor.eval.*`) reads and writes `eval_out/`, which is git-ignored: the blinded packet carries public-record names, and the key joins pairs back to them. Only the scorer's aggregate `metrics.json` and the frame manifest are inputs to a release (`make build-release EVAL_DIR=eval_out`).

## A note on `landlords_with_connections`

lwc is WoW's landlord graph, vendored **verbatim** as `bor/sql/landlords_with_connections.sql` so
BOR's nodeids and edge weights match WoW's exactly. `nodeid = row_number()` is a per-build
surrogate: stable within one build (all layers read the same lwc in one run) but not across
rebuilds, so exported/persisted ids key off it only within a release. See
[`parity.md`](parity.md).
