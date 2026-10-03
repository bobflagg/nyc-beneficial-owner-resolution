# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Owner-group layer** (`bor.owner_groups`) — beneficial owner groups off-graph (union-find over
  `CONNECTED_BY_SPLINK ∪ CONNECTED_BY_DEED`, co-op/condo exclusion). Reproduces the live KG's
  partition exactly.
- **Deed veil-pierce** (`bor.deed_edges`) — name-free ACRIS co-conveyance edges with the
  linked-successor guard.
- **Operational-network layer** (`bor.operational_network`) — WCC + Louvain over name/address/splink,
  aggregator-masked. WCC exact; the >300-BBL Louvain tail approximate.
- **Benchmark** — `bor.eval.divergence` (paired vs Who Owns What: 760 crossing / 616 hiding) and
  `bor.eval.gate` (the WoW gate).
- **Data layer** — `bor.build_lwc` builds `landlords_with_connections` from `wow_landlords`
  (`bor/sql/`), so BOR needs only the data, not the WatchlineNYC pipeline. See `docs/data.md`.
- **Dataset export** — `bor.export`, person-free by default (BBL-keyed, opaque ids).
- **Tests** — unit (pure logic) + DB-gated regression suite.
- **Docs** — `docs/parity.md`, `docs/data.md`, `docs/release.md`.
- Depends on [`nlr`](https://github.com/bobflagg/nyc-landlord-resolution) `v0.1.0` for record
  linkage; `splink` pinned to `4.0.16`.

### Notes
- Not yet released. Cut a versioned, DOI'd release per [`docs/release.md`](docs/release.md).
