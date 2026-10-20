# Release contract (draft v0.1.0)

Status: draft for review with the KG, 2026-10-20. This is the minimal W8 contract from `kg-handoff-plan-v2.md`: the shape of a bor release, a worked explanation, and a validator. The machine-readable form is `src/bor/release_schema.py`; `python -m bor.release_validate <dir>` checks a release against it. A synthetic example lives in `tests/fixtures/mini_release/`.

Only the lineage tables are produced today (`bor.lineage`, branch `w0-mapping-tables`). Everything else is **planned**: specified so it can be reviewed before it is built. The lineage tables built from the reference dump already validate against this contract.

## What a release is

A directory of CSVs plus `manifest.json`. It is frozen: the KG loads a release with the matching source snapshot and never re-runs bor per build. Both layers (Owner Portfolio, Operational Network) come from one identity resolution (P0).

No table holds a name. Keys are HPD registration and contact ids, BBLs, ACRIS document ids, run-local ids, and nlr identity ids.

## Keys and namespace

- **Shared objects** (observations, nodes, identities, clusters, decisions) are keyed by a typed local id within the run. `run_id` is in the manifest and is not repeated per row.
- **Layer objects** (groups, memberships, witness, bbl status) are also keyed by `layer`, `owner_portfolio` or `operational_network`.
- Node, group and cluster ids are **run-local**: stable within a release, meaningless across releases.
- `observation_id` is `registration:contact:k`. HPD's contact id repeats in 1,028 cases (616 with differing content), so `k` ranks differing contents sharing the pair; it is 0 when the pair is unique. Nothing about the contact's content is exported.
- Every membership and witness row carries an immutable `assertion_key` of the form `<run_id>/<layer>/<group_id>[/n<node>|/w<step>]`. It is stable for the same frozen assertion and says nothing about enduring owner identity. The KG can use it as, or derive from it, its `link_id` (KG note 0005).
- A node is in at most one group per layer, and a BBL in at most one node, so a BBL is in at most one group per layer. The validator checks the first; the second is true by construction in WoW's `wow_landlords` (one row per BBL).

## Tables

| Group | Tables | Status |
|---|---|---|
| Lineage | `observations`, `node_observations`, `node_observation_alternatives`, `identity_clusters`, `identity_observations`, `node_identity_matches`, `node_cluster`, `node_cluster_alternatives` | implemented |
| Decisions and evidence | `decision_events`, `decision_support`, `evidence_items`, `evidence_members` | planned (W2, W3, W6a) |
| Groups and paths | `groups`, `group_members`, `group_bbls`, `group_witness` | planned (W4) |
| Operational network | `network_edges`, `network_membership`, `split_attempts` | planned (W5) |
| Absence, masking, metrics | `bbl_status`, `masked_addresses`, `masked_address_nodes`, `method_metrics` | planned (W6b, W7) |

Columns, types, enums, keys and foreign keys for each are in `release_schema.py`; the table descriptions there are the reference.

## Decisions: one event model

`decision_events` records a decision **at the grain where a rule ran**. A subject and an optional counterpart are typed (`identity`, `base_cluster`, `cluster`, `node`, `bbl`, `address`, `deed_document`, `parcel`, `component`, `group`). An accepted link and a policy outcome are the same kind of row, distinguished by `outcome` (`accepted`, `rejected`, `masked`, `excluded`, `dropped`).

- **Stage** is one of: `identity.splink_base`, `identity.splink_feedback`, `identity.curated`, `identity.registered_llc`, `deed.held_since`, `deed.linked_successor`, `network.name`, `network.address`.
- **Scores belong only to decisions that were scored.** A base pair carries `score` and `threshold`. A feedback merge joins two pre-feedback *base clusters*, so it has no pair score. Nothing is ever scored for an A–C pair that was never compared.
- **`decision_support`** links a decision to the exact source records it rests on: HPD observations, BBLs, documents. This is what lets a consumer reach contacts without joining on names.
- **Absence of an event means the rule did not run.** An unexamined candidate is never recorded as rejected.

## How an explanation is assembled

The fixture models three lots, A, B and C. A and B are linked by a scored base decision. B and C are linked by a feedback merge through a shared private company. A and C were never compared.

1. `group_members` puts nodes 1, 2, 3 in group `OG-1`.
2. `group_witness` gives a **representative** spanning tree: 1–2 at stage `identity.splink_base`, 2–3 at stage `identity.splink_feedback`, both with basis cluster `K1`.
3. `decision_events` with `cluster_id = K1` give the derivation: `d1` (base, A–B, score 0.9995) and `d2` (feedback, between base clusters `bc-1` and `bc-2`).
4. `decision_support` for `d2` names the two contacts on the shared company (`101:10103:0`, `103:10303:0`).
5. `node_observations` and `identity_observations` take every node and identity to an HPD registration and contact.

So the A–C link is explained through both decisions, the weak feedback stage is visible because the path needs it, and no A–C score exists. A witness path is representative: it is not the unique, strongest or shortest connection, and other accepted evidence is kept separately.

## Absence

`bbl_status` is a **summary** over the PLUTO-snapshot lot universe; a missing row means nothing. A lot not in a group has a detailed `reason_code`, which maps to one of the four top-level reasons:

| Top level | Detailed codes |
|---|---|
| `no_qualifying_linkage` | `no_linkage` |
| `excluded_by_policy` | `coop_condo_dominated`, `institutional_screen`, `deed_hub_capped`, `aggregator_address_masked`, `curated_exclusion` |
| `below_eligibility_rule` | `deed_parcels_out_of_range`, `successor_guard_failed`, `group_below_min_size` |
| `outside_source_coverage` | `no_registration`, `no_owner_contact`, `not_latest_registration`, `unmatched_node` |

These codes describe what the pipeline decided. They do not establish that no real relationship exists, and comparisons beyond the candidates bor evaluated (for example Q7, Q22) are the KG's to make. The detailed grain lives in `decision_events`; one lot can have several reasons there.

## Metrics

`method_metrics` states the precision of a *method stage*, with its unit, population, estimate, interval and method, estimator and strata where weighted, evaluation artifact and version, and adjudication status. It is **not a link probability** and must not be shown as one. Every row is `provisional` until blind human re-adjudication; an unevaluated stage has a null estimate and a note. Precision-only: recall is not estimated.

## Manifest

Required: `schema_version`, `run_id`, `snapshot_id`, `effective_date`, `bor_revision`, `nlr_revision`, `source_tree_hash`, `dependency_lock_digest`, `threshold`, `parameters`, `artifacts`, `stage_vocabulary_version`, `reason_vocabulary_version`, `output_checksums`.

`artifacts` declares each artifact `complete` or `representative` (for example `group_witness` is representative; `network_edges` may be either, decided after the size spike). Storage choices never silently change what a release means.

## What the validator checks

Columns, types, nullability, enums, keys and foreign keys, then: ambiguous node rows carry no selection and list every candidate; a straddling node has one alternative per cluster and exactly one selected; a witness is a connected, acyclic spanning tree over the group's members; accepted events carry no reason and every other outcome does; event references resolve by type; group counts match their BBL lists; assertion keys are unique; reason codes agree with their top level; an unevaluated metric has a note and a precision sits inside its interval; manifest fields and file checksums. It cannot check the lot universe or that the decisions are the ones bor really made.

## Mapping to the KG (documented, not imported)

The KG loader marks bor-derived assertions `reliability: II`, `source_category: project_derived`, `review_status: unreviewed` (notes 0002–0004), keeps the HPD/ACRIS source facts distinct, and takes `snapshot_id` from the manifest. bor does not adopt the KG's ontology or graph model; whether evidence becomes list properties, per-edge relationships or promoted nodes is the KG's decision (note 0005).

## Open questions for the KG

1. **Identity ids.** `identity_id` is nlr's md5 of contact kind, name and address, the same formula as the KG's recorded-party key (note 0006). But it is a hash of a person's name and address, so guessable from a list of names. If the release is public, should identities be opaque ids with the KG deriving its own key from the observations? "No names exported" is accurate; "not reversible" would not be.
2. **Polymorphic events.** Is one `decision_events` table with typed subjects acceptable, or does the loader prefer typed tables per stage?
3. **Rejected candidates.** Which rejected pairs are recorded? Every scored pair near the threshold, or only those a gate blocked? The volume is unmeasured.
4. **Witness versus full graph.** Does the KG load only the witness, or also `network_edges`? (Affects the size decision in W5.)
5. **`assertion_key`** against the loader's `link_id` derivation.
6. **Reason vocabulary.** Is the detailed-to-top-level mapping above the one the KG's absence contract wants?
7. **Lot universe.** Confirm `bbl_status` covers the PLUTO snapshot the KG loads.

## Not promised

Exact rerun determinism (resolution is stochastic; a fixed run serializes deterministically and is checksummed). Recall. Cross-release identity of groups. That a grouping is true: every group is a lead, not a determination.
