# Release contract (draft v0.1.0)

Status: draft for review with the KG, 2026-10-20, amended after the KG developer's review ([release-contract-review.md](release-contract-review.md)). Background: the plan is [kg-handoff-plan-v2.md](kg-handoff-plan-v2.md) and the measurements behind the lineage tables are [w0-findings.md](w0-findings.md). This is the minimal W8 contract from the plan: the shape of a bor release, a worked explanation, and a validator. The machine-readable form is `src/bor/release_schema.py`; `python -m bor.release_validate <dir>` checks a release against it. A synthetic example lives in `tests/fixtures/mini_release/` (regenerate with `tests/fixtures/make_mini_release.py`).

Where this document and the plan disagree on table names or columns, **this document wins**; the plan's section 4 was a first sketch.

Only the lineage tables are produced today (`bor.lineage`). Everything else is **planned**: specified so it can be reviewed before it is built. The lineage tables built from the reference dump already validate against this contract.

## What a release is

A directory of CSVs plus `manifest.json`. It is frozen: the KG loads a release with the matching source snapshot and never re-runs bor per build (KG note 0007). Both layers (Owner Portfolio, Operational Network) come from one identity resolution (P0).

No table holds a name. Keys are HPD registration and contact ids, BBLs, ACRIS document ids, and run-local opaque ids.

## Keys and namespace

- **Shared objects** (observations, nodes, identities, clusters, decisions) are keyed by a typed local id within the run. `run_id` is in the manifest and is not repeated per row.
- **Layer objects** (groups, memberships, witness, bbl status) are also keyed by `layer`, `owner_portfolio` or `operational_network`.
- **Opaque ids.** Identity ids (`I0000001`), cluster ids (`C0000001`) and base-cluster ids are run-local numbers assigned in sorted order of the underlying nlr value. nlr's own ids are an md5 of a person's name and address, and Splink's cluster ids derive from them, so none of them leave the release. The KG derives its own recorded-party key from the observations (KG notes 0006, 0007). Node, group and cluster ids mean nothing across releases.
- **Observations.** `observation_id` is `registration:contact:k`. **The normative join key is (`registration_id`, `registration_contact_id`)**, which the KG's role nodes carry. HPD's contact id repeats in 1,028 cases (616 with differing content); `observations.pair_variants` says how many contents share the pair. Where `pair_variants > 1` the pair is **ambiguous**: attach the evidence to every row of the pair. `k` ranks the contents inside bor and is only for naming a row within this release; the digest behind it is not normative and not exported, and a consumer never has to reproduce it. Identical duplicate rows count as one.
- **Assertion keys.** Every membership and witness row carries an immutable `assertion_key`, `<run_id>/<layer>/<group_id>[/n<node>|/w<step>]`. It is stable for the same frozen assertion and says nothing about enduring owner identity. A node can hold several BBLs, so the KG forms its per-building `link_id` as `<assertion_key>#<bbl>` (KG note 0007); keep the BBL out of the node key.
- **Counting unit.** Counts are **tax lots (BBLs)**, not buildings: `groups.lot_count` is the rental footprint and `total_lot_count` includes co-op and condo lots. The earlier release's `building_count` column is the same count under a misleading name.
- **Partitions.** A node is in at most one group per layer (a key), and a BBL in exactly one node (checked: `node_observations` BBL uniqueness), so a BBL is in at most one group per layer.

## Tables

| Group | Tables | Status |
|---|---|---|
| Lineage | `observations`, `node_observations`, `node_observation_alternatives`, `identity_clusters`, `identity_observations`, `node_identity_matches`, `node_cluster`, `node_cluster_alternatives` | implemented, except that `identity_clusters.base_cluster_id` (the pre-feedback cluster) waits on W2 |
| Decisions and evidence | `decision_events`, `decision_support`, `evidence_items`, `evidence_members` | planned (W2, W3, W6a) |
| Groups and paths | `groups`, `group_members`, `group_bbls`, `group_witness` | planned (W4) |
| Operational network | `network_edges`, `network_membership`, `split_attempts` | planned (W5) |
| Absence, masking, metrics | `bbl_status`, `masked_addresses`, `masked_address_nodes`, `method_metrics` | planned (W6b, W7) |

The worked example below uses base clusters, which the real tables cannot produce until W2. Columns, types, enums, keys and foreign keys are in `release_schema.py`; the table descriptions there are the reference.

## Decisions: one event model

`decision_events` records a decision **at the grain where a rule ran**. A subject and an optional counterpart are typed (`identity`, `base_cluster`, `cluster`, `node`, `bbl`, `address`, `deed_document`, `parcel`, `component`, `group`). An accepted link and a policy outcome are the same kind of row, distinguished by `outcome` (`accepted`, `rejected`, `masked`, `excluded`, `dropped`).

- **Stage** is one of the link-creating stages (`identity.splink_base`, `identity.splink_feedback`, `identity.curated`, `identity.registered_llc`, `deed.held_since`, `deed.linked_successor`, `network.name`, `network.address`) or a group-level policy stage (`owner_portfolio.group_size`, `owner_portfolio.footprint`), so every event has a valid stage.
- **Rule** is a controlled, extend-never-repurpose vocabulary naming what produced the decision: `splink_model`, `first_name_veto`, `common_name_veto`, `shared_company_feedback`, `shared_company_guard`, `curated_owner_list`, `registered_llc_owner_match`, `deed_latest_rule`, `deed_successor_guard`, `deed_hub_cap`, `deed_size_range`, `institutional_screen`, `coop_condo_contact_rule`, `coop_condo_building_class_rule`, `aggregator_address_mask`, `splink_address_evidence_mask`, `group_min_size`, `group_footprint_rule`, `name_edge`, `address_edge`. `rule_version` is the version of that rule's definition.
- **Two co-op/condo rules exist** and are named separately: the owner-group rule uses HPD `contactdescription`; the deed code uses PLUTO building classes. **Two address masks exist** with the same threshold and different keys: the network address-edge mask and the Splink address-evidence mask.
- **Scores belong only to decisions that were scored.** A base pair carries `score` and `threshold`. A feedback merge joins two pre-feedback *base clusters*, so it has no pair score. Nothing is ever scored for a pair that was never compared.
- **Rejected candidates.** By default the release records pairs **blocked by a gate** (a veto, a mask, a hub cap, a guard), which are the exclusions Q19 asks about. Pairs merely below the threshold are not recorded (`pair_below_threshold` exists for a release that opts in; the volume is unmeasured).
- **`decision_support`** links a decision to the source records it rests on: HPD observations, BBLs, documents. This is what lets a consumer reach contacts without joining on names.
- **Absence of an event means the rule did not run.** An unexamined candidate is never recorded as rejected.
- **Dropped groups** are never in `groups`. Their `group` event has outcome `dropped`; a published group never does. The lots of a dropped group get their own events.

## How an explanation is assembled

The fixture models seven lots. Identities a and b are linked by a scored base decision (`d1`). b and c are linked by a feedback merge through a shared private company (`d2`), so lots 1 and 3 are in one group although a and c were never compared. Lot 5 joins by a second base decision (`d4`) and is a co-op, left out of the rental footprint. Lot 4 is blocked from c by the first-name veto (`d3`). Lots 6 and 7 link, but their group is dropped as co-op dominated.

1. `group_members` puts nodes 1, 2, 3, 5 in group `OG-1`.
2. `group_witness` gives a **representative** spanning tree: 1–2 at `identity.splink_base`, 2–3 at `identity.splink_feedback`, 3–5 at `identity.splink_base`, each with basis cluster `C0000001`.
3. `decision_events` with `cluster_id = C0000001` give the derivation, and `decision_support` names the exact contacts behind each, including the two contacts on the shared company (`101:10103:0`, `103:10303:0`).
4. `node_observations` and `identity_observations` take every node and identity to an HPD registration and contact.

So the 1–3 link is explained through both decisions, the weak feedback stage is visible because the path needs it, and no 1–3 score exists. A witness path is representative: not the unique, strongest or shortest connection. Other accepted evidence is kept separately.

**Tied nodes.** 639 nodes straddling several clusters are assigned by a tied plurality vote resolved by an arbitrary rule. A witness step that rests on such a node (`node_cluster.tied`) must be shown with that caveat, with its `node_cluster_alternatives` listed.

## Absence

`bbl_status` is a **summary** over the PLUTO-snapshot lot universe (the manifest names the snapshot); a missing row means nothing. A lot has one status:

- `in_group`, with its group;
- `not_in_group`, with a reason and no group;
- `excluded_from_footprint`: a lot in a published group that is left out of its rental footprint (`group_bbls.rental = false`), for example a co-op. It keeps its group and carries a reason.

A detailed `reason_code` maps to one of five top-level reasons, listed in **precedence order**. When several reasons apply, `bbl_status.reason_code` is the one from the earliest stage that removed the lot (ties inside a level follow the order below); the validator rejects a primary reason that ranks below a reason in the lot's own events.

| Top level | Detailed codes |
|---|---|
| `outside_source_coverage` | `no_registration` |
| `outside_method_input` | `no_owner_contact`, `not_latest_registration`, `unmatched_node` |
| `excluded_by_policy` | `coop_condo_excluded` (a building), `coop_condo_dominated` (a whole group), `institutional_screen`, `deed_hub_capped`, `aggregator_address_masked`, `address_evidence_masked`, `curated_exclusion` |
| `below_eligibility_rule` | `deed_parcels_out_of_range`, `deed_not_latest`, `successor_not_shell`, `successor_transfer_not_nominal`, `first_name_veto`, `common_name_veto`, `shared_company_name_not_rare`, `shared_company_first_name_conflict`, `shared_company_degree_cap`, `group_below_min_size` |
| `no_qualifying_linkage` | `no_linkage`, `pair_below_threshold` |

`outside_method_input` is the KG's proposed fifth reason (KG note 0007, awaiting acceptance): the source holds the record but the method did not use it. **No user-facing sentence should call those codes "source coverage".** All of these describe what the pipeline decided; none establishes that no real relationship exists, and comparisons beyond the candidates bor evaluated (for example Q7, Q22) are the KG's to make.

## Metrics

`method_metrics` states the precision of a *method stage*, with its unit, population, estimate, interval and method, estimator and strata where weighted, evaluation artifact and version, and adjudication status. It is **not a link probability** and must not be shown as one. Every row is `provisional` until blind human re-adjudication; an unevaluated stage has a null estimate and a note. Precision-only: recall is not estimated.

## Manifest

Required: `schema_version`, `run_id`, `snapshot_id`, `pluto_snapshot_id`, `effective_date`, `bor_revision`, `nlr_revision`, `source_tree_hash`, `dependency_lock_digest`, `threshold`, `parameters`, `source_tables`, `deed_selection_rule`, `normalizer_versions`, `artifacts`, `stage_vocabulary_version`, `reason_vocabulary_version`, `output_checksums`.

- `snapshot_id` takes the form the KG defines (an open KG decision); the manifest repeats it exactly.
- `source_tables` maps each source table bor read (HPD contacts and registrations, `wow_landlords`, the ACRIS tables, PLUTO) to `{row_count, fingerprint, fingerprint_method}`. The KG compares these with its own load and refuses a mismatch. The fingerprint method is fixed in W1.
- `deed_selection_rule` is `{rule, version}`. bor currently selects `doctype ILIKE '%DEED%'`, which includes `DEED COR` and `DEED, TS`; the KG can check document types from the ACRIS ids in `evidence_members`.
- `artifacts` declares each artifact `complete` or `representative`. Storage choices never silently change what a release means.

## What the validator checks

Columns, types, nullability, enums, keys and foreign keys, then: a BBL belongs to one node; `k` is below `pair_variants`; ambiguous node rows carry no selection and list every candidate; a straddling node has one alternative per cluster and exactly one selected; a witness is a connected, acyclic spanning tree over the group's members; accepted events carry no reason and every other outcome does; event references resolve by type, and a group subject is published unless its outcome is `dropped`; group lot counts match their BBL lists; assertion keys are unique; `excluded_from_footprint` matches the non-rental lots; reason codes agree with their top level and the primary reason respects the precedence; an unevaluated metric has a note and a precision sits inside its interval; manifest fields, source-table entries and file checksums. It cannot check the lot universe or that the decisions are the ones bor really made.

## Mapping to the KG (documented, not imported)

The KG loader marks bor-derived assertions `reliability: II`, `source_category: project_derived`, `review_status: unreviewed` (notes 0002–0004, 0007), keeps the HPD/ACRIS source facts distinct, and takes `snapshot_id` from the manifest. bor does not adopt the KG's ontology or graph model; whether evidence becomes list properties, per-edge relationships or promoted nodes is the KG's decision (note 0005).

## Settled by the KG review

Opaque identity ids; one polymorphic `decision_events` table; gate-blocked rejections only; the PLUTO lot universe, identified in the manifest; `link_id = assertion_key#bbl`; joining observations on (registration, contact id).

## Still open

1. **Witness only, or the full network graph?** Decided after the W5 size spike.
2. **Run-scoped nodes versus edge expansion** onto identities in the graph (KG note 0007, item 5). The KG's call once the node and edge tables exist.
3. **The fingerprint method** for large source tables (W1), and the form of `snapshot_id` (KG).
4. **Whether the fifth reason is accepted** (KG note 0007); the codes under it are ready either way.

## Not promised

Exact rerun determinism (resolution is stochastic; a fixed run serializes deterministically and is checksummed). Recall. Cross-release identity of groups. That a grouping is true: every group is a lead, not a determination.
