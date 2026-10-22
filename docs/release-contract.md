# Release contract (draft v0.1.0)

Status: draft for review with the KG, 2026-10-20, amended after the KG developer's review ([release-contract-review.md](release-contract-review.md)). Background: the plan is [kg-handoff-plan-v2.md](kg-handoff-plan-v2.md) and the measurements behind the lineage tables are [w0-findings.md](w0-findings.md). This is the minimal W8 contract from the plan: the shape of a bor release, a worked explanation, and a validator. The machine-readable form is `src/bor/release_schema.py`; `python -m bor.release_validate <dir>` checks a release against it. Fixtures to load and test against live in `tests/fixtures/` (see [Fixtures](#fixtures)).

Where this document and the plan disagree on table names or columns, **this document wins**; the plan's section 4 was a first sketch.

Only the lineage tables are produced today (`bor.lineage`). Everything else is **planned**: specified so it can be reviewed before it is built. The lineage tables built from the reference dump already validate against this contract.

## What a release is

A directory of CSVs plus `manifest.json`. It is frozen: the KG loads a release with the matching source snapshot and never re-runs bor per build (KG note 0007). Both layers (Owner Portfolio, Operational Network) come from one identity resolution (P0).

No table holds a name. Keys are HPD registration and contact ids, BBLs, ACRIS document ids, and run-local opaque ids.

## Keys and namespace

- **Shared objects** (observations, nodes, identities, clusters, decisions) are keyed by a typed local id within the run. `run_id` is in the manifest and is not repeated per row.
- **Layer objects** (groups, memberships, witness, bbl status) carry a `layer` column, `owner_portfolio` or `operational_network`, and it is part of their key, because the two layers share these tables and a node can be in a group in each. (`decision_events.layer` also takes `identity`, for decisions made before the layers exist that both layers use.) Group ids are `OP-<n>` for an Owner Portfolio and `ON-<n>` for an Operational Network, where `n` is the group's minimum node id; the prefix is redundant with `layer` but kept for readability, and the validator checks they agree.
- **Opaque ids.** Identity ids (`I0000001`), cluster ids (`C0000001`) and base-cluster ids are run-local numbers assigned in sorted order of the underlying nlr value. nlr's own ids are an md5 of a person's name and address, and Splink's cluster ids derive from them, so none of them leave the release. The KG derives its own recorded-party key from the observations (KG notes 0006, 0007). Node, group and cluster ids mean nothing across releases.
- **Observations.** `observation_id` is `registration:contact:k`. **The normative join key is (`registration_id`, `registration_contact_id`)**, which the KG's role nodes carry. HPD's contact id repeats in 1,028 cases (616 with differing content); `observations.pair_variants` says how many contents share the pair. Where `pair_variants > 1` the pair is **ambiguous**: attach the evidence to every row of the pair. `k` ranks the contents inside bor and is only for naming a row within this release; the digest behind it is not normative and not exported, and a consumer never has to reproduce it. Identical duplicate rows count as one.
- **Assertion keys.** Every membership and witness row carries an immutable `assertion_key`, `<run_id>/<layer>/<group_id>[/n<node>|/w<step>]`. It is stable for the same frozen assertion and says nothing about enduring owner identity. A node can hold several BBLs, so the KG forms its per-building `link_id` as `<assertion_key>#<bbl>` (KG note 0007); keep the BBL out of the node key.
- **Counting unit.** Counts are **tax lots (BBLs)**, not buildings: `groups.lot_count` is the rental footprint and `total_lot_count` includes co-op and condo lots. The earlier release's `building_count` column is the same count under a misleading name.
- **Partitions.** A node is in at most one group per layer (a key), and a BBL in exactly one node (checked: `node_observations` BBL uniqueness), so a BBL is in at most one group per layer.

## Tables

| Group | Tables | Status |
|---|---|---|
| Lineage | `observations`, `node_observations`, `node_observation_alternatives`, `identity_clusters` (with `base_cluster_id`), `identity_observations`, `node_identity_matches`, `node_cluster`, `node_cluster_alternatives` | implemented |
| Decisions and evidence | `decision_events`, `decision_support` | implemented for the identity layer (`bor.identity_events`, W2) and the deed layer (`bor.deed_events`, W3); group and network decisions are planned (W5, W6a) |
| | `evidence_items`, `evidence_members` | implemented (`bor.deed_events`, W3) |
| Groups and paths | `groups`, `group_members`, `group_bbls`, `group_witness`, `link_sets`, `link_set_members` | implemented for both layers (`bor.group_tables` for Owner Portfolios, W4; `bor.network_tables` for Operational Networks, W5) |
| Operational network | `network_edges`, `network_membership`, `split_attempts` | implemented (`bor.network_tables`, W5) |
| Absence, masking, metrics | `masked_addresses`, `masked_address_nodes` | implemented (W5) |
| | `bbl_status` | implemented (`bor.absence`, W6) |
| | `method_metrics` | implemented (`bor.metrics`, W7) |

The worked example below is a synthetic fixture, but every table it uses for the identity layer is now produced from the real dump. Columns, types, enums, keys and foreign keys are in `release_schema.py`; the table descriptions there are the reference.

## Decisions: one event model

`decision_events` records a decision **at the grain where a rule ran**. A subject and an optional counterpart are typed (`identity`, `base_cluster`, `cluster`, `node`, `bbl`, `address`, `deed_document`, `parcel`, `component`, `group`). An accepted link and a policy outcome are the same kind of row, distinguished by `outcome` (`accepted`, `rejected`, `masked`, `excluded`, `dropped`).

- **Stage** is one of the link-creating stages (`identity.splink_base`, `identity.splink_feedback`, `identity.curated`, `identity.registered_llc`, `deed.held_since`, `deed.linked_successor`, `deed.group` for the hub cap that spans both deed paths, `network.name`, `network.address`) or a group-level policy stage (`owner_portfolio.group_size`, `owner_portfolio.footprint`), so every event has a valid stage.
- **Rule** is a controlled, extend-never-repurpose vocabulary naming what produced the decision: `splink_model`, `first_name_veto`, `common_name_veto`, `shared_company_feedback`, `shared_company_guard`, `curated_owner_list`, `registered_llc_owner_match`, `deed_latest_rule`, `deed_successor_guard`, `deed_hub_cap`, `deed_size_range`, `institutional_screen`, `coop_condo_contact_rule`, `coop_condo_deed_rule`, `aggregator_address_mask`, `splink_address_evidence_mask`, `group_min_size`, `group_footprint_rule`, `name_edge`, `address_edge`. `rule_version` is the version of that rule's definition.
- **Two co-op/condo rules exist** and are named separately: the Owner Portfolio rule (`coop_condo_contact_rule`) uses the share of a building's owner-role HPD contacts described CO-OP or CONDO; the deed rule (`coop_condo_deed_rule`) treats a lot as co-op/condo if its PLUTO building class says so **or** that HPD plurality does, and drops a deed whose parcels are mostly such lots. **Two address masks exist** with the same threshold and different keys: the network address-edge mask and the Splink address-evidence mask.
- **Scores belong only to decisions that were scored.** A base pair carries `score` and `threshold`. A feedback merge joins two pre-feedback *base clusters*, so it has no pair score. Nothing is ever scored for a pair that was never compared.
- **Rejected candidates.** By default the release records pairs **blocked by a gate** (a veto, a mask, a hub cap, a guard), which are the exclusions Q19 asks about. Pairs merely below the threshold are not recorded (`pair_below_threshold` exists for a release that opts in; the volume is unmeasured).
- **`decision_support`** links a decision to the source records it rests on: HPD observations, BBLs, documents. This is what lets a consumer reach contacts without joining on names. Events between identities cite their contacts through `identity_observations`, so `decision_support` carries rows only where the contacts are not any identity's own: for a shared-company merge, the contacts that carry the company (role `shared_company`), on either cluster's buildings.
- **Identity-layer provenance.** `rule_version` is the version of the code that made the decision (`nlr-<version>`, or `bor-<version>` for the curated list). An identity a curated list removed (`curated_exclusion`) is in no cluster, so it is known by `identity_observations` alone, and an `identity` subject may resolve against either table. `detail` is a small JSON object (for example `name_rarity`, `addr_degree`, `n_shared_corporations`); no corporation names are exported.
- **Absence of an event means the rule did not run.** An unexamined candidate is never recorded as rejected.
- **Dropped groups** are never in `groups`. Their `group` event has outcome `dropped`; a published group never does. The lots of a dropped group get their own events.

## Deed evidence

Each deed that links two or more landlord nodes is an `evidence_items` row, with one `evidence_members` row per parcel (BBL, and the node that owns it):

- `held_under_joint_deed`: the joint deed is still the parcel's latest deed.
- `transferred_onward`: the grantee later conveyed the parcel into a single-purpose LLC. This is the linked-successor guard: the latest deed's grantor includes the original grantee, the successor holds at most three buildings, and the onward conveyance is nominal (at most $100), not a market sale. `latest_document_id` and `latest_amount` give that onward deed.

An item is `deed.linked_successor` if any member depends on that guard, else `deed.held_since`; the per-member role is the truth either way, since a single deed can mix both. A member whose node was left out of every clique by the hub cap (more than 20 deeds) is kept and marked `excluded_reason = deed_hub_capped`.

Decisions are recorded where a gate blocked a link that could have formed: a deed-level screen (parcel count, institutional party, co-op/condo majority; stage `deed.held_since` or `deed.linked_successor` for the path it blocked), a parcel the guard rejected (`deed_not_latest`, `successor_not_shell`, `successor_transfer_not_nominal`; subject `parcel`, counterpart the joint deed, with the ACRIS documents in `decision_support`), and a hub node. **A deed whose parcels all belong to one node would link nothing either way, so its gates are not events.**

The queries pick a parcel's latest deed by date and then by document id (the later-recorded wins). Before that tie-break the pick was arbitrary for 23,163 BBLs and two runs of the same code differed by about 19 edges.

## Owner Portfolios and paths

`groups`, `group_members` and `group_bbls` hold the Owner Portfolios (`layer = owner_portfolio`, ids `OP-<n>`); `group_witness` holds a **representative path** for each: a spanning tree over its members, one step fewer than there are nodes, in which every step cites what joined its two nodes (`basis_type` and `basis_id`):

| Stage | The step cites | Resolves in |
|---|---|---|
| `identity.splink_base`, `identity.splink_feedback` | the final identity cluster | `identity_clusters.cluster_id`; its decisions carry that `cluster_id` |
| `identity.curated`, `identity.registered_llc` | a link set | `link_sets.set_id` (`CG…` curated owner, `LG…` one DOF owner-of-record entity), with `link_set_members` |
| `deed.held_since`, `deed.linked_successor` | a deed | `evidence_items.evidence_id` |

A **link set** is a set of nodes tied by a curated owner or by one registered-LLC entity. Its id is opaque; the owner label and the entity name are not exported. For a registered-LLC set each member names the PLUTO lot (`source_bbl`) the entity owns that puts the node in the set.

The path is built by a union-find over these sets in a fixed order that prefers the least questionable evidence: base-cluster identities, curated owners, registered-LLC entities, deeds held since the joint deed, shared-company merges, and last the deeds that depend on the linked-successor guard. **A weak stage appears in a path only where the group cannot be connected without it.** On the reference dump that is 578 of 9,100 steps for the shared-company merge (492 of 6,523 groups) and 30 steps for the guard (28 groups). A step inside a cluster is `splink_base` if the two nodes share a base cluster and `splink_feedback` otherwise. The path is representative, not the unique, strongest or shortest one.

A node whose lots are all co-op or condo stays a member and a path node; `group_bbls.rental = false` explains its lots.

## Operational Networks and paths

The Operational Network is the weakly connected components of a weighted graph of name, address and identity edges, with Louvain cutting the few components over the size cap into smaller networks. **The release carries the complete graph** (`network_edges`, declared `complete` in the manifest): about 57,000 edges, a few megabytes. One row per node pair, with `name_weight + address_weight + identity_weight = weight`, which is exactly the weight Louvain was given (a mutual name match is listed by both nodes and counted twice, as the algorithm does). That one table serves three purposes:

- **A path between any two nodes**, including two in different final networks of one original component: follow the edges. `crosses_networks` marks the edges whose ends ended up in different Operational Networks, which is the boundary.
- **The input of Louvain, reproduced exactly.**
- **The original connectivity.** `network_membership` gives each node's component (`NC-<n>`) and final network; `split_attempts` records every Louvain call, including the ones that found no useful split.

`groups`, `group_members` and `group_bbls` list the networks (`layer = operational_network`, ids `ON-<n>`; every lot is counted, since this layer has no co-op filter). `group_witness` gives a representative path inside each network over its own edges, preferring identity edges (`network.identity`), then name (`network.name`), then address (`network.address`), so a weaker kind appears only where needed.

**A path is a forest where it must be.** Louvain does not guarantee a community is connected by its own edges, and a step never leaves its network. When a network is not, its path leaves more than one piece, and `groups.witness_pieces` says how many (1 for a tree, always so for an Owner Portfolio). The pieces are connected through nodes of other networks in the same component, using `network_edges` with the boundary marked. Louvain is **seeded** (`parameters.operational_network.louvain_seed`, 42): the same graph and seed give the same networks every time, so which communities are disconnected is a fixed property of the release. (Unseeded, the same graph gave a different partition on each call, and one build on the reference dump had a disconnected network that an earlier one did not.) The seed fixes one draw; it does not make that draw better than another.

`masked_addresses` lists the aggregator addresses (shared by more than 25 landlords) whose address edges were masked, under opaque ids with their degree, and `masked_address_nodes` gives the nodes using each; the address text is not exported. Each has a `decision_events` row (stage `network.address`, reason `aggregator_address_masked`).

## How an explanation is assembled

The fixture models seven lots. Identities a and b are linked by a scored base decision (`d1`). b and c are linked by a feedback merge through a shared private company (`d2`), so lots 1 and 3 are in one group although a and c were never compared. Lot 5 joins by a second base decision (`d4`) and is a co-op, left out of the rental footprint. Lot 4 is blocked from c by the first-name veto (`d3`). Lots 6 and 7 link, but their group is dropped as co-op dominated.

1. `group_members` puts nodes 1, 2, 3, 5 in group `OP-1`.
2. `group_witness` gives a **representative** spanning tree: 1–2 at `identity.splink_base`, 2–3 at `identity.splink_feedback`, 3–5 at `identity.splink_base`, each with basis cluster `C0000001`.
3. `decision_events` with `cluster_id = C0000001` give the derivation, and `decision_support` names the exact contacts behind each, including the two contacts on the shared company (`101:10103:0`, `103:10303:0`).
4. `node_observations` and `identity_observations` take every node and identity to an HPD registration and contact.

So the 1–3 link is explained through both decisions, the weak feedback stage is visible because the path needs it, and no 1–3 score exists. A witness path is representative: not the unique, strongest or shortest connection. Other accepted evidence is kept separately.

**Tied nodes.** 639 nodes straddling several clusters are assigned by a tied plurality vote resolved by an arbitrary rule. A witness step that rests on such a node (`node_cluster.tied`) must be shown with that caveat, with its `node_cluster_alternatives` listed.

## Absence

`bbl_status` has one row per lot **per layer**, over every lot in the PLUTO snapshot plus any lot that is in a node or a group (on the reference dump 858,625 lots, 137 MB as CSV; a missing row means nothing). The detail, with every reason that applies, is in `decision_events`; this table is the summary.

How the primary reason is chosen (`bor.absence`): the facts about the source and the lot's own events are pooled, and the reason from the earliest stage wins (precedence below; ties follow the order of the codes).

- **Facts:** the lot has no HPD registration (`no_registration`); it has one but no qualifying person owner contact (`no_owner_contact`); in the Owner Portfolio layer only, its node matched no resolved identity (`unmatched_node`). A lot in a group has none of these.
- **Events:** an event bears on a lot when it names the lot (a `bbl` or `parcel`), or a node, identity, base cluster, masked address or published group that contains it, or (a deed-level screen) cites it as a parcel in `decision_support`. Events of layer `identity` bear on both layers; deed and Owner Portfolio events only on theirs; the network's address mask only on the network. The validator uses the same rule, so the summary and its check cannot drift apart.
- **Group-level policy events** (stage `owner_portfolio.footprint`) are emitted for the co-op/condo rule: a group dropped as co-op dominated has one `dropped` event on the group and an `excluded` event on each of its lots; a co-op lot left out of a surviving group's footprint has its own `excluded` event.

On the reference dump, in the Owner Portfolio layer 43,318 lots are in a group, 412 are co-ops left out of a footprint and 814,895 are not in a group. Of the latter 677,771 have no HPD registration (outside source coverage), 114,002 have no linkage, 9,507 are registered with no qualifying contact, 2,576 belong to the 219 groups dropped as co-op dominated, and the rest carry a gate reason (for example 1,923 first-name veto, 528 institutional screen, 363 not their latest deed, 166 unmatched node). The Operational Network has 71,256 lots in a network. These describe what the pipeline decided; none establishes that no real relationship exists.

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
| `below_eligibility_rule` | `deed_parcels_out_of_range`, `deed_not_latest`, `successor_not_shell`, `successor_transfer_not_nominal`, `first_name_veto`, `common_name_veto`, `shared_company_name_not_rare`, `shared_company_first_name_conflict`, `shared_company_degree_cap`, `shared_company_degree_unknown`, `group_below_min_size` |
| `no_qualifying_linkage` | `no_linkage`, `pair_below_threshold` |

`outside_method_input` is the KG's proposed fifth reason (KG note 0007, awaiting acceptance): the source holds the record but the method did not use it. **No user-facing sentence should call those codes "source coverage".** All of these describe what the pipeline decided; none establishes that no real relationship exists, and comparisons beyond the candidates bor evaluated (for example Q7, Q22) are the KG's to make.

## Metrics

`method_metrics` states how well each link-creating stage did on the evaluation sample. It is a transcription of the evaluation's `metrics.json` (`bor.eval.score`) with the integers behind each proportion; nothing is estimated at build time and the numbers are stored exactly as the scorer published them. It is **not a link probability** and must not be shown as one: it is the share of sampled pairs judged correct in a stratum, on one snapshot, and a group's path chains several pairs, so no step's precision is the group's. Precision only: recall is not estimated.

- **Rows.** The key is `(stage, metric)`. `metric` is `precision_strict` (pairs judged the same owner on cross-source corroboration only, C1), `precision_inclusive` (C1 plus same-source-verified, C2) or `split_precision`. Both link precisions are published. Strict leaves C2 pairs out of numerator and denominator, as the scorer does.
- **Split precision** (the share of pairs the method keeps apart that really are different owners) belongs to a sampled *population*, not a stage: `method.aggregator_splits` (pairs at a masked aggregator address) and `method.hard_negatives` (surname-sharing pairs no signal links). For the second, one minus it estimates how often such a pair is really the same owner, on that population only; it is not recall overall.
- **One row per stratum; no pooled figure.** Strata are sampled at very different rates.
- **Every link-creating stage has a row**, and the validator requires one for every stage a witness path cites. A stage the evaluation did not draw has null estimates and a note saying why: a missing row would read as "no problem". The identity sample draws pairs from inside resolved clusters, which include shared-company merges, so `identity.splink_base` pools them and `identity.splink_feedback` has no estimate of its own. The network stages are unevaluated because the sample asked whether a pair is the same owner, which is not what an Operational Network claims.
- **Columns.** `n` is pairs sampled in the stratum; `numerator`/`denominator` the counted pairs (indeterminate ones excluded); `confidence_level` 0.95; `interval_method` names the Wilson interval and notes a census (a stratum whose frame was sampled in full, where the interval is conservative); `estimator` says what was counted; `strata_ref`, `eval_artifact` (with a hash of `metrics.json`) and `eval_version` (the frame and its builder commit) identify the evaluation.
- **`adjudication_status`** says who produced the gold: `none`, `synthetic`, `human_llm_provisional` (one human annotator, an LLM second reader and an LLM-run resolution of their disagreements) or `blind_human` (a second blind human and human arbitration). Every row is `provisional` unless it is `blind_human`; the current evaluation is `human_llm_provisional`, and a release candidate is rebuilt from the re-adjudicated gold. The status is a fact about the gold that the build cannot derive, so `--gold-status` is required with `--eval-dir`.
- Build: `make build-release SNAPSHOT_ID=<id> EVAL_DIR=eval_out GOLD_STATUS=human_llm_provisional`. Without `EVAL_DIR` the table still has a row per link stage, all unevaluated. The scorer must be a version that records counts (`python -m bor.eval.score` rewrites `metrics.json` with the same figures plus counts and the gold's annotators).

`explain` shows a weak stage's published strict precision beside it, with the caveat, when the release has one.

## Manifest

Required: `schema_version`, `run_id`, `snapshot_id`, `pluto_snapshot_id`, `effective_date`, `bor_revision`, `nlr_revision`, `source_tree_hash`, `dependency_lock_digest`, `threshold`, `parameters`, `source_tables`, `deed_selection_rule`, `normalizer_versions`, `artifacts`, `stage_vocabulary_version`, `reason_vocabulary_version`, `output_checksums`.

- `snapshot_id` is proposed as `<source>-<YYYY-MM-DD>`, the latest record date in the source data (for the reference dump, `justfixwow-2026-05-29`), and the manifest repeats it exactly; the KG confirms the form. The date is the data's, not the build day.
- `source_tables` maps each source table bor read (HPD contacts and registrations, `wow_landlords`, the ACRIS tables, PLUTO) to `{row_count, fingerprint, fingerprint_method}`. The KG compares these with its own load and refuses a mismatch. The fingerprint method is fixed in W1.
- `deed_selection_rule` is `{rule, version}`. bor currently selects `doctype ILIKE '%DEED%'`, which includes `DEED COR` and `DEED, TS`; the KG can check document types from the ACRIS ids in `evidence_members`.
- `artifacts` declares each artifact `complete` or `representative`. Storage choices never silently change what a release means.
- `effective_date` is the deed cut-off the queries used in place of `CURRENT_DATE`, so a rerun means the same thing; it is also recorded under `parameters.deed.as_of`.
- `source_tree_hash` hashes the code files themselves (bor and nlr, whose changes are part of what produced the result), because a commit SHA and a dirty flag do not identify modified content. `code` gives each package's version, revision, dirty flag and own hash; `dependency_lock_digest` hashes `uv.lock`; `environment` records the versions actually loaded (Splink, DuckDB, pandas, Python). A tagged release is built with `--require-clean`. To build and validate one: `make build-release SNAPSHOT_ID=<id> [AS_OF=YYYY-MM-DD] [REQUIRE_CLEAN=1]` (output in `release/contract`; `make validate-release` re-checks it).
- `source_tables[t].fingerprint` is `sum(first 60 bits of md5(row::text))` over the table, with `row_count`; the exact SQL is `bor.manifest.fingerprint_sql`, so the KG can run it on its own load. It covers the nine tables bor reads, including `landlords_with_connections`, whose node ids come from an unordered `row_number()` and so only match the same build.
- `excerpt` is present only when the release is a cut of a larger one (`bor.excerpt`): `{of_run_id, seed_groups, rule, tables_omitted, events_omitted, evidence_omitted}`. An excerpt keeps its parent's `run_id`, `snapshot_id`, source fingerprints and assertion keys, so it is verified exactly as the whole release is, and every row is a row of the parent. It leaves things out (the table list, events that point outside it, deeds with parcels outside it) and says so; a missing row in an excerpt means nothing, and `masked_addresses.degree` is the parent's, so it may exceed the listed nodes.
- `synthetic: true` marks a made-up release (the synthetic fixture). It is never present on a real one.
- `diagnostics` is not part of the contract proper: counts a reader may want, such as `latest_deed_ties` (BBLs whose latest deed date is shared by two or more documents, where the query's pick is arbitrary) and the mapping report.

## Reading a release: `explain`

`bor.explain` turns the tables into plain-language answers, using the release alone (no database): `lot <bbl>` (is it in a group, and if not the primary reason, the other reasons that apply and the events behind them), `pair <bbl> <bbl> [layer]` (the representative path between two lots, step by step, with the weak stages it depends on named; across a Louvain boundary, the connecting edges with the boundary marked) and `group <id>` (size, composition and the mix of evidence). `python -m bor.explain <release_dir> pair 3000010001 3000010003`, or `make explain ARGS="lot 3000010001"`; add `--json` for structured output. A pair that is not in one group also gets the **closest evidence** the tables hold: a decision between their people that a gate did not accept (with its rule and score), a deed they share that did not link them (for example because one parcel's node was left out by the hub cap), or another reading of a node whose registration lists several contacts, with the vote and the tie. Every answer carries the caveat that it is a lead, not a determination, and that the path is representative. It is also the reference for what a consumer can reconstruct from the tables.

## Fixtures

Three frozen releases in `tests/fixtures/`, each loadable on its own with no database (`read_release`, or any CSV reader):

- **`synthetic_release/`** (`make fixtures`; generator `make_synthetic_release.py`): one made-up run, `synthetic-0001`, covering all 25 tables and every case a consumer has to handle. Every BBL starts with 9 (there is no borough 9), every id is in a reserved range and the manifest says `synthetic: true`. Its cases: a transitive feedback bridge (lots 1 and 3 grouped though never compared), a deed mixing held and transferred parcels, a hub-capped node that keeps another link, a dropped group and a footprint exclusion, a deed screened out as co-op dominated, an ambiguous contact mapping with a tied cluster, a component cut by Louvain with the boundary edge marked and a masked hub address, a deed bridging two resolved owners, a registered-company link set and a curated owner, and one lot for each reason a lot can be absent. `bbl_status` is computed by the real `bor.absence`, not written by hand. Its `method_metrics` rows are labeled synthetic.
- **`citadel_excerpt/`** (`make excerpt`): real rows. Owner Portfolio `OP-67966`, the Citadel deed veil-pierce from the README, cut by `bor.excerpt` from a full build of the reference dump: one 2008 deed over 15 parcels, re-titled in 2015 at $0 into 12 single-purpose LLCs, three nodes that no name or address links because the hub office they share is masked (33 landlords against a threshold of 25). Public-record identifiers only, no names. The parent build was made from an uncommitted tree (`code.bor.dirty`), so the release candidate regenerates this fixture.
- **`mini_release/`**: the seven-lot example the worked explanation above is written against.

`tests/test_kg_fixture.py` is the approval gate (plan section 7) as tests, run on the first two: each fixture validates; the run and snapshot are verified (every assertion key carries the run id, checksums hold, a changed file is detected); grouped lots trace to exact HPD registrations and contacts; each path step names its stage and cites its evidence; a cross-community pair shows its path with the boundary edge; every absence reason is explained and each event-backed one cites an event; a published metric is read as stored. `tests/test_excerpt.py` checks that every Owner Portfolio of the synthetic release excerpts to a valid release that answers `explain` exactly as its parent does.

## What the validator checks

Columns, types, nullability, enums, keys and foreign keys, then: a BBL belongs to one node; `k` is below `pair_variants`; ambiguous node rows carry no selection and list every candidate; a straddling node has one alternative per cluster and exactly one selected; a witness is a connected, acyclic spanning tree over the group's members; accepted events carry no reason and every other outcome does; event references resolve by type, and a group subject is published unless its outcome is `dropped`; group ids carry the prefix of their layer; group lot counts match their BBL lists; assertion keys are unique; each witness step's stage fixes the kind of evidence it cites and that evidence exists; a link set's size matches its members; `excluded_from_footprint` matches the non-rental lots; reason codes agree with their top level and the primary reason respects the precedence; an unevaluated metric has a note, a precision sits inside its interval and equals its counts' ratio, a split precision belongs to a method scope and the others to a stage, and every stage a path cites has a metric row; manifest fields, source-table entries and file checksums, and that every assertion key begins with the manifest's `run_id` (the tables and the manifest describe one run). An excerpt may list fewer nodes at a masked address than its `degree`. It cannot check the lot universe or that the decisions are the ones bor really made.

## Mapping to the KG (documented, not imported)

The field-by-field mapping, the checks a loader makes and what it must never do are in [kg-mapping.md](kg-mapping.md). Each release also ships a generated data dictionary, `DATA.md` (`bor.release_docs`), rendered from the schema and the manifest, so it matches the files.

The KG loader marks bor-derived assertions `reliability: II`, `source_category: project_derived`, `review_status: unreviewed` (notes 0002–0004, 0007), keeps the HPD/ACRIS source facts distinct, and takes `snapshot_id` from the manifest. bor does not adopt the KG's ontology or graph model; whether evidence becomes list properties, per-edge relationships or promoted nodes is the KG's decision (note 0005).

## Settled by the KG review

Opaque identity ids; one polymorphic `decision_events` table; gate-blocked rejections only; the PLUTO lot universe, identified in the manifest; `link_id = assertion_key#bbl`; joining observations on (registration, contact id).

## Still open

1. **Witness only, or the full network graph?** Decided after the W5 size spike.
2. **Run-scoped nodes versus edge expansion** onto identities in the graph (KG note 0007, item 5). The KG's call once the node and edge tables exist.
3. **The fingerprint method** for large source tables (W1), and the form of `snapshot_id` (proposed above; the KG confirms).
4. **Whether the fifth reason is accepted** (KG note 0007); the codes under it are ready either way.

## Not promised

Exact rerun determinism (resolution is stochastic; a fixed run serializes deterministically and is checksummed). Recall. Cross-release identity of groups. That a grouping is true: every group is a lead, not a determination.
