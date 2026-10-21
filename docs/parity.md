# Parity & reproducibility

BOR resolves Owner Portfolios **off-graph** (no Neo4j). This records how the off-graph
partition was validated against WatchlineNYC's live knowledge-graph partition, and what level of
reproducibility to expect.

## Method

The live KG builds Owner Portfolios as connected components of `CONNECTED_BY_SPLINK ∪ CONNECTED_BY_DEED`
edges materialized in Neo4j. BOR builds the *same* edges from Postgres (forked verbatim from the
pipeline) and runs the identical union-find in memory, then compares the two node→group partitions.
Both are keyed on the `landlords_with_connections` (lwc) `nodeid`, which is stable within a single
build, so the partitions are directly comparable.

## Result (splink 4.0.16, matching the KG build)

| Comparison | Exact-label agreement | Group count | Composition |
|---|---|---|---|
| **BOR vs live KG** | **15,621 / 15,621 = 100.000%** of KG nodes | 6,522 (KG) vs 6,522–6,524 (BOR) | `{identity 6449, deed_only 61, deed_bridged 12}` — exact |
| BOR run-A vs run-B (same version, same data) | 15,612 / 15,620 = 99.949% | 6,522 vs 6,524 | — |

Every node in the KG's Owner Portfolio partition is reproduced by BOR with the identical group label.
The deed layer matches exactly (941 `CONNECTED_BY_DEED` edges — byte-identical code).

## The reproducibility ceiling

The Owner Portfolio partition is **not byte-reproducible run-to-run**, even at a fixed splink version and identical
input: two BOR runs of the same code disagree on ~8 of 15,621 nodes (~0.05%), always in tiny
borderline groups (size 2–5). The cause is Splink's `u`-training, which samples pairs over DuckDB —
seeded, but only approximately seed-stable under DuckDB's parallel sampling. A handful of pairs sit
right at the 0.999 clustering threshold and flip between draws.

Two consequences:

1. **BOR is a faithful port.** BOR-vs-KG agreement (100% of KG nodes) is *at least as good* as the
   pipeline's agreement with itself across runs (99.95%). The residual is the resolution layer's
   own noise, shared with `nlr`, not an artifact of decoupling from Neo4j.
2. **Pin the splink version.** Across splink *patch* versions the drift is larger (4.0.17 shifted
   the group count by 1 and moved ~8 nodes). `pyproject.toml` pins `splink==4.0.16` — the version
   behind the published / KG partition — so the group count and composition are stable; the
   sub-0.05% run-to-run jitter remains and is expected.

Downstream figures (e.g. the divergence-vs-WoW counts) are therefore stable to ~99.95%; report them
as such rather than as exact integers reproducible to the unit.

## Operational-network layer (v1.1)

The operational network (`bor.operational_network`) is WCC(+Louvain) over name ∪ address ∪ splink
edges, mirroring WatchlineNYC's `:Portfolio`. It has a different reproducibility profile than the
Owner Portfolios, because it uses **two** clustering steps:

- **WCC** (connected components) — deterministic, reproduces exactly.
- **Louvain** — splits only components whose BBL-sum exceeds `MAX_SIZE = 300`. WatchlineNYC runs
  GDS's seedless, default-granularity Louvain; BOR runs igraph's weighted `community_multilevel`.
  These are different implementations and **cannot** byte-match (GDS does not reproduce itself
  run-to-run either). This affects only the tail of oversized components.

Parity vs the live KG's multi-member Portfolios:

| Metric | Result |
|---|---|
| Node universe | **identical** — 30,924 nodes both sides, 0 difference |
| Portfolios reproduced exactly (identical member set) | **9,662 / 9,672 = 99.90%** |
| Nodes in an identically-membered portfolio | **30,813 / 30,924 = 99.64%** |
| Final portfolios > 300 BBLs | **1 (max 424)** — exact |
| Split origin (BOR) | 9,627 WCC (exact) + 47 Louvain |

So all ≤300-BBL portfolios — the WCC majority — reproduce exactly; the ~10 differing portfolios
(~111 nodes) are entirely within the Louvain-split oversized tail (a few dozen large operators),
which is expected and inherent to Louvain, not a defect of the off-graph port. Portfolio ids
(`ON-<min nodeid>` in BOR, `PF-<run_id>-<n>` in the WatchlineNYC graph) are not comparable across builds — compare
by member set / BBL overlap, as above.
