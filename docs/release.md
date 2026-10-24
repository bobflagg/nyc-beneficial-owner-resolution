# Release checklist: the citeable artifact

How to cut a versioned release. Steps marked **(you)** need account access or a decision that belongs to the maintainer. Nothing here pushes or tags for you.

There are two products. The **contract release** is the handoff to the knowledge graph and the thing to cite: a directory of CSVs and a manifest, frozen and checksummed, with the evidence behind every grouping ([release-contract.md](release-contract.md), [kg-mapping.md](kg-mapping.md)). The **legacy dataset** (`bor.export`) is the four-file membership list the first release was going to be. The graph treats it as superseded; it stays for people who want only memberships (see Open decisions).

## 0. Policy: names, for reading (blocking)

**Decided 2026-10-24: a release from contract 0.2.0 on carries names.** v0.1.0 was person-free; it stays published as it is. The evidence behind a grouping could not be followed without the names of the people and companies it concerns (JustFix's own results carry them), so six tables say what the ids stand for, as HPD, ACRIS and PLUTO filed them: `observation_contacts` (role, name and business address of each HPD contact), `identity_names`, `node_names`, `deed_documents` and `deed_parties` (the grantors and grantees), and `lot_addresses`. They are copied without cleaning. They are **for reading, never for joining**: every key is still an HPD id, a BBL, an ACRIS document id or a run-local opaque id, and a shared name is not evidence that two records are one person (the decisions are).

What this takes on, and what keeps it honest:

- The names are public records, but a release groups individuals' names with the buildings they are said to control, and many small owners registered their own address. Every grouping is a lead, not a finding about a named person; `DATA.md`, the release notes and the explain output say so, and the CC BY 4.0 licence says only that the data may be reused with credit. Nothing here makes the groupings suitable for publishing about a named person without checking the source records.
- A release without the name tables (an older one, or an excerpt that omits them) is still valid, and says so in its `DATA.md`.
- The packaging guard is unchanged: only the contract's tables, `DATA.md` and `manifest.json` are zipped, so an old export with person anchors in `release/` still cannot be attached. `bor.export --include-names` (the legacy person-linked export) remains separate and is never part of a release.

## 1. Preconditions

- **nlr is released and pinned.** The release is built with `nyc-landlord-resolution` v0.2.0 (it returns the captured decisions the evidence tables come from), pinned in `pyproject.toml` and `uv.lock`. A clean install (`uv sync`) is enough; `NLR=<path>` points a build or the tests at a local nlr checkout instead, for trying an unreleased one.
- **The work is merged and the trees are clean.** The manifest records each package's revision, a dirty flag and a hash of the code itself. A tagged release is built with `REQUIRE_CLEAN=1`, which refuses an unclean tree.
- **Versions.** `splink==4.0.16` stays pinned (the version behind the published partition). The version is `0.1.0` (`pyproject.toml`, `bor.__version__`, `CITATION.cff`): **bump it before the final build**, because it is written into the data (every decision and evidence row carries `rule_version: bor-<version>`, and the manifest records it). The packaging step refuses a `.dev` version.
- **The test suite passes against the reference Postgres** (`PGDATABASE=justfixwow make test`; about half an hour). `make test-offline` runs the subset that needs no database (about ten seconds). A plain `make test` runs the database tests too whenever `PGDATABASE` is set, including by bor's `.env`.
- **The evaluation is scored with counts.** `uv run python -m bor.eval.score --key eval_out/blinding_key.jsonl --annotations eval_out/annotations.jsonl --out eval_out` records the counts behind each proportion and the gold's annotators (the figures themselves do not change). A `metrics.json` from an older scorer is refused with this instruction.

## 2. Build and validate

```bash
make build-release SNAPSHOT_ID=<source>-<data date> AS_OF=<data date> REQUIRE_CLEAN=1 EVAL_DIR=eval_out GOLD_STATUS=<status> [NLR=<path>]
make validate-release
```

**The snapshot id** is settled by the KG's design note 0008. It identifies one source dump, `<source>-<YYYY-MM-DD>`, with a revision suffix `-rN` only when the same date is extracted again with different content (the fingerprints, not the suffix, establish identity). Lowercase letters, digits and hyphens, at most 40 characters. For the reference dump it is `justfixwow-2026-05-29`. The date is the data's, never the build day: it is the **earlier** of the newest `real_property_master.recordedfiled` and the newest `hpd_registrations.lastregistrationdate`, so the id means "complete through" that date and an answer never claims more recent data than the dump holds. Both newest dates are recorded in the manifest (`snapshot_date_basis`, with a count of rows dated after the build, which are ignored), and the date is also a separate field, `snapshot_date`. **The build computes the date and refuses an id that disagrees** (before it does any work), so a wrong date cannot ship. PLUTO is part of the dump and has no id of its own. Set `AS_OF` to the same date so `effective_date` equals the snapshot date (checked on the reference dump: no deed falls between 2026-05-29 and the build date, so the choice does not change a result). Other tables in the dump are newer than the id's date (the KG measured violations through 2026-07-02); the KG's snapshot catalog keeps a per-table date and answers cite it. `GOLD_STATUS` says who produced the gold behind the metrics (`human_llm_provisional` today; `blind_human` only after a second blind human and human arbitration). The release lands in `release/contract` (git-ignored): 27 files (25 tables, `DATA.md`, `manifest.json`), 200 MB, 21 MB zipped. `bbl_status.csv` is 137 MB of it, because it covers every PLUTO lot in both layers and about four fifths of those rows are lots with no HPD registration. `DATA.md` is generated from the contract and the manifest, so it matches the files.

The build validates itself; a nonzero error count is a failed build. `python -m bor.explain release/contract lot <bbl>` (or `make explain ARGS="lot <bbl>"`) answers from the release alone and is the quickest read on whether it makes sense.

## 3. Regenerate the fixtures from the release

Two dry runs on 2026-10-22, from clean commits, each about ten minutes with 0 validation errors. The first (nlr from a local checkout, a placeholder snapshot id) matched the earlier reference build exactly. The second (bor `52b168e`, nlr v0.2.0 from the pinned install, `justfixwow-2026-05-29`, `AS_OF=2026-05-29`, run `2026-05-29-7edb54cf`) matched the first: 20 of 25 tables identical apart from the run id, and the other five identical in content (`groups`, `group_members` and `group_witness` differ only in row order; `decision_events` and `decision_support` in the float noise of the scores, at most 3e-16, and one symmetric shared-company event recorded as A to B in one build and B to A in the other). Two builds on different days from fresh Splink fits give the same groups, paths, decisions and absences. `REQUIRE_CLEAN=1` accepts the pinned nlr.

The checked-in fixtures are what a consumer tests against, so they come from the release being cut:

```bash
make excerpt SEEDS="OP-67966" OUT=release/contract EXCERPT_OUT=tests/fixtures/citadel_excerpt NOTE="<what the parent was>"
make fixtures
```

then run the tests and commit. The Citadel excerpt's manifest says whether its parent was built from a clean tree; a release candidate's must say it was.

## 4. Verify the numbers

```bash
uv run python -m bor.eval.divergence     # expect ~760 crossing / 616 hiding
```

Cross-check against [parity.md](parity.md). Report figures as stable to about 99.9%, not exact integers (Splink's u-sampling jitters). Check the loader's side too: compare `manifest.source_tables` with the same fingerprint query on the graph's own load ([kg-mapping.md](kg-mapping.md)).

## 5. Package the release

```bash
make package-release
```

This writes `dist/bor-v0.1.0-justfixwow-2026-05-29.zip`, its `.sha256` and a `-NOTES.md` for the GitHub release. It **refuses** anything that should not be published: a release that does not validate, a synthetic release or an excerpt, one built from unclean trees or a `.dev` version, and any file in the directory that is not a contract table, `DATA.md` or `manifest.json` (it names the file). That last check is the guard that matters, because the `release/` directory of a checkout can hold an older export that includes owner names. Package `release/contract`, never `release/`. The zip is reproducible: the same release always gives the same checksum.

## 6. Tag and publish **(you)**

```bash
git tag -a v0.1.0 -m "Beneficial Ownership Resolution v0.1.0"
git push origin v0.1.0
```

Then create a GitHub release from the tag, paste the `-NOTES.md` as its description, and attach the zip and its `.sha256`. Tag the commit that holds the regenerated fixtures: the manifest names the commit the release was built from, which is one commit earlier and differs only in test fixtures (the manifest's `source_tree_hash` covers the code and is the same for both). Do not move a tag once it is pushed; if something is wrong, release `v0.1.1`. In `CHANGELOG.md`, replace "unreleased" in the heading with the date, in the commit you tag.

## No DOI yet

A DOI is a later step, taken when the project has earned it. GitHub's "Cite this repository" button works from `CITATION.cff` without one. When you want one, enable the repository in Zenodo and create the next release. Zenodo archives only releases created after it is enabled, so `v0.1.0` would have to be uploaded by hand. Whether Zenodo includes a release asset (the data zip) in its archive is not stated in the pages checked on 2026-10-22; confirm before relying on it. A published DOI is permanent, so mint one for a real release, not a rehearsal. A DOI cannot be inside the release: the files are checksummed before it exists.

## Decisions

Settled by the maintainer, 2026-10-22:

- **License.** The code is MIT; the data of a release is **CC BY 4.0**. It is stated in the README, in each release's `DATA.md` and in the release notes. The author's ORCID is in `CITATION.cff`.
- **Version `0.1.0`, tag `v0.1.0`, no DOI yet.** A tagged GitHub release with the data zip and its checksum attached; Zenodo later, if the project proves itself.
- **Legacy dataset.** `bor.export` stays as a documented convenience: four membership files, person-free by default (the contract release now carries names; the legacy export does not), one Splink fit shared by both layers. It is not the handoff, its group ids are per-build and it carries no evidence; the contract release is what to cite and what the graph loads.
- **The gold.** The release ships with the provisional gold, labeled `human_llm_provisional` in every metric row and in `DATA.md`: one human annotator, an LLM second reader and an LLM-run resolution of their disagreements. A release rebuilt after the blind human re-adjudication carries `blind_human`. Public wording about the evaluation ("blind human adjudication", "inter-annotator") does not go out ahead of that.
- **`bbl_status` keeps every PLUTO lot in both layers.** It is 1.7 million rows and 137 MB, but 6.6 MB gzipped, and 79% of the rows are `no_registration`. Dropping them would save 112 MB raw and 5 MB compressed and break the promise that a missing row means nothing. A loader that does not want them can skip them and answer "no HPD registration" from its own HPD data ([kg-mapping.md](kg-mapping.md)).

Settled by the KG: design note 0007 (the fifth absence reason) and design note 0008 (the snapshot id form above), both accepted.

## Still open before a "1.0"

- The full stratified adjudication protocol (INDETERMINATE class, circularity and data-vintage controls) and the packaged case studies.
- v2: DuckDB-native over the public HPD/ACRIS/PLUTO CSVs, so reviewers reproduce without a private database.
