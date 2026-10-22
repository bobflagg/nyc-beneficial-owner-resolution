# Plan v2.1: bor release as the handoff to the landlord KG

Status: draft for final review, 2026-10-20. Supersedes the W0–W10 table in the original review request. v2 was revised after the first colleague review; v2.1 after the second; the release contract was then drafted and amended after the KG developer's review. (The review request and the reviews are working papers and are not kept in this repository.) The author has now read KG design notes 0002–0007. **Where this plan and `release-contract.md` disagree on table names, columns or vocabularies, the contract wins.**

This plan authorizes nothing by itself. P0 is implemented (branch `p0-shared-identity-context`). The W0 measurements are done (`w0-findings.md`) and the mapping tables are built in `bor.lineage` (branch `w0-mapping-tables`), not yet wired into `export()`. The minimal W8 contract is drafted in [release-contract.md](release-contract.md) (schemas in `bor.release_schema`, validator in `bor.release_validate`, synthetic fixture in `tests/fixtures/mini_release/`). The W5 spike has not been run.

## 1. Problem

The KG (`nyc-landlord-research-kg`) must show why two buildings are grouped, say which stage linked them, and say why a building is absent. It is forbidden from rebuilding entity resolution. bor's release today is four CSVs of memberships and counts: no evidence, no path, no reasons for absence, no run identity.

Decision already made: **bor's release is the handoff.** The graph model, ontology, loader and mail-drop reconciliation stay in the KG repo.

## 2. What changed

### From v1 to v2 (first review)

| v1 | v2 | Why |
|---|---|---|
| Put a stage and probability on each projected Splink clique pair | Capture the actual decisions: scored base pairs and feedback merge events between clusters; never score an unscored pair | A projected pair may never have been scored or merged directly; v1 would invent explanations |
| W0 joined `wow_landlords` to nodes on (name, bizaddr) | Emit node lineage while building `landlords_grouped` using the full six-field grouping tuple; add a second mapping from identity to contact observation | The LWC node key is six fields; registration id alone does not identify the supporting contact |
| Export only operational-network edges inside final communities | Export the full accepted pre-split graph (or a pre-split witness forest) plus split metadata | Edges crossing communities explain "same original component, different final network" |
| One per-BBL reason code | Decision records at the grain where each rule ran, plus a summary status over a defined universe | Exclusions act on contacts, nodes, addresses, deeds, parcels and components |
| Each layer resolved separately; run identity = counts and max dates | One shared run context; immutable source and code identity in the manifest | `export()` currently refits Splink once per layer; row counts do not identify content |
| `group_key` as cross-build key | An optional, versioned fingerprint only; no cross-build identity claim | A BBL-set hash changes with membership and can collide |
| "Person-free" | "No names exported" | Registration-linked evidence stays joinable to people in public records |
| "Determinism check" | Checksum and referential validation of a fixed run; agreement across fresh fits reported separately | Stochastic resolution cannot promise exact reruns |

### From v2 to v2.1 (second review)

All four findings and the sequencing, dirty-tree and decision recommendations are accepted. Where I added to or narrowed a recommendation, it is marked.

| Review point | Change | Notes |
|---|---|---|
| 1. Identity → observation chain (P1) | Added `identity_observations`, `identity_clusters` (base and final, with membership) and `decision_support` to the release | **Superseded by the KG review:** identity ids in the release are run-local opaque ids (`I0000001`), not NLR's md5 `unique_id`, which hashes a person's name and address. The KG derives its own recorded-party key from the observations |
| 2. Namespace and assertion keys (P2) | Shared objects (observations, nodes, identity decisions) keyed by run plus typed local id; layer-specific objects also keyed by layer; every foreign key states its scope; `run_id` inherited from the manifest. Added an immutable `assertion_key` per membership and supporting link | **Narrowed:** note 0005 gives the KG a stable `link_id` for Type II links. bor ships `assertion_key` as the input to the loader's derivation. Whether the KG stores evidence as list properties, per-edge relationships or promoted nodes is the KG's decision (note 0005 lists richer BOR evidence as a promotion trigger) |
| 3. Metrics (P2) | `method_metrics` keeps `precision`, lower and upper bounds, confidence level, sample size, evaluation unit, estimator and stratum or weight references, adjudication status, and null-with-reason | My v2 dropped the values when rewriting the table; restored |
| 4. Full graph vs forest (P2) | The manifest declares each artifact `complete` or `representative`, and the validator checks the declaration. The choice is made after the W5 size spike | Exported weights reproduce the actual `_collapse` input as-is. Any change to weighting is a separate, evaluated algorithm change |
| W6 sequencing | W6 split: event schema in minimal W8; event emission inside W2, W3 and W5; summaries assembled afterward | Avoids discarding rejection evidence |
| KG notes 0002–0006 | Handoff documents the KG's mapping (`reliability: II`, `source_category: project_derived`, `review_status: unreviewed`) without importing the KG ontology | Confirmed against notes 0002–0004 |
| Deed rule (note 0004) | Manifest records bor's actual deed-selection rule and version | **Addition:** bor selects `doctype ILIKE '%DEED%'`, which includes `DEED COR` (an index correction note 0004 says is never a transfer) and `DEED, TS` (timeshare). I propose a non-blocking spike counting these among qualifying deeds. Changing the rule is a separate algorithm change |
| Dirty-tree flag | Frozen release records a source-tree hash that includes the nlr changes used; a tagged release requires a clean tree | |
| Masked addresses | Snapshot-scoped crosswalk: masked address id → nodes → source observations the KG already loads. No address strings or name hashes required | Works because of `node_observations`; the KG reconciles its own mail-drop list against observations |

### From v2.1 to v2.2 (KG review of the contract)

All eleven findings are accepted; `release-contract.md` and `bor.release_schema` carry the detail.

| Finding | Change |
|---|---|
| 1. Missing reasons and rules | Codes added for the vetoes, the shared-company guards, the three deed-gate clauses, the two address masks and a below-threshold pair; `rule` is now a controlled vocabulary. Rejected candidates recorded by default: gate-blocked pairs only (the review's answer 3), so the fixture's rejected pair is a veto, not a low score |
| 2. No building-level co-op reason | `coop_condo_excluded` added; `bbl_status` gains `excluded_from_footprint`; the two co-op rules (contact description, building class) are named separately |
| 3. Policy events had no stage | `owner_portfolio.group_size` and `owner_portfolio.footprint` added |
| 4. Primary reason undefined | Precedence stated (coverage, method input, policy, eligibility, no linkage); the validator checks it |
| 5. Snapshot match unverifiable | Manifest gains `pluto_snapshot_id`, per-table `source_tables` fingerprints, `deed_selection_rule` and `normalizer_versions`; `snapshot_id` takes the KG's form |
| 6. `k` not reproducible | Normative join is (registration, contact id); `observations.pair_variants` flags the 0.08% ambiguous pairs; the digest stays internal |
| 7. Coverage vs method input | Fifth top-level reason `outside_method_input` (KG note 0007, proposed) |
| 8. `building_count` counts BBLs | Renamed `lot_count`, `total_lot_count` |
| 9. Tied nodes | Contract requires a witness step through a tied node to carry the caveat |
| 10. Stale text | Fixed here; BBL-once-per-node added to the validator; base clusters marked as waiting on W2 |
| 11. `assertion_key` | KG forms `link_id` as `<assertion_key>#<bbl>` |

One addition beyond the review: Splink's *cluster* ids are also derived from the name-and-address hash, so clusters are relabelled opaquely as well as identities.

## 3. Contract principles

1. **One run, one context.** Source view, extraction, identity decisions, node mapping, accepted edges and policy outcomes are computed once and consumed by both layers.
2. **Evidence is captured where it is produced**, before aggregation or discard. It is not reconstructed afterward.
3. **Explanations are representative, not unique.** A witness path proves connectivity; other accepted evidence is kept separately. A path is never labeled strongest or shortest.
4. **Absence summarizes pipeline decisions.** It does not establish that no real relationship exists. Comparisons beyond the candidates bor evaluated (Q7, Q22) are the KG's job.
5. **Recorded versus derived stays separable.** Exact owner-name agreement and similar rules are derived matching rules, not verified legal identity.
6. **Metrics are provisional and precision-only** until blind human re-adjudication. They describe a method, not an individual link, and must not be shown as a link probability. Every consumer-facing statement carries that.
7. **No names exported.** Opaque observation references, registration ids, BBLs and ACRIS document ids only.
8. **Declared capabilities.** The manifest states which artifacts are complete and which are representative. Storage choices never silently change what a release means.
9. **bor does not import the KG's model.** It documents how its fields map to the KG's reliability, source category and review status, and nothing more.

## 4. Release contents (proposed)

**Keys.** Shared objects (observations, nodes, identity decisions) are keyed by run plus a typed local id. Layer-specific objects (groups, membership, witness, decisions, network membership) are additionally keyed by layer. `run_id` comes from the manifest of a self-contained release; every foreign key states its scope. Each membership and supporting link carries an immutable `assertion_key`, stable for the same frozen assertion and not a claim of enduring owner identity. Node ids are build-local.

| Table | Purpose |
|---|---|
| `manifest.json` | Run id, effective as-of date (replaces `CURRENT_DATE`), immutable snapshot or source hashes, bor and nlr revisions, source-tree hash (including nlr changes used), dependency lock digest, model and settings artifacts, seeds where applicable, normalizer and rule versions (including the deed-selection rule), every constant, output checksums, schema version, and a complete/representative declaration per artifact |
| `observations` | Opaque observation key, registration id, BBL, contact selector, role |
| `node_observations` | LWC node → observations, from the full grouping tuple; unmatched and ambiguous rows reported |
| `identity_observations` | Identity (opaque id) → the contact observations it aggregates |
| `identity_clusters` | Base and final cluster membership by identity id, with the cluster each feedback merge joined |
| `identity_decisions` | One row per real decision, endpoints are identity ids or preserved base clusters: scored base pair (score, gate outcomes), feedback merge event (supporting shared-company registrations), curated owner, registered-LLC match (PLUTO BBL and snapshot as source) |
| `decision_support` | Decision → the exact observations or source records that support it |
| `identity_node_map` | Identity cluster → node: selected assignment, alternatives and tie rule (distinguished), so a node attached to several identities does not imply every observation supports every edge |
| `evidence_items` / `evidence_members` | Multi-member assertions: deed bundles (per parcel role: still held vs transferred onward, original and latest document ids, gate values), plus references to identity decisions |
| `groups`, `group_members` | Owner Portfolios with `assertion_key`; a node is in at most one group per layer, and W0 measured that each BBL is in exactly one node, so each BBL is in at most one group per layer; the validator checks it |
| `group_witness` | Per group: step, actual endpoint pair, evidence or decision reference, deterministic selection order |
| `network_edges` | Accepted pre-split graph with name, address and identity weight contributions, reproducing the actual `_collapse` input. Complete or representative per the manifest declaration |
| `network_membership`, `split_attempts` | Node → original component → final community; recursive split and unsuccessful attempts |
| `decisions` | Layer, stage, subject type and key, rule and version, outcome, reason, evidence reference. Multiple reasons allowed; primary-reason precedence defined |
| `bbl_status` | Summary per layer over the PLUTO-snapshot lot universe; distinguishes no registration, no usable owner contact, unmatched node, no accepted linkage, dropped component. A missing row never means "outside coverage" |
| `masked_addresses` | Method-specific address id, normalizer version, degree unit, threshold, decision, and a crosswalk to nodes and their source observations |
| `method_metrics` | Stage, evaluation unit, population, `precision`, lower and upper bounds, confidence level, sample size, numerator and denominator, estimator and stratum or weight references, evaluation artifact and version, adjudication status; null with explanation when unevaluated |

Stage vocabulary (versioned): `identity.splink_base`, `identity.splink_feedback`, `identity.curated`, `identity.registered_llc`, `deed.held_since`, `deed.linked_successor`, `network.name`, `network.address`.

## 5. Work packages

| # | Package | Acceptance | Size |
|---|---|---|---|
| **P0** | **Shared run context.** `export()` computes identity resolution once and both layers consume it. Standalone bug fix; interface coordinated with W0 and minimal W8, but not the whole evidence system | A test shows both layers consume the same result | S–M |
| **W0** | **Mappings and ambiguity contract.** LWC node → source observations; identity → contact observation (source contact id if present, else snapshot-scoped key plus selector); confirm `unique_id` as the identity key | Report unmatched, ambiguous and fan-out rows and BBL coverage. Tests: null addresses, several contacts per registration, same name and address with different grouping fields, one node to several identities | M. Measured: see `w0-findings.md`; build the tables next |
| **W1** | **Manifest and immutable run identity** (section 4) | Fixed run has checksums; `CURRENT_DATE` resolves to a recorded date; date ties in latest-record selection are deterministic or flagged; source-tree hash recorded | S–M. Implemented 2026-10-21 (`bor.manifest`, `bor.release`; bor branch `w1-manifest`): see `release-contract.md`. Date ties are flagged, not fixed: 23,163 BBLs share a latest deed date, 1,221 of them with tied documents that differ in whether they are multi-parcel deeds |
| **W2** | **Identity evidence capture, in nlr, once.** (a) Remove the duplicated pipeline: `bor.splink_bridge._resolve` and `_stratified_train` copy the body of `nlr.resolve.owner_index`. nlr exposes one function returning the entity frame, the clusters and, optionally, captured decisions and extraction lineage, with a hook for bor's F12 servicer-officer exclusion; `owner_index` and bor both call it. (b) Capture decisions inside it (existing API preserved: optional flag or new entry point) | Parity first: with capture off, the shared function reproduces bor's current clusters (check against `docs/parity.md`) and `owner_index` output is unchanged. Then: a consumer traces a base A–B decision and a feedback B–C bridge to exact contacts, without joining on names, guessing cluster contents or attributing unrelated contacts; includes the ambiguous-node case; no A–C score is manufactured | L. Implemented 2026-10-21 (nlr branch `capture-decisions`, bor branch `w2-identity-evidence`); nlr 0.2.0 is released and pinned (2026-10-22). See `w2-design.md` 7a and 7b |
| **W3** | **Deed evidence capture** before `deed_node_groups` unions held and transferred sets; record co-op/condo rules separately for deed and Owner Portfolio code; record the deed-selection rule and version | A mixed held/successor deed shows per-parcel outcomes | M. Implemented 2026-10-21 (`bor.deed_events`; bor branch `w3-deed-evidence`). On the reference dump: 839 evidence items (77 depend on the linked-successor guard, 22 mix held and transferred parcels), 2,454 members, about 3,200 gate events; the hub cap never triggers. Includes a deterministic latest-deed tie-break (separate commit). See `release-contract.md`, Deed evidence |
| **W4** | **Group tables, witness paths and `assertion_key`** with endpoint pairs and deterministic order | Witness is connected and acyclic; paths through footprint-excluded nodes keep those nodes and explain them; loading twice is idempotent; two runs with reused numbers do not collide; both layers can reference one identity decision without copying it | M. Implemented 2026-10-21 for the Owner Portfolio layer (`bor.group_tables`; bor branch `w4-groups-witness`; design in `w4-design.md`). On the reference dump: 6,523 groups over 15,623 nodes and 9,100 witness steps (exactly one fewer than members per group); the shared-company merge is needed by 492 groups and the successor guard by 28. The Operational Network's groups and path are W5 |
| **W5** | **Operational network evidence.** Size spike first; then choose full graph or forest and declare it | Two lots in different final communities but one original component have a path with the boundary identified; the manifest declares complete or representative and the validator checks it | M–L. Implemented 2026-10-21 (`bor.network_tables`; bor branch `w5-operational-network`). The size spike decided it: the whole weighted graph is 57,202 edges (about 3 MB), so the release carries the **complete** graph, not a forest, and Louvain's input is reproduced exactly. Louvain communities can be internally disconnected (one in a build on the reference dump), so a network's path is a forest with `witness_pieces` recorded; the complete edge table connects the pieces across the boundary. Louvain is now seeded (42, in the manifest), so the layer is reproducible |
| **W6a** | **Decision-event emission** inside W2, W3 and W5 builders, to the event schema fixed in minimal W8 | A hub-capped node that retains another valid link, and a dropped component, are represented correctly | M. Implemented 2026-10-21 for the identity, deed and network layers and the Owner Portfolio's co-op rule (`bor.group_events`; bor branch `w6-absence`). |
| **W6b** | **Summaries:** assemble `decisions` and `bbl_status` from the emitted events | Status universe is the PLUTO snapshot; reasons are consistent with events | S–M. Implemented 2026-10-21 (`bor.absence`). `bbl_status` covers every PLUTO lot in both layers (858,625 lots, 137 MB as CSV); the primary reason follows the documented precedence and the validator uses the same event-to-lot rule as the summary. |
| **W7** | **Method metrics** generated from evaluation artifacts | A consumer displays the published estimate and interval directly, with no recalculation and no reading as link probability | S. Implemented 2026-10-22 (`bor.metrics`; bor branch `w7-metrics`): a transcription of the scorer's `metrics.json`, strict and inclusive precision per stratum, split precision for the aggregator and hard-negative strata as method scopes, no pooled figure, a row (null, with a note) for every link-creating stage, Wilson and census noted in `interval_method`. Gold status is explicit (`human_llm_provisional` today); `explain` shows the published estimate beside a weak stage. The identity sample pools base and shared-company pairs, so `splink_feedback` has no estimate of its own |
| **W8** | **Schemas, validator, `explain()`.** A minimal version comes first as the contract, including the event schema (drafted: [release-contract.md](release-contract.md); `explain()` not yet) | Endpoint existence, source references, membership cardinality, witness connectivity, reason consistency, metric-stage coverage, declared capabilities | M. `explain()` implemented 2026-10-21 (`bor.explain`; bor branch `w8-explain`): lot, pair and group, from the release tables alone. |
| **W9** | **Fixtures and tests:** the Citadel case plus synthetic ones (transitive feedback bridge; mixed held/successor deed; hub-capped node with another valid link; dropped component; ambiguous contact mapping; WCC split across communities); validator invariant that each BBL is in one node and at most one group per layer (true by construction in this dump: W0) | Consumer loads the fixture without Postgres | M. Implemented 2026-10-22 (bor branch `w9-fixtures`): `tests/fixtures/synthetic_release` (every case above and each absence reason, all 25 tables), `tests/fixtures/citadel_excerpt` (real rows, cut by the new `bor.excerpt`), and `tests/test_kg_fixture.py`, the approval gate as tests. The fixtures exposed three gaps, now fixed: `explain pair` said only "No" for a hub-capped or ambiguous pair (it now gives the closest evidence), the validator never checked that assertion keys carry the manifest's `run_id`, and the manifest recorded the builder's local checkout path. Two fixtures, not one merged release: a merge would put synthetic rows under a real run id. The release candidate regenerates the Citadel excerpt from a clean build |
| **W10** | **Docs, changelog, frozen release, tag** | `docs/data.md`, `docs/release.md`, `DATA.md` updated; field mapping to the KG documented | S. Docs implemented 2026-10-22 (bor branch `w10-release`): `release.md` rewritten around the contract release, `data.md`, README, `kg-mapping.md`, and a `DATA.md` generated from the schema (`bor.release_docs`) into every release and fixture. **The frozen release and the tag are not done:** they need nlr tagged and pinned, the branches merged, a snapshot id in the KG's form and the maintainer's decisions listed in `release.md`. A release-candidate build from clean commits is the dry run |

## 6. Sequence

1. **P0, W0, minimal W8 contract (with event schema).** Agree keys, cardinalities, observation mapping and decision grains with the KG, with one worked explanation.
2. **W1.**
3. **W2, W3, W6a, and the W5 size spike** (W5 need not wait for W4).
4. **W4, W5, W6b, W7**, built from the preserved artifacts.
5. **W8–W10.**

## 7. Approval gate

One frozen fixture in which a KG consumer can: trace two grouped lots to exact source observations; name each necessary linkage stage; explain a cross-community path and an absence; display a published metric directly; and verify the shared run and snapshot. The identity-provenance, key-collision, metric-value and graph-completeness tests above are part of it. When it passes, the remaining implementation is well scoped.

A frozen release is valid only when the KG loads the matching source snapshot. A refreshed KG snapshot needs a newly frozen bor release.

## 8. Risks and unknowns

- W2 reaches into nlr: a new nlr release and a new pin. Approved in scope; v0.2.0, tagged 2026-10-22 and pinned.
- bor's copy of the nlr pipeline (`_resolve`, `_stratified_train`) has not been diffed line by line against `owner_index`; the parity check in W2 is what establishes that removing it changes nothing. The F12 exclusion is the one known difference.
- nlr extraction drops the contact id, but `hpd_contacts.registrationcontactid` exists; it is not unique (1,028 repeated pairs), so the observation id carries a rank `k` over differing contents (W0; no hash is exported). Splink runs on person contacts only, so corporate links come from the registered-LLC and deed stages.
- Pre-split graph size is unmeasured; storage format and the complete/representative declaration follow from it.
- `_collapse` sums parallel and possibly mutual entries. Exports will reproduce it as-is; whether that double-counts is an audit question for a separate change.
- W0 measured: each BBL is in exactly one node, so it is in at most one group per layer. 751 nodes (0.63%) straddle several clusters and 639 of those are tied; the tie rule is arbitrary and must be flagged in the release.
- Deed selection includes `DEED COR` and `DEED, TS`; how many qualifying deeds depend on them is unmeasured.
- KG note 0006 says nlr uses only the most recent registration per BBL; if bor inherits that, "not in the method's input" is a distinct absence reason that must appear in `decisions`. Confirmed in W0 for nlr: it takes one registration per BBL, and picks a different one than WoW for 1,249 BBLs because its tie-break is unspecified; also 10,516 BBLs have a registration but no `wow_landlords` row.
- Estimate: several weeks. W2, W5 and W6a are the uncertain ones.
- Splink run-to-run agreement is ~99.95% (`docs/parity.md`); precision figures and parity are not independently re-validated.

## 9. Decisions needed

Items 1 and 2 were approved by the author on 2026-10-20. Items 3 and 4 are proposed resolutions from the second review and still need approval.

1. **nlr changes: approved, in scope.** Decision and extraction-lineage capture are optional so the existing API is preserved. Release version chosen after a compatibility assessment; no nlr change has been made yet.
2. **P0 first: approved and implemented** (uncommitted): `bor.run_context.resolve_identity` computes the identity edges once; `resolve_owner_portfolios` and `resolve_operational_networks` accept `identity=`; `export()` shares one. Unit tests in `tests/test_run_context.py`. Full suite (38 tests, including the integration tests against `justfixwow`) passes in about 7 minutes.
3. **KG note 0007:** draft the boundary and unresolved questions now (note 0006's Correction already names the open question: run-scoped nodes mapped to identity nodes, or edges expanded onto identity nodes). Finalize mappings and issues after W0 results. Writing it touches the KG repo, which has uncommitted work on its current branch, so the location needs your decision.
4. **Masked addresses:** snapshot-scoped crosswalk through source observations. The only open policy question is whether any normalized address token or hash is exposed beyond the crosswalk, and under which normalizer version.
