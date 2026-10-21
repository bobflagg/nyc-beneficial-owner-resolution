# W2 design: one resolution function in nlr, with decision capture

Status: design for approval, 2026-10-21. Nothing in this document is implemented. It covers W2 of `kg-handoff-plan-v2.md`: the identity half of the release contract (`release-contract.md`), which needs the actual decisions behind each identity cluster.

## 1. Goal

For every identity cluster, be able to say which decisions made it: which pairs Splink scored and accepted, which were blocked by a gate and why, which clusters the shared-company pass joined and on what evidence, and which HPD contacts each identity aggregates. Do it without changing a single clustering result.

Non-goals: changing any threshold, gate or the registration tie-break (those move results and need their own evaluation); the deed stages (W3); the network layer (W5).

## 2. What the code does today

Three facts from reading `nlr/splink_source.py`, `nlr/resolve.py` and `bor/splink_bridge.py`:

1. **The pipeline exists twice.** `nlr.resolve.owner_index` and `bor.splink_bridge._resolve` run the same sequence (extract, keep persons, stratified train, `fit_predict_full`, `cluster_gated`, `feedback_merge`), and `_stratified_train` is copied. They differ in one step: bor first removes curated servicer officers (the F12 list), and bor needs the entity frame and the clusters, while `owner_index` returns only a `(name, bbl) -> id` dict.
2. **Every decision is discarded where it is made.**
   - `cluster_gated` keeps pairs with `match_probability >= threshold` and `gamma_first_name != 0`, then drops pairs with a common name at different addresses, then runs union-find. The scores and both vetoes leave no trace; only the root label survives.
   - `feedback_merge` joins pre-feedback clusters that share a corporation, with three guards (corp degree cap, rare name, compatible first names). It keeps neither the pairs nor the shared corporation.
   - `_mask_aggregators` blanks the address evidence of identities at high-degree addresses before the model runs; nothing records who was blanked.
3. **Contact ids are dropped early.** `EXTRACT_SQL` aggregates contacts into identities and keeps only BBLs. `corp_owners_for` returns `(bbl, corp)` without the contact, and across **all** registrations of the BBL, not just the one the identity came from.

Two corrections to things I said earlier. Splink **is** seeded (`seed=42` in `estimate_u_using_random_sampling`), but `parity.md` explains it is only approximately seed-stable under DuckDB's parallel sampling; my P0 docstring saying "not seeded" is wrong and I will fix it. And `cluster_id` is the `unique_id` of a member (union-find root), so it is also a hash of a name and address; the release already relabels it.

## 3. Measured volume (reference dump, threshold 0.999, one fit)

| Decision | Rows |
|---|---|
| Identities (persons) | 145,388 (24 more removed by the curated list) |
| Scored pairs ≥ 0.5 / ≥ threshold | 29,304 / 22,423 |
| Accepted base pairs | 19,838 |
| Blocked by the first-name veto | 1,682 |
| Blocked by the common-name veto | 903 |
| Identities with address evidence masked | 5,298 |
| Base clusters (with 2 or more members) | 131,427 (10,611) |
| Feedback pairs accepted | 1,351 |
| Feedback pairs rejected: name not rare / first names conflict / corp degree cap | 415 / 191 / 70 |

About 30,000 decision rows in all. Volume is not a reason to leave anything out, which settles open question 3 in the contract for this stage: record every gate-blocked pair. The 6,881 pairs scored between 0.5 and the threshold are also cheap, but the contract records only gate-blocked pairs by default, so I propose leaving them out.

## 4. Proposed nlr change

One new public function; existing functions keep their signatures and results.

```python
# nlr/resolve.py
@dataclass
class Resolution:
    identities: DataFrame      # the extract frame; + `sources` when with_sources
    base_clusters: DataFrame   # unique_id, cluster_id after cluster_gated
    clusters: DataFrame        # final, after feedback_merge
    excluded: DataFrame        # identities removed by exclude_names (empty if none)
    params: dict               # threshold, seed, caps, FIRST_NAME_SIM, ...
    trace: Trace | None        # decisions, only when capture=True

def resolve_entities(conn, *, threshold=DEFAULT_THRESHOLD, feedback=True, seed=42,
                     exclude_names=None, capture=False) -> Resolution: ...
```

- `owner_index` becomes a thin wrapper over `resolve_entities(capture=False)`. Its output must not change.
- `exclude_names` is a collection of upper-case `"FIRST LAST"` keys (what bor's `aoa.excluded_officer_names` already returns), removed before training and before the feedback pass, exactly as bor does now.
- Low-level additions, each optional and defaulting to current behaviour: `extract(..., with_sources=False)`, `corp_owners_for(..., with_sources=False)`, and a `trace=None` parameter on `_mask_aggregators`, `fit_predict_full`, `cluster_gated` and `feedback_merge`. With `trace=None` the code path is the same as now; with a trace dict they fill it in.

**What the trace holds** (nlr's own vocabulary; it knows nothing of the release contract):

| Frame | Columns | Written by |
|---|---|---|
| `pairs` | `unique_id_l`, `unique_id_r`, `match_probability`, `gamma_first_name`, `outcome` (accepted, rejected), `reason` (null, first_name_veto, common_name_veto), `name_rarity`, `same_address` | `cluster_gated`: every pair at or above the threshold |
| `address_masked` | `unique_id`, `addr_degree` | `_mask_aggregators` (the full-population pass) |
| `feedback` | `base_cluster_l`, `base_cluster_r`, `outcome`, `reason` (null, name_not_rare, first_name_conflict, degree_cap), `shared_corps` | `feedback_merge`: every same-name pair that shares a corporation, including those sharing only a capped corporation (an extra counterfactual pass, trace mode only) |
| `feedback_sources` | `base_cluster`, `corp`, `bbl`, `registrationid`, `registrationcontactid` | `feedback_merge`: the contact rows carrying each shared corporation |

`identities.sources` is a list of `bbl:registrationid:registrationcontactid` strings per identity, aggregated by the extraction SQL. This replaces the temporary SQL in `bor.lineage` that re-derives which registration nlr chose, and removes its tie ambiguity: the lineage becomes what nlr actually used.

**Guarantee.** For the same inputs, `capture=True` and `capture=False` return identical clusters. This is enforced by a test, not trusted.

## 5. bor side

- `splink_bridge._resolve` becomes `resolve_entities(exclude_names=aoa.excluded_officer_names(conn))` and returns the same `(full, clusters)`; bor's copied `_stratified_train` and pipeline body are deleted. `node_clusters` and everything downstream is unchanged.
- A new module (`bor/identity_events.py`) turns a `Resolution` into contract tables, using the same opaque-id maps as `bor.lineage`:

| nlr record | Contract row |
|---|---|
| accepted pair | `decision_events`: stage `identity.splink_base`, rule `splink_model`, accepted, score, threshold, final `cluster_id`; support = the two identities' contacts |
| first-name veto / common-name veto | rejected, reason and rule `first_name_veto` / `common_name_veto`, with the score (above the threshold) |
| address masked | outcome `masked`, reason `address_evidence_masked`, rule `splink_address_evidence_mask` |
| curated exclusion | outcome `excluded`, reason `curated_exclusion`, rule `curated_owner_list` |
| accepted feedback pair | stage `identity.splink_feedback`, rule `shared_company_feedback`, subject and counterpart `base_cluster`, no pair score; support = the shared company's contacts |
| rejected feedback pair | rejected, reason `shared_company_name_not_rare` / `_first_name_conflict` / `_degree_cap`, rule `shared_company_guard` |

- `identity_clusters` gains `base_cluster_id` (from `base_clusters`), closing the gap in the contract's status table.
- `identity_observations` comes from `identities.sources`, mapped to observation ids with the pair-level rule in the contract (every `k` of an ambiguous pair).

## 6. Tests

1. **nlr unit tests (new; nlr has no test suite and no pytest dev dependency).** Hand-built prediction and cluster frames for each case: accepted pair, first-name veto, common-name veto (and the same-address exception), feedback accepted, rare-name, first-name conflict and degree cap. For each: trace-on clusters equal trace-off clusters, and the trace contains the expected row. A small offline fixture for `resolve_entities` itself would need DuckDB; to be decided.
2. **Parity (bor, database).** The final partition from the new path equals a baseline saved from the current code. Whether equality can be strict depends on run-to-run stability; see section 7.
3. **Contract.** The identity-layer tables built from the real dump pass `release_validate`, and their counts match section 3 within tolerance.
4. **Acceptance scenario on real data.** Croman's offices (740 Broadway and 424 W 51st) are one final cluster only through the Centennial Properties feedback merge. The test asserts that the events show a base decision inside each office and a feedback merge between them citing Centennial's contacts, and that no event scores the two offices against each other.
5. **Unchanged suite.** The existing 46-test bor suite passes.

## 7. Parity baseline

Two separate runs of the current code on the same input (this environment, splink 4.0.16) produce **identical partitions** of the 145,388 identities into 130,445 final clusters, but **different cluster labels**, because the label is a union-find root. `parity.md` records ~0.05% drift between runs in other conditions, so the test should compare partitions and allow that documented tolerance only if exact equality ever fails.

Consequence for the release: opaque cluster ids cannot be numbered by Splink's label. They are now numbered by each cluster's smallest member identity, so the same partition always gets the same ids (`bor.lineage.opaque_id_maps`, with a test). W2's base-cluster ids use the same rule.

The baseline partition is saved in the session scratchpad (`baseline_a.pkl`, `baseline_b.pkl`); step 3 of the work order compares against it.

## 7a. Findings from the nlr half (2026-10-21)

The nlr half is implemented on branch `capture-decisions` (commit `6a9b1a1`, v0.2.0; not pushed or tagged). On the reference dump: `owner_index` and `resolve_entities` reproduce the previous partitions exactly, capture on or off gives identical clusters, and the trace matches section 3 (22,423 pairs, 5,298 masked identities, 24 curated exclusions).

One thing section 3 got wrong. The throwaway replica kept every corporation, but `feedback_merge` keeps only corporations that have a degree record at or below the cap, and the degree query only counts a corporation that appears on a row with a named person. 72,850 of 107,386 corporations (68%) have no degree record and never take part. The real feedback pass has 1,197 accepted pairs, 371 rejected as not rare, 175 for first-name conflict, and 284 left out of the pass: 70 over the cap and 214 with no degree record. The totals match the replica (2,027); only the split differs. The trace reports the last group as `degree_unknown`, and the contract gains the reason code `shared_company_degree_unknown` under `below_eligibility_rule`. nlr's behaviour is unchanged; whether the exclusion is intended is a separate question.

## 7b. Status of the bor half (2026-10-21)

Implemented on bor branch `w2-identity-evidence`, developed against the local nlr worktree (the pin in `pyproject.toml` still says v0.1.0 and moves when nlr 0.2.0 is released; until then `uv run --with-editable <nlr checkout> ...` is needed). `bor.splink_bridge.resolve` is a thin wrapper over `nlr.resolve_entities` with the F12 exclusion, and bor's copy of the pipeline is gone. `bor.identity_events` builds `decision_events`, `decision_support`, `identity_clusters` (with `base_cluster_id`) and `identity_observations` from the trace; `bor.lineage.build_mapping` takes the captured `Resolution`. On the reference dump the event counts match the trace, the whole table set validates against the contract, every identity-BBL pair is traceable to an HPD contact, and the Croman scenario of section 6 holds. Also fixed: `bor.db.pg_conn` now loads bor's own `.env`, because nlr looks for it next to its own install.

## 8. Order of work

1. Baseline saved (done in scratch; kept for step 5).
2. nlr branch: tests first for the existing behaviour of `cluster_gated` and `feedback_merge`, then the `trace` parameters, then `with_sources`, then `resolve_entities` and the `owner_index` wrapper. Prove `owner_index` unchanged.
3. bor: `_resolve` over `resolve_entities`; parity against the baseline.
4. bor: `identity_events.py`, `identity_clusters.base_cluster_id`, `identity_observations` from `sources`; contract validation and the Croman test.
5. Docs: update the contract status table and the plan; CHANGELOG entries in both repos.

## 9. Risks and open points

- **A new nlr release.** This needs `nlr` v0.2.0 and a new pin in bor. Tagging and pushing are outward-facing and stay with you.
- **nlr has uncommitted local changes** (`uv.lock`, an untracked notebook). Adding pytest as a dev dependency touches `pyproject.toml` and `uv.lock`; the work should go on its own branch and leave your changes alone.
- **Curated exclusions have no cluster.** An excluded identity is not in `clusters`, so a decision event about it cannot reference `identity_clusters`. Proposal: allow an `identity` subject with outcome `excluded` to resolve against `identity_observations` instead, and say so in the contract and validator.
- **Shared-company support can be large.** A corporation can sit on many BBLs; support rows are limited to the contacts on the two clusters' own BBLs. About 1,351 accepted pairs; size to be measured.
- **The registration tie-break stays as it is.** It differs from WoW's for 1,249 BBLs and is unspecified in nlr (W0). Fixing it moves results; it belongs in a separate, evaluated change. Capture will at least record which registration was used.
- **DuckDB path.** nlr also runs on DuckDB; `sources` and the trace must work there or be explicitly unsupported.

## 10. Decisions needed

1. Approve the nlr change and a v0.2.0 release (no tag or push without your say).
2. Approve adding pytest as an nlr dev dependency, on a branch of its own.
3. The curated-exclusion convention above.
4. Record only gate-blocked pairs, leaving out the 6,881 pairs between 0.5 and the threshold.
