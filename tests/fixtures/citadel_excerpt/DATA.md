# Beneficial Ownership Resolution: release `2026-05-29-7edb54cf`

This directory is an **excerpt** of run 2026-05-29-7edb54cf (a few Owner Portfolios and what they cite). Contract version 0.1.0.

Owner Portfolios and Operational Networks resolved from NYC public records (HPD registrations and
contacts, ACRIS deeds, PLUTO), with the evidence behind every grouping. **This release contains no owner
names.** Lots are identified by BBL (the public tax-lot id); people, companies and decisions by opaque ids
that are local to one run.

**Read it as leads, not verdicts.** Every grouping is inferred by a method whose precision was measured on a
sample (`method_metrics`). A precision is the share of sampled pairs judged correct in one stratum; it is *not*
the probability that a given link is right, and a group's path chains several pairs. A lot's absence from a
group is a rule the method applied or a record it never saw. It is never evidence that the owners differ, and a
missing row in `bbl_status` means nothing.

## Provenance

| | |
|---|---|
| Run | `2026-05-29-7edb54cf` |
| Source snapshot | `justfixwow-2026-05-29` |
| PLUTO snapshot | `justfixwow-2026-05-29` |
| Deed cut-off | `2026-05-29` |
| Built | `2026-10-22T16:50:03+00:00` |
| bor revision | `52b168efcfe5f871943552e070f54fbcec22e6f4` |
| nlr revision | `6a9b1a19ac1b16c9a4f217c34e8711b5634d9c79` |
| Source-tree hash | `e2111fd432511ea5f6f1ff1980b3b750baee381d15ca5707c6462ae61c2f9585` |
| Lockfile digest | `ba882e9c5ec55c64e8b3b5a97ea7b0078b4b0a75cbd2e6f3b2f876ced67aaead` |
| Splink threshold | `0.999` |

Source tables, as fingerprinted (compare with your own load using `bor.manifest.fingerprint_sql`):

| table | rows | fingerprint |
|---|---|---|
| `hpd_contacts` | 782,024 | `446723573507456567766101` |
| `hpd_registrations` | 203,236 | `116952552060625267150906` |
| `hpd_registrations_grouped_by_bbl_with_contacts` | 193,710 | `111639779985286756401565` |
| `wow_landlords` | 171,347 | `98790780466472732475958` |
| `landlords_with_connections` | 118,493 | `68417755281667780513872` |
| `pluto_latest` | 858,602 | `495732327790862256518451` |
| `real_property_master` | 17,009,118 | `9805580637410314130378991` |
| `real_property_legals` | 22,652,824 | `13056767151149614161428376` |
| `real_property_parties` | 46,375,598 | `26737199831231077171312090` |

Method metrics rest on a gold of status: `human_llm_provisional`. Rows are `provisional` unless the status is `blind_human`.

## Keys and ids

- **Layers.** `owner_portfolio` (one resolved owner: identity links and deeds) and `operational_network`
  (operational linkage by name and address, looser by design). Ids are `OP-<n>` and `ON-<n>`, where `n` is the
  group's smallest node id. A node is in at most one group per layer; a BBL is in exactly one node.
- **Run-local ids.** Identities (`I…`), clusters (`C…`), base clusters (`BC…`), evidence (`DV…`), link sets
  (`CG…`, `LG…`), decisions (`D…`, `E…`, `G…`, `N…`), network edges (`NE…`) and masked addresses (`A…`) mean
  something only inside this run. Nothing is stable across releases; membership is the durable content.
- **`assertion_key`** = `<run_id>/<layer>/<group_id>` (a member adds `/n<node>`, a path step `/w<step>`). The
  KG's link id for a lot is `<assertion_key>#<bbl>`.
- **Observations** are HPD contacts, `registration:contact:k`. Join them to HPD on (`registration_id`,
  `registration_contact_id`), never on a name.
- **Counting unit** is the tax lot (BBL), not the building.

## Files

| file | rows | what it is |
|---|---|---|
| `observations.csv` | 21 | HPD contact observations referenced elsewhere. |
| `node_observations.csv` | 20 | The registration and contact WoW used for each (node, BBL). |
| `node_observation_alternatives.csv` | 0 | The tied candidate contacts of ambiguous (node, BBL) rows. |
| `identity_clusters.csv` | 3 | nlr identity -> final cluster (and, from W2, its pre-feedback base cluster). |
| `identity_observations.csv` | 20 | Which HPD contacts, per BBL, an identity aggregates: the contacts nlr used. |
| `node_identity_matches.csv` | 19 | The (name, bbl) matches that attach identities to nodes. |
| `node_cluster.csv` | 3 | The cluster each matched node is assigned. |
| `node_cluster_alternatives.csv` | 0 | Every cluster a straddling node matched, with votes and the selected one. |
| `decision_events.csv` | 4 | One row per decision at the grain where a rule ran: accepted links and policy outcomes alike. |
| `decision_support.csv` | 0 | The source records a decision rests on. |
| `evidence_items.csv` | 1 | Multi-member assertions: a qualifying deed bundle. |
| `evidence_members.csv` | 15 | Per parcel: held under the joint deed, or transferred onward. |
| `link_sets.csv` | 0 | Sets of nodes tied by a curated owner (CG...) or by one DOF owner-of-record entity (LG...). |
| `link_set_members.csv` | 0 | The nodes of a link set. |
| `groups.csv` | 1 | Owner Portfolios (OP-<n>) and Operational Networks (ON-<n>), n = the minimum node id (run-local). |
| `group_members.csv` | 3 | Node partition: a node is in at most one group per layer. |
| `group_bbls.csv` | 20 | BBL listing; rental=false marks co-op/condo lots outside the published footprint. |
| `group_witness.csv` | 2 | A representative spanning tree per group (not unique, strongest or shortest). |
| `bbl_status.csv` | 40 | Summary over the PLUTO-snapshot lot universe; a missing row means nothing. |
| `masked_addresses.csv` | 1 | Aggregator addresses masked from the network layer. |
| `masked_address_nodes.csv` | 3 | Crosswalk from a masked address to the nodes (and so HPD observations) using it. |
| `method_metrics.csv` | 20 | Method precision (not a link probability). |

`manifest.json` holds the provenance above and the sha256 of every file.

## Tables

### `observations`

HPD contact observations referenced elsewhere. id = registration:contact:k. The join key is (registration_id, registration_contact_id); where pair_variants > 1 the pair is ambiguous and evidence attaches to every row of the pair.

Key: `observation_id`.

| column | type | null | values |
|---|---|---|---|
| `observation_id` | str |  |  |
| `registration_id` | int |  |  |
| `registration_contact_id` | int |  |  |
| `k` | int |  |  |
| `pair_variants` | int |  |  |

### `node_observations`

The registration and contact WoW used for each (node, BBL).

Key: `node_id`, `bbl`.

References `observations` on `selected_observation_id`.

| column | type | null | values |
|---|---|---|---|
| `node_id` | int |  |  |
| `bbl` | str |  |  |
| `registration_id` | int |  |  |
| `n_candidates` | int |  |  |
| `selected_observation_id` | str | yes |  |
| `ambiguous` | bool |  |  |

### `node_observation_alternatives`

The tied candidate contacts of ambiguous (node, BBL) rows.

Key: `node_id`, `bbl`, `observation_id`.

References `node_observations` on `node_id`, `bbl`.
References `observations` on `observation_id`.

| column | type | null | values |
|---|---|---|---|
| `node_id` | int |  |  |
| `bbl` | str |  |  |
| `observation_id` | str |  |  |

### `identity_clusters`

nlr identity -> final cluster (and, from W2, its pre-feedback base cluster).

Key: `identity_id`.

| column | type | null | values |
|---|---|---|---|
| `identity_id` | str |  |  |
| `cluster_id` | str |  |  |
| `base_cluster_id` | str | yes |  |

### `identity_observations`

Which HPD contacts, per BBL, an identity aggregates: the contacts nlr used. Also covers identities a curated list removed, which are in no cluster.

Key: `identity_id`, `bbl`, `observation_id`.

References `observations` on `observation_id`.

| column | type | null | values |
|---|---|---|---|
| `identity_id` | str |  |  |
| `bbl` | str |  |  |
| `observation_id` | str |  |  |
| `tied_registration` | bool |  |  |

### `node_identity_matches`

The (name, bbl) matches that attach identities to nodes.

Key: `node_id`, `identity_id`, `bbl`.

References `node_observations` on `node_id`, `bbl`.
References `identity_clusters` on `identity_id`.

| column | type | null | values |
|---|---|---|---|
| `node_id` | int |  |  |
| `identity_id` | str |  |  |
| `bbl` | str |  |  |

### `node_cluster`

The cluster each matched node is assigned. tied = plurality vote tied.

Key: `node_id`.

References `identity_clusters` on `cluster_id`.

| column | type | null | values |
|---|---|---|---|
| `node_id` | int |  |  |
| `cluster_id` | str |  |  |
| `n_clusters` | int |  |  |
| `tied` | bool |  |  |

### `node_cluster_alternatives`

Every cluster a straddling node matched, with votes and the selected one.

Key: `node_id`, `cluster_id`.

References `node_cluster` on `node_id`.
References `identity_clusters` on `cluster_id`.

| column | type | null | values |
|---|---|---|---|
| `node_id` | int |  |  |
| `cluster_id` | str |  |  |
| `votes` | int |  |  |
| `selected` | bool |  |  |

### `decision_events`

One row per decision at the grain where a rule ran: accepted links and policy outcomes alike. Absence of an event means the rule did not run. Identity, deed, group and network decisions are all recorded here.

Key: `decision_id`.

| column | type | null | values |
|---|---|---|---|
| `decision_id` | str |  |  |
| `layer` | str |  | `identity`, `owner_portfolio`, `operational_network` |
| `stage` | str |  | 12 values, see below |
| `subject_type` | str |  | 10 values, see below |
| `subject_id` | str |  |  |
| `counterpart_type` | str | yes | 10 values, see below |
| `counterpart_id` | str | yes |  |
| `outcome` | str |  | `accepted`, `rejected`, `masked`, `excluded`, `dropped` |
| `reason_code` | str | yes | 24 values, see below |
| `rule` | str |  | 20 values, see below |
| `rule_version` | str |  |  |
| `score` | float | yes |  |
| `threshold` | float | yes |  |
| `cluster_id` | str | yes |  |
| `detail` | str | yes |  |

### `decision_support`

The source records a decision rests on.

Key: `decision_id`, `support_type`, `support_id`, `role`.

References `decision_events` on `decision_id`.

| column | type | null | values |
|---|---|---|---|
| `decision_id` | str |  |  |
| `support_type` | str |  | `observation`, `bbl`, `document` |
| `support_id` | str |  |  |
| `role` | str |  |  |

### `evidence_items`

Multi-member assertions: a qualifying deed bundle.

Key: `evidence_id`.

| column | type | null | values |
|---|---|---|---|
| `evidence_id` | str |  |  |
| `stage` | str |  | `deed.held_since`, `deed.linked_successor` |
| `document_id` | str |  |  |
| `parcel_count` | int |  |  |
| `rule_version` | str |  |  |

### `evidence_members`

Per parcel: held under the joint deed, or transferred onward. excluded_reason marks a member whose node was left out of the deed's clique (deed_hub_capped).

Key: `evidence_id`, `bbl`.

References `evidence_items` on `evidence_id`.

| column | type | null | values |
|---|---|---|---|
| `evidence_id` | str |  |  |
| `bbl` | str |  |  |
| `node_id` | int |  |  |
| `role` | str |  | `held_under_joint_deed`, `transferred_onward` |
| `original_document_id` | str |  |  |
| `latest_document_id` | str | yes |  |
| `latest_amount` | float | yes |  |
| `excluded_reason` | str | yes | 24 values, see below |

### `link_sets`

Sets of nodes tied by a curated owner (CG...) or by one DOF owner-of-record entity (LG...). Ids are opaque; the owner label and the entity name are not exported.

Key: `set_id`.

| column | type | null | values |
|---|---|---|---|
| `set_id` | str |  |  |
| `stage` | str |  | `identity.curated`, `identity.registered_llc` |
| `rule` | str |  | 20 values, see below |
| `rule_version` | str |  |  |
| `size` | int |  |  |

### `link_set_members`

The nodes of a link set. For a registered-LLC set, source_bbl is the PLUTO lot the entity owns that puts the node in the set; null for a curated owner.

Key: `set_id`, `node_id`, `source_bbl`.

References `link_sets` on `set_id`.

| column | type | null | values |
|---|---|---|---|
| `set_id` | str |  |  |
| `node_id` | int |  |  |
| `source_bbl` | str | yes |  |

### `groups`

Owner Portfolios (OP-<n>) and Operational Networks (ON-<n>), n = the minimum node id (run-local). witness_pieces is the number of connected pieces the group's path leaves: 1 (a spanning tree) unless its own edges cannot connect it. Counting unit: tax lots (BBLs), not buildings. lot_count is the rental footprint, total_lot_count includes co-op/condo lots.

Key: `layer`, `group_id`.

| column | type | null | values |
|---|---|---|---|
| `layer` | str |  | `owner_portfolio`, `operational_network` |
| `group_id` | str |  |  |
| `assertion_key` | str |  |  |
| `composition` | str | yes | `identity`, `deed_only`, `deed_bridged` |
| `split` | str | yes | `wcc`, `louvain` |
| `lot_count` | int |  |  |
| `total_lot_count` | int |  |  |
| `witness_pieces` | int |  |  |

### `group_members`

Node partition: a node is in at most one group per layer.

Key: `layer`, `node_id`.

References `groups` on `layer`, `group_id`.

| column | type | null | values |
|---|---|---|---|
| `layer` | str |  | `owner_portfolio`, `operational_network` |
| `group_id` | str |  |  |
| `node_id` | int |  |  |
| `assertion_key` | str |  |  |

### `group_bbls`

BBL listing; rental=false marks co-op/condo lots outside the published footprint.

Key: `layer`, `bbl`.

References `groups` on `layer`, `group_id`.

| column | type | null | values |
|---|---|---|---|
| `layer` | str |  | `owner_portfolio`, `operational_network` |
| `group_id` | str |  |  |
| `bbl` | str |  |  |
| `rental` | bool |  |  |

### `group_witness`

A representative spanning tree per group (not unique, strongest or shortest). Each step cites the set that joined its two nodes (basis).

Key: `layer`, `group_id`, `step`.

References `groups` on `layer`, `group_id`.

| column | type | null | values |
|---|---|---|---|
| `layer` | str |  | `owner_portfolio`, `operational_network` |
| `group_id` | str |  |  |
| `step` | int |  |  |
| `node_a` | int |  |  |
| `node_b` | int |  |  |
| `stage` | str |  | 12 values, see below |
| `basis_type` | str |  | `identity_cluster`, `evidence_item`, `link_set`, `network_edge` |
| `basis_id` | str |  |  |
| `assertion_key` | str |  |  |

### `bbl_status`

Summary over the PLUTO-snapshot lot universe; a missing row means nothing. excluded_from_footprint: in a published group but left out of its rental footprint (group_bbls.rental = false); it keeps its group_id and carries a reason. reason_code is the primary reason, by PRECEDENCE.

Key: `layer`, `bbl`.

| column | type | null | values |
|---|---|---|---|
| `layer` | str |  | `owner_portfolio`, `operational_network` |
| `bbl` | str |  |  |
| `status` | str |  | `in_group`, `not_in_group`, `excluded_from_footprint` |
| `group_id` | str | yes |  |
| `reason_code` | str | yes | 24 values, see below |
| `top_level_reason` | str | yes | `outside_source_coverage`, `outside_method_input`, `excluded_by_policy`, `below_eligibility_rule`, `no_qualifying_linkage` |

### `masked_addresses`

Aggregator addresses masked from the network layer.

Key: `address_id`.

| column | type | null | values |
|---|---|---|---|
| `address_id` | str |  |  |
| `method` | str |  |  |
| `normalizer_version` | str |  |  |
| `degree` | int |  |  |
| `degree_unit` | str |  |  |
| `threshold` | int |  |  |
| `decision` | str |  | `masked` |

### `masked_address_nodes`

Crosswalk from a masked address to the nodes (and so HPD observations) using it.

Key: `address_id`, `node_id`.

References `masked_addresses` on `address_id`.

| column | type | null | values |
|---|---|---|---|
| `address_id` | str |  |  |
| `node_id` | int |  |  |

### `method_metrics`

Method precision (not a link probability). Null with a note when unevaluated.

Key: `stage`, `metric`.

| column | type | null | values |
|---|---|---|---|
| `stage` | str |  | 14 values, see below |
| `metric` | str |  | `precision_strict`, `precision_inclusive`, `split_precision` |
| `unit` | str |  |  |
| `population` | str | yes |  |
| `n` | int | yes |  |
| `numerator` | int | yes |  |
| `denominator` | int | yes |  |
| `precision` | float | yes |  |
| `ci_lower` | float | yes |  |
| `ci_upper` | float | yes |  |
| `confidence_level` | float | yes |  |
| `interval_method` | str | yes |  |
| `estimator` | str | yes |  |
| `strata_ref` | str | yes |  |
| `eval_artifact` | str | yes |  |
| `eval_version` | str | yes |  |
| `adjudication_status` | str |  | `none`, `synthetic`, `human_llm_provisional`, `blind_human` |
| `provisional` | bool |  |  |
| `note` | str | yes |  |

## Vocabularies

**Stages** (the link-creating ones carry a path step; the others are group-level policy): `identity.splink_base`, `identity.splink_feedback`, `identity.curated`, `identity.registered_llc`, `deed.held_since`, `deed.linked_successor`, `deed.group`, `network.identity`, `network.name`, `network.address`, `owner_portfolio.group_size`, `owner_portfolio.footprint`.

**Method scopes** (for split precision): `method.aggregator_splits`, `method.hard_negatives`. **Metrics:** `precision_strict`, `precision_inclusive`, `split_precision`. **Gold status:** `none`, `synthetic`, `human_llm_provisional`, `blind_human`.

**Rules:** `splink_model`, `first_name_veto`, `common_name_veto`, `shared_company_feedback`, `shared_company_guard`, `curated_owner_list`, `registered_llc_owner_match`, `deed_latest_rule`, `deed_successor_guard`, `deed_hub_cap`, `deed_size_range`, `institutional_screen`, `coop_condo_contact_rule`, `coop_condo_deed_rule`, `aggregator_address_mask`, `splink_address_evidence_mask`, `group_min_size`, `group_footprint_rule`, `name_edge`, `address_edge`.

**Reasons a lot is absent.** The primary reason is the earliest of these levels that applies:

1. `outside_source_coverage`
2. `outside_method_input`
3. `excluded_by_policy`
4. `below_eligibility_rule`
5. `no_qualifying_linkage`

| code | level | meaning |
|---|---|---|
| `no_registration` | `outside_source_coverage` | No HPD registration for the lot. |
| `no_owner_contact` | `outside_method_input` | Registered, but no qualifying person owner contact (no wow_landlords row). |
| `not_latest_registration` | `outside_method_input` | The contact is on a registration the method did not use. |
| `unmatched_node` | `outside_method_input` | Node matched no resolved identity. |
| `coop_condo_excluded` | `excluded_by_policy` | Building is a co-op or condo, left out of a surviving group's rental footprint. |
| `coop_condo_dominated` | `excluded_by_policy` | Dropped: co-op/condo lots are the majority (of a group's footprint, or of a deed's parcels). |
| `institutional_screen` | `excluded_by_policy` | Deed parties screened as institutional or public. |
| `deed_hub_capped` | `excluded_by_policy` | Node on more multi-parcel deeds than the hub cap. |
| `aggregator_address_masked` | `excluded_by_policy` | Address-edge mask: address shared by more landlords than the threshold. |
| `address_evidence_masked` | `excluded_by_policy` | Splink address-evidence mask: address shared by more landlords than the threshold. |
| `curated_exclusion` | `excluded_by_policy` | Curated exclusion (for example a servicer officer). |
| `deed_parcels_out_of_range` | `below_eligibility_rule` | Deed outside the 2-25 parcel range. |
| `deed_not_latest` | `below_eligibility_rule` | Staleness guard: the joint deed is no longer the parcel's latest deed. |
| `successor_not_shell` | `below_eligibility_rule` | Linked-successor guard: the successor holds more buildings than the shell cap. |
| `successor_transfer_not_nominal` | `below_eligibility_rule` | Linked-successor guard: the onward transfer is not at nominal consideration. |
| `first_name_veto` | `below_eligibility_rule` | Pair blocked by the first-name veto. |
| `common_name_veto` | `below_eligibility_rule` | Pair blocked by the common-name veto. |
| `shared_company_name_not_rare` | `below_eligibility_rule` | Shared-company pass: the name is not rare enough. |
| `shared_company_first_name_conflict` | `below_eligibility_rule` | Shared-company pass: first names are not compatible. |
| `shared_company_degree_cap` | `below_eligibility_rule` | Shared-company pass: too many contacts under the company. |
| `shared_company_degree_unknown` | `below_eligibility_rule` | Shared-company pass: the company has no degree record, so the pass leaves it out. |
| `group_below_min_size` | `below_eligibility_rule` | Component smaller than the minimum group size. |
| `no_linkage` | `no_qualifying_linkage` | No accepted edge connected the node to another. |
| `pair_below_threshold` | `no_qualifying_linkage` | A scored pair fell below the threshold (recorded only if a release opts in). |

## Limits

Not promised: that a rerun gives identical groups (resolution is stochastic; a fixed run serializes
deterministically and is checksummed), recall, identity of groups across releases, and that any grouping is
true. A release is valid only with the source snapshot named in the manifest; a refreshed snapshot needs a newly
frozen release.
