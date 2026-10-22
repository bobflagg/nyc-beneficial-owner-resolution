# Loading a bor release into the knowledge graph

This is bor's side of the boundary agreed with the KG (the `nyc-landlord-research-kg` repository, design notes 0001, 0002, 0005 and 0007). It says which release field feeds which graph property, what a loader must check before it trusts a release, and what it must never do. It is documentation, not an import: bor does not adopt the KG's ontology and the KG does not import bor's schema (note 0007). The release itself is described in [release-contract.md](release-contract.md) and, per release, in its generated `DATA.md`.

Status of the KG notes this rests on: 0002 and 0005 are accepted; **0007 is proposed**, so the fifth absence reason and the node-versus-edge choice below are the KG's to confirm.

## Field mapping

| bor release | knowledge graph | notes |
|---|---|---|
| `manifest.snapshot_id` | `snapshot_id` property on every loaded assertion | The release is valid only with the matching source snapshot. Proposed form: `<source>-<YYYY-MM-DD>`, the latest record date in the data, for example `justfixwow-2026-05-29` ([release.md](release.md)); the KG confirms it. |
| `manifest.run_id` | the BOR run, recorded on each Type II link and in the snapshot/run catalog | Every `assertion_key` starts with it. |
| `group_bbls` row (`layer`, `bbl`, `group_id`) | a membership of one building in an Owner Portfolio or Operational Network | `link_id = <assertion_key>#<bbl>`, the key a later review points at. A bor node can hold several BBLs, so the graph models a membership per building. |
| `groups.lot_count`, `total_lot_count`, `composition`, `split` | properties of the group | Counting unit is the tax lot. `rental = false` lots are co-op/condo lots outside the published footprint. |
| (constants set by the loader) | `reliability: II`, `source_category: project_derived`, `review_status: unreviewed` | Notes 0002 to 0004 and 0007. bor never marks anything reviewed. |
| `group_witness` rows | the evidence for a link: one record per step | Each step: `stage`, the two nodes it joins, the evidence it cites (`basis_type`, `basis_id`), and its own `assertion_key`. Held as list properties on the link or as one relationship per step (note 0005, open until the graph needs more). The path is *representative*, not the only or strongest one. |
| `decision_support` / `observations` | the HPD contacts behind a decision | An observation is `registration:contact:k`. Join to the graph's role nodes on `registration_id` and `registrationcontactid`, never on a name. Where `observations.pair_variants > 1` the pair repeats with differing content: attach to every row of the pair and mark it ambiguous. |
| `node_observations`, `node_identity_matches`, `node_cluster` | how a bor node maps to recorded parties | bor nodes are `landlords_with_connections` rows. Whether to load them as run-scoped nodes or expand edges onto identities is open (note 0007, item 5). `ambiguous` and `tied` rows are shown, not hidden. |
| `evidence_items`, `evidence_members` | ACRIS deed evidence | `original_document_id` and `latest_document_id` are ACRIS document ids; a member either still sits under the joint deed or was transferred onward. |
| `decision_events` | why a link was made or refused | One row per decision, with the rule and its version, outcome, reason code, score and threshold where there is one. Absence of an event means the rule did not run. |
| `bbl_status` | the answer to "why is this building not in a group?" | Five top-level reasons, in precedence order: `outside_source_coverage`, `outside_method_input`, `excluded_by_policy`, `below_eligibility_rule`, `no_qualifying_linkage`. The detailed `reason_code`s are narrower terms of these (the KG's `AbsenceReason` scheme). A missing row means nothing. `no_registration` is about 79% of the rows (a lot HPD does not register): a loader may skip them and answer "no HPD registration" from its own HPD data, which is the source record itself. |
| `method_metrics` | the published precision shown beside a link | Show `precision` with its interval and `adjudication_status` exactly as stored. Do not recompute it and do not call it a probability. |

The questions this serves are the KG's Q9 and Q10 (footprint and comparison of the two layers), Q19 (why are these grouped?) and Q26 (absence).

## What a loader checks before it trusts a release

1. `manifest.schema_version` is one it supports, and `bor.release_validate` passes on the directory (it checks keys, foreign keys, the invariants in the contract and the checksums).
2. Every file matches `manifest.output_checksums`.
3. The release was built from the source snapshot the graph holds: compare `manifest.source_tables[t]` (`row_count`, `fingerprint`) with the same query on the graph's own load (`bor.manifest.fingerprint_sql`). `landlords_with_connections` is bor-built and only matches the same build, so compare the tables the graph actually mirrors.
4. Every `assertion_key` starts with `manifest.run_id` (the validator checks this).
5. `manifest.synthetic` is absent. A synthetic release is for tests and is refused in a production load.
6. `manifest.excerpt` is absent, or the load is deliberately partial: an excerpt leaves rows out and says so.
7. `manifest.code.*.dirty` is not true. A tagged release is built from clean trees; a dirty one identifies its code only by the tree hash.

## What a loader must never do

- **Join on names.** There are none in a release. Join observations on (`registration_id`, `registration_contact_id`) and lots on BBL.
- **Treat ids as stable across releases.** Group, identity, cluster and decision ids are run-local. Membership is the durable content, and a review does not carry across runs (note 0007, item 2).
- **Read a group as a determination of ownership,** or a path as the only evidence. Every group is a lead.
- **Show a precision as the chance a link is right.** It is the share of sampled pairs judged correct in one stratum, on one snapshot. `provisional` rows stay labeled so until the gold is blind human adjudication.
- **Read an absence as evidence the owners differ.** An absence is a rule the method applied or a record it did not use.
- **Re-run bor on each graph build.** Resolution is stochastic (about 99.95% agreement between fits); the release is frozen and a new snapshot needs a newly frozen release.

## Open on the KG side

Acceptance of note 0007 (the fifth reason, `outside_method_input`, and the building-level `coop_condo_excluded` code); run-scoped nodes versus edge expansion (item 5); the `AbsenceReason` vocabulary; the form of `snapshot_id`; and whether reviews should survive across runs once a review process exists.
