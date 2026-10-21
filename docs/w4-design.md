# W4 design: Owner Portfolios and witness paths

Status: design, 2026-10-21; implemented on branch `w4-groups-witness` as described. Covers W4 of `kg-handoff-plan-v2.md` for the **Owner Portfolio** layer. The Operational Network's groups and witness come with its edges in W5.

## Goal

Give the KG, for every Owner Portfolio, the members, the lots, and a **representative path**: a set of node-to-node steps, each citing the evidence that joined the two nodes, that shows why the group is one group. A consumer can then answer "why are these two buildings grouped?" by following the path between their nodes and reading each step's stage.

## What joins nodes (and what each step cites)

The group partition is the connected components of four kinds of links, all of which tie a *set* of nodes together (a clique, or a star when large). A step in the path cites the set, not a pair:

| Stage | Set | Basis cited |
|---|---|---|
| `identity.splink_base` | nodes whose identities share a base cluster | `identity_cluster` = the final cluster id (its decisions carry that `cluster_id`) |
| `identity.splink_feedback` | the final cluster, joining nodes whose base clusters differ | `identity_cluster` |
| `identity.curated` | a hand-verified owner | `link_set` (new) |
| `identity.registered_llc` | lots with the same DOF owner-of-record entity | `link_set` (new) |
| `deed.held_since` / `deed.linked_successor` | a deed's parcels | `evidence_item` |

**Two new tables** make the curated and registered-LLC sets citable, since they have no decision events of their own: `link_sets(set_id, stage, rule, rule_version, size)` and `link_set_members(set_id, node_id, source_bbl)`. Set ids are opaque (`CG…` curated, `LG…` registered-LLC), numbered by smallest member node; the curated owners' labels and the DOF entity names are not exported. For a registered-LLC set, `source_bbl` is the PLUTO lot owned by the entity that put the node in the set; the KG can read the owner of record from PLUTO itself. `group_witness.basis_type` gains `link_set`.

## The path: a spanning tree, preferring strong evidence

Per group, take the sets that touch it and connect their nodes with a union-find, recording an edge only when it joins two parts that were not yet connected. That gives a tree: connected, acyclic, one step fewer than there are members. A set connects its nodes through its first node, so every step is a genuine pair from that set.

**Order decides which tree you get**, so it is fixed, deterministic, and prefers the least questionable evidence: base-cluster identities, then curated owners, then registered-LLC sets, then deeds held since the joint deed, then the shared-company merges, and last the deeds that depend on the linked-successor guard. A weak stage therefore appears in a path only when the group cannot be connected without it. This is what the contract means by a "representative" path; it is not the unique, strongest or shortest one.

**Stage of a step:**
- A step inside a cluster is `identity.splink_base` if the two nodes share a base cluster, `identity.splink_feedback` otherwise. A node's base clusters are those of the identities matched to it that sit in its assigned final cluster.
- A deed step is `deed.linked_successor` if either end's only membership in that deed is a transferred-onward parcel, else `deed.held_since`. A deed's star centre is a node that holds a parcel directly when there is one.
- Deed sets leave out hub nodes (the deed layer drops them), exactly as the edges do.

## Tables

`groups`, `group_members`, `group_bbls`, `group_witness` as in the contract, for `layer = owner_portfolio`:
- `lot_count` is the rental footprint and `total_lot_count` includes co-op/condo lots; `group_bbls.rental = false` marks the latter. A node whose lots are all non-rental stays a member and a path node; the `rental` flags explain it.
- Every row carries an `assertion_key` (`<run_id>/owner_portfolio/<group_id>[/n<node>|/w<step>]`). `run_id` is therefore fixed before the tables are built.

## Not in W4

- The decision events for groups dropped as co-op dominated (stage `owner_portfolio.footprint`) and the per-lot absence summaries are W6a/W6b.
- The Operational Network layer's groups and its path are W5, because its path is made of weighted name and address edges.
- `explain()` is W8.

## How it is checked

- The partition is computed by the existing code; the witness is built independently from the sets. A test requires that, for every group, the witness is a spanning tree over exactly that group's members, so any disagreement between the two is a failure rather than a silent drift.
- The release now reuses the one captured identity resolution for the Owner Portfolios (previously the groups refit Splink on their own). This is the substance of P0, done by passing the captured node-to-cluster assignment and the deed edges in, rather than through a separate run context.
- Validator: every witness basis resolves (`identity_cluster` to `identity_clusters`, `evidence_item` to `evidence_items`, `link_set` to `link_sets`), the stage matches its basis type, and the existing tree, count and assertion-key checks apply.
