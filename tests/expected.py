"""Frozen regression targets, validated against the reference `justfixwow` dump and the live
WatchlineNYC knowledge graph (see docs/parity.md).

All counts are checked with a tolerance. Splink-dependent counts jitter ~0.05% run-to-run
(u-sampling over DuckDB). The deed layer has no Splink but is still not bit-exact: ACRIS
latest-deed tiebreaks and data vintage move a handful of edges (observed 941 and 935).
"""

# Deed layer (no Splink). Deterministic since the latest-deed tie-break (document id); before it, two
# runs differed by ~19 edges (942 vs 937). The tolerance stays for data-vintage drift in the dump.
DEED_EDGES = 947
DEED_NODES = 1551

# Owner groups (Splink-dependent → tolerant).
OWNER_GROUPS = 6522
OWNER_GROUP_NODES = 15621
COMPOSITION = {"identity": 6449, "deed_only": 61, "deed_bridged": 12}

# Operational network (Splink + Louvain tail → tolerant).
OPERATIONAL_NETWORKS_MULTI = 9672   # components with >= 2 members

# Divergence vs Who Owns What.
OWNERS_CROSSING = 760
PORTFOLIOS_HIDING = 616

# lwc substrate (reference dump).
LWC_NODES = 118_493

# Absolute tolerance for Splink-jittered counts (~0.05% of ~15-30k ≈ a few dozen).
TOL = 30
