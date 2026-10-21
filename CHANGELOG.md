# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Owner Portfolio layer** (`bor.owner_portfolios`) — Owner Portfolios off-graph (union-find over
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

### Changed
- **Group id prefixes:** Owner Portfolios are `OP-<min nodeid>` (was `OG-`) and Operational
  Network groups are `ON-<min nodeid>` (was `PF-`). A clean break: nothing had been released with the
  old prefixes, and ids were never stable across builds. The `owner_portfolio_id` and `operational_network_id`
  column names are unchanged.

- **Owner Portfolio terminology.** The ownership layer is "Owner Portfolio" throughout, matching the
  release contract and the `OP-` ids: `bor.owner_groups` is `bor.owner_portfolios`,
  `resolve_owner_groups` is `resolve_owner_portfolios`, `OwnerGroup` is `OwnerPortfolio`, and the
  legacy release files and columns are `owner_portfolios.csv`, `owner_portfolio_bbls.csv` and
  `owner_portfolio_id`. The network layer's `portfolio_id` is `operational_network_id`, so
  "portfolio" no longer means two things. Nothing had been released under the old names.
- **Seeded Louvain.** The Operational Network's Louvain step seeds igraph's RNG before every call
  (`LOUVAIN_SEED = 42`, recorded in the release manifest) and builds the graph from sorted edges, so
  the same graph cuts into the same networks every time. Unseeded, the partition differed on each call.
- **Data dictionary.** The first line of the generated `DATA.md` now lists HPD contacts, the main
  input, alongside HPD registrations.

### Notes
- Not yet released. Cut a versioned, DOI'd release per [`docs/release.md`](docs/release.md).
