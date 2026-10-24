# Loading a bor release into the knowledge graph

This is bor's side of the boundary agreed with the KG (the `nyc-landlord-research-kg` repository, design notes 0001, 0002, 0005, 0007, 0008 and 0009). It says which release field feeds which graph property, what a loader must check before it trusts a release, and what it must never do. It is documentation, not an import: bor does not adopt the KG's ontology and the KG does not import bor's schema (note 0007). The release itself is described in [release-contract.md](release-contract.md) and, per release, in its generated `DATA.md`.

Status of the KG notes this rests on: 0002, 0005, 0007 (the fifth absence reason, `outside_method_input`), 0008 (the snapshot identifier) and 0009 (names in results) are accepted. Note 0007's item 5 is decided: bor nodes enter the graph as run-scoped nodes (below). Note 0009 (2026-10-24) is why a release from contract 0.2.0 carries names: the graph loads the release with names as is, and the person-free condition of note 0007 no longer applies (see "Names", below).

## Field mapping

| bor release | knowledge graph | notes |
|---|---|---|
| `manifest.snapshot_id`, `snapshot_date` | `snapshot_id` property on every loaded assertion; `snapshot_date` on the snapshot node | One source dump, `<source>-<YYYY-MM-DD>[-rN]` (KG design note 0008, accepted). The date is the data's: the earlier of the newest ACRIS `recordedfiled` and HPD `lastregistrationdate`, both recorded in `snapshot_date_basis`. The release is valid only with the matching snapshot. |
| `manifest.run_id` | the BOR run, recorded on each Type II link and in the snapshot/run catalog | Every `assertion_key` starts with it. |
| `group_bbls` row (`layer`, `bbl`, `group_id`) | a membership of one building in an Owner Portfolio or Operational Network | `link_id = <assertion_key>#<bbl>`, the key a later review points at. A bor node can hold several BBLs, so the graph models a membership per building. |
| `groups.lot_count`, `total_lot_count`, `composition`, `split` | properties of the group | Counting unit is the tax lot. `rental = false` lots are co-op/condo lots outside the published footprint. |
| (constants set by the loader) | `reliability: II`, `source_category: project_derived`, `review_status: unreviewed` | Notes 0002 to 0004 and 0007. bor never marks anything reviewed. |
| `group_witness` rows | the evidence for a link: one record per step | Each step: `stage`, the two nodes it joins, the evidence it cites (`basis_type`, `basis_id`), and its own `assertion_key`. Held as list properties on the link or as one relationship per step (note 0005, open until the graph needs more). The path is *representative*, not the only or strongest one. |
| `decision_support` / `observations` | the HPD contacts behind a decision | An observation is `registration:contact:k`. Join to the graph's role nodes on `registration_id` and `registrationcontactid`, never on a name. Where `observations.pair_variants > 1` the pair repeats with differing content: attach to every row of the pair and mark it ambiguous. |
| `node_observations`, `node_identity_matches`, `node_cluster` | how a bor node maps to recorded parties | bor nodes are `landlords_with_connections` rows and are **loaded as run-scoped nodes** (decided, note 0007 item 5; see below). `ambiguous` and `tied` rows are shown, not hidden. |
| `evidence_items`, `evidence_members` | ACRIS deed evidence | `original_document_id` and `latest_document_id` are ACRIS document ids; a member either still sits under the joint deed or was transferred onward. |
| `decision_events` | why a link was made or refused | One row per decision, with the rule and its version, outcome, reason code, score and threshold where there is one. Absence of an event means the rule did not run. |
| `bbl_status` | the answer to "why is this building not in a group?" | Five top-level reasons, in precedence order: `outside_source_coverage`, `outside_method_input`, `excluded_by_policy`, `below_eligibility_rule`, `no_qualifying_linkage`. The detailed `reason_code`s are narrower terms of these (the KG's `AbsenceReason` scheme). A missing row means nothing. `no_registration` is about 79% of the rows (a lot HPD does not register): a loader may skip them and answer "no HPD registration" from its own HPD data, which is the source record itself. |
| `method_metrics` | the published precision shown beside a link | Show `precision` with its interval and `adjudication_status` exactly as stored. Do not recompute it and do not call it a probability. |
| `observation_contacts`, `identity_names`, `node_names`, `deed_documents`, `deed_parties`, `lot_addresses` (0.2.0) | names and addresses as properties of what they describe: `node_names.name` on the run-scoped node, the contact's name and business address on the observation, the parties on the deed, the address on the lot | Loaded as is (KG note 0009). Display text, never keys and never evidence. The graph already holds the HPD, ACRIS and PLUTO sources, so the contact, deed and lot rows repeat what it has; `node_names` and `identity_names` are what the release adds. See "Names" below. |

The questions this serves are the KG's Q9 and Q10 (footprint and comparison of the two layers), Q19 (why are these grouped?) and Q26 (absence).

## bor nodes are run-scoped nodes

Decided with the KG (note 0007, item 5): a bor node is a **run-scoped, `project_derived` node**, keyed by the run and node id (the `/n<node>` of `assertion_key`: `<run_id>/<layer>/<group_id>/n<node>`). It is a `landlords_with_connections` row, and it is the grain at which bor groups, joins and explains.

- It maps to the graph's role nodes through `node_observations`: the selected observation, or every candidate in `node_observation_alternatives` when the node is `ambiguous`. Its lots are its `node_observations` rows (a node covers one or more lots; 14,242 of the 118,493 nodes cover two or more, up to 384).
- Identity ids stay properties of the release, not nodes. The graph derives its own recorded-party key from the observations (note 0007, item 4), and `node_identity_matches` is there to cross-reference events.
- An explanation path runs building, role node, bor node, bor node, role node, building. Only the 31,035 nodes that are in a group (of the 118,493) are needed to explain a grouping.
- `ambiguous` (616 nodes, covering 642 lots) and straddling (751 nodes, 639 of them tied) stay flags on the node, with their alternatives, so a reader sees the choice bor made.

Why not expand the edges onto identities instead: most of the evidence does not join identities. Of the 21,251 Operational Network path steps, 11,771 are shared-address and 156 are name matches between landlord *records*, and deeds and owner-entity link sets join nodes through lots. 113 nodes match no identity, so their steps would vanish, and a node that straddles clusters would connect to both readings, undoing a tie bor resolved by a recorded rule. (Expanding would only multiply edges by about 1.2 to 1.3, so cost was not the deciding reason.) Counts are from the v0.1.0 release.

## Names

KG design note 0009 (accepted 2026-10-24) drops the rule that people appear only in recorded roles, so a release from contract 0.2.0 carries names, and the graph loads it as is.

- **What is in the release.** The name tables in the field mapping, copied as HPD, ACRIS and PLUTO filed them: typos and variant spellings stay, and blank is null. A contact that HPD repeats with differing content has one row per variant (the same `k` as the observation). The tables are optional in a directory, so a loader checks for them and does not assume them.
- **Where the names go.** Properties of the run-scoped nodes (`node_names`) and, if the graph wants them, of the observations, deeds and lots. Each name still comes from a fact that carries `reliability`, `source_category`, `source` and `snapshot_id`. bor's are `project_derived` and `unreviewed`, as for every other bor row.
- **A name is not an ownership claim.** A role node needs a source; a name and a group's anchor do not make one (notes 0001 and 0009).
- **Name matches.** Stored name edges come only from bor (note 0009, item 6): 156 of the 21,251 Operational Network path steps are name matches between landlord records, with the name weight on `network_edges`. The graph's own name comparisons (Q3, Q22) are made at query time by rule N1 of note 0006 and are leads. Neither is stored, and neither is joined on.
- **The group anchor.** A group's person anchor is a display attribute, never a role. **The 0.2.0 release has no anchor column.** bor computes one only in memory, for Owner Portfolios, as the member with the most lots (ties by database order, so not deterministic). A loader that wants one can show the member names from `node_names`. Whether to add `groups.anchor_node_id`, with a stated tie rule, has been put to the KG (below).
- **Care.** These are public records, but a group is a lead and the names are individuals' as well as companies'. An answer that shows one says where it came from and whether it is recorded, attributed or derived (note 0009, item 2). It does not follow links to an individual's home address or other non-business information, which note 0009 still rules out.

## What a loader checks before it trusts a release

1. `manifest.schema_version` is one it supports (`0.1.0` or `0.2.0`; a 0.1.0 release has no name tables and a 0.2.0 one has them, though an excerpt may omit them), and `bor.release_validate` passes on the directory (it checks keys, foreign keys, the invariants in the contract, that each name table covers every id it is for, and the checksums).
2. Every file matches `manifest.output_checksums`.
3. The release was built from the source snapshot the graph holds. The loader reads `snapshot_id` from the manifest and verifies it by fingerprint; it does not re-derive it (note 0008). It checks `snapshot_id` against `^[a-z][a-z0-9]*-\d{4}-\d{2}-\d{2}(-r\d+)?$`, runs the two date queries behind `snapshot_date_basis` on its own load and refuses a mismatch, and compares `manifest.source_tables[t]` (`row_count`, `fingerprint`) with the same query on the graph's own load (`bor.manifest.fingerprint_sql`), in three tiers:
   - *required, refuse on mismatch:* `hpd_contacts`, `hpd_registrations`, `pluto_latest`, `real_property_master`, `real_property_legals`, `real_property_parties`;
   - *warning only:* `wow_landlords`, `hpd_registrations_grouped_by_bbl_with_contacts` (the graph does not read them);
   - *skipped:* `landlords_with_connections`, which bor builds and which matches only its own build.
4. Every `assertion_key` starts with `manifest.run_id` (the validator checks this).
5. `manifest.synthetic` is absent. A synthetic release is for tests and is refused in a production load.
6. `manifest.excerpt` is absent, or the load is deliberately partial: an excerpt leaves rows out and says so.
7. `manifest.code.*.dirty` is not true. A tagged release is built from clean trees; a dirty one identifies its code only by the tree hash.

## What a loader must never do

- **Join on names.** A 0.2.0 release carries names (`observation_contacts`, `identity_names`, `node_names`, `deed_parties`, `lot_addresses`) for display only. Join observations on (`registration_id`, `registration_contact_id`), lots on BBL and documents on ACRIS document id; a name is never a key, and two records sharing one are not thereby one person.
- **Treat ids as stable across releases.** Group, identity, cluster and decision ids are run-local. Membership is the durable content, and a review does not carry across runs (note 0007, item 2).
- **Read a group as a determination of ownership,** or a path as the only evidence. Every group is a lead. A name, or a group's anchor name, is not an ownership claim either (note 0009).
- **Show a precision as the chance a link is right.** It is the share of sampled pairs judged correct in one stratum, on one snapshot. `provisional` rows stay labeled so until the gold is blind human adjudication.
- **Read an absence as evidence the owners differ.** An absence is a rule the method applied or a record it did not use.
- **Re-run bor on each graph build.** Resolution is stochastic (about 99.95% agreement between fits); the release is frozen and a new snapshot needs a newly frozen release.

## Asked of the KG (2026-10-24)

Whether to add, in a v0.2.1, `groups.anchor_node_id` (rule: most lots, ties to the smallest node id, both layers), and the normalised text of each masked address in `masked_addresses`, to settle the reconciliation with the KG's mail-drop list (the open item in note 0001). Nothing in v0.2.0 depends on the answer.

## Open on the KG side

The `AbsenceReason` vocabulary; and whether reviews should survive across runs once a review process exists.
