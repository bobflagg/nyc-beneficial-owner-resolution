# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - unreleased (the date is added when the release is tagged)

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
- Depends on [`nlr`](https://github.com/bobflagg/nyc-landlord-resolution) `v0.2.0` (resolution with decision capture) for record
  linkage; `splink` pinned to `4.0.16`.

- **Fixtures and the approval gate (W9).** `tests/fixtures/synthetic_release` (all 25 tables, every case
  and absence reason, made-up lots), `tests/fixtures/citadel_excerpt` (real rows: Owner Portfolio
  `OP-67966`), and `tests/test_kg_fixture.py`, which runs the gate with no database. `bor.excerpt`
  (`make excerpt`) cuts a self-contained, validating excerpt of a release around chosen Owner
  Portfolios; the manifest says it is one (`excerpt`) and a made-up release says `synthetic`.
- `explain pair` shows the closest evidence for a pair that is not in one group: a blocked decision, a
  shared deed that did not link them, or a tied alternative reading of a node.

- **Method metrics (W7).** `bor.metrics` builds `method_metrics` from the evaluation: strict and inclusive
  precision per stratum, split precision for the aggregator and hard-negative strata, a null row with a
  note for each unevaluated link stage, and the gold's status (`human_llm_provisional` today). `bor.eval.score`
  now also records the counts behind each proportion and the gold's annotators (the published figures are
  unchanged). The validator checks the counts, the stage/scope split and metric-stage coverage;
  `explain` shows a weak stage's published estimate.

- **Release docs (W10).** `docs/release.md` is rewritten around the contract release (the legacy export is
  now a side note), `docs/data.md` lists what a release fingerprints and what BOR writes,
  `docs/kg-mapping.md` is a loader's checklist and field mapping, and every release and fixture ships a
  `DATA.md` generated from the schema and manifest (`bor.release_docs`). The README gains a short section on
  the frozen release and its no-names policy.

### Changed
- Licenses: the code is MIT and the data of a release is CC BY 4.0, stated in the README, each release's `DATA.md`
  (a new "License and citation" section) and the release notes; the author's ORCID is in `CITATION.cff`.
- A decision about a pair of identities or base clusters is recorded with the smaller id as its subject, whichever way
  nlr listed the pair; the validator checks it. Two fits of the same partition used to differ in the orientation of a
  few symmetric events (and so in the numbering of the decisions after them).
- `bor.release build` reports a caller's mistake (a snapshot id of the wrong form or date, a missing gold status, a
  missing evaluation, an unclean tree under `--require-clean`) as one line, before any work, instead of a traceback.
- Snapshot id (KG design note 0008): `<source>-<YYYY-MM-DD>[-rN]`, one source dump, with the date of the data, not the build
  (`justfixwow-2026-05-29` for the reference dump): the earlier of the newest ACRIS `recordedfiled` and HPD
  `lastregistrationdate`. The manifest gains `snapshot_date` and `snapshot_date_basis` (both newest dates) and
  loses `pluto_snapshot_id` (PLUTO is part of the dump). The build refuses an id that disagrees with the data,
  and the validator checks the form, the date and the basis.
- Recorded decisions: `bor.export` stays as a documented convenience, releases ship with the provisional gold
  labeled as such, and `bbl_status` keeps every PLUTO lot in both layers.
- nlr is pinned at `v0.2.0` (was `v0.1.0`): the release's identity evidence comes from its decision capture.
- A package installed from a git commit (the pinned nlr) is recorded with `dirty: false`, so `--require-clean`
  accepts it; it used to be `null`, which `--require-clean` refuses as unidentified.
- The manifest no longer records the builder's local checkout path (`code.*.checkout`).
- The validator checks that every assertion key begins with the manifest's `run_id`.
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
- First release, `v0.1.0`: a tagged GitHub release with the data attached, cut per [`docs/release.md`](docs/release.md). No DOI yet.
