# Release checklist: the citeable artifact

How to cut a versioned, DOI'd release. Steps marked **(you)** need account access or a decision that belongs to the maintainer. Nothing here pushes or tags for you.

There are two products. The **contract release** is the handoff to the knowledge graph and the thing to cite: a directory of CSVs and a manifest, frozen and checksummed, with the evidence behind every grouping ([release-contract.md](release-contract.md), [kg-mapping.md](kg-mapping.md)). The **legacy dataset** (`bor.export`) is the four-file membership list the first release was going to be. The graph treats it as superseded; it stays for people who want only memberships (see Open decisions).

## 0. Policy: no names (blocking)

A release is **person-free**. The contract release has no name column anywhere, by construction (the validator and `DATA.md` both say so). The legacy export is person-free by default; `bor.export --include-names` writes person anchors and is never part of a release. The person name is the sensitive join and the doxxing vector; the public good (grouping public parcels, labeled as inferred) is fully delivered without it. A directory produced with `--include-names` carries a `DATA.md` that says "person-linked" and must not be attached to anything.

## 1. Preconditions

- **nlr is released and pinned.** The release is built with `nyc-landlord-resolution` v0.2.0 (it returns the captured decisions the evidence tables come from), pinned in `pyproject.toml` and `uv.lock`. A clean install (`uv sync`) is enough; `NLR=<path>` points a build or the tests at a local nlr checkout instead, for trying an unreleased one.
- **The work is merged and the trees are clean.** The manifest records each package's revision, a dirty flag and a hash of the code itself. A tagged release is built with `REQUIRE_CLEAN=1`, which refuses an unclean tree.
- **Versions.** `splink==4.0.16` stays pinned (the version behind the published partition). Drop `.dev0` from `pyproject.toml` and `CITATION.cff` at tag time.
- **The test suite passes against the reference Postgres** (`PGDATABASE=justfixwow make test`; about half an hour). `make test-offline` runs the subset that needs no database (about ten seconds). A plain `make test` runs the database tests too whenever `PGDATABASE` is set, including by bor's `.env`.
- **The evaluation is scored with counts.** `uv run python -m bor.eval.score --key eval_out/blinding_key.jsonl --annotations eval_out/annotations.jsonl --out eval_out` records the counts behind each proportion and the gold's annotators (the figures themselves do not change). A `metrics.json` from an older scorer is refused with this instruction.

## 2. Build and validate

```bash
make build-release SNAPSHOT_ID=<source>-<YYYY-MM-DD> AS_OF=<YYYY-MM-DD> REQUIRE_CLEAN=1 EVAL_DIR=eval_out GOLD_STATUS=<status> [NLR=<path>]
make validate-release
```

**The snapshot id** is `<source>-<YYYY-MM-DD>`, the source dump plus the latest record date in its data, and it is repeated exactly in the manifest. For the reference dump that is `justfixwow-2026-05-29`: its newest ACRIS filing and newest HPD registration are both 2026-05-29. Take the date from the data (`select max(recordedfiled) from real_property_master`, `max(lastregistrationdate)` from `hpd_registrations`), **not** from the day you build: the id appears on every fact the graph loads, and an answer that says "as of the snapshot" must not claim more recent data than the dump holds. Set `AS_OF` to the same date so the manifest's `effective_date` equals the snapshot date (checked on the reference dump: no deed falls between 2026-05-29 and the build date, so the choice does not change a result). If PLUTO's own vintage differs, pass `--pluto-snapshot-id`. The form is a proposal until the KG confirms it. `GOLD_STATUS` says who produced the gold behind the metrics (`human_llm_provisional` today; `blind_human` only after a second blind human and human arbitration). The release lands in `release/contract` (git-ignored): 27 files (25 tables, `DATA.md`, `manifest.json`), 200 MB, 21 MB zipped. `bbl_status.csv` is 137 MB of it, because it covers every PLUTO lot in both layers and about four fifths of those rows are lots with no HPD registration. `DATA.md` is generated from the contract and the manifest, so it matches the files.

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

## 5. Tag and release **(you)**

```bash
git tag -a vX.Y.Z -m "Beneficial Ownership Resolution vX.Y.Z"
git push origin vX.Y.Z
```

Create a GitHub Release from the tag and attach the zipped `release/contract` with its sha256. In `CHANGELOG.md` rename "Unreleased" to the version and date.

## 6. Mint a DOI on Zenodo **(you)**

Enable the GitHub–Zenodo integration (or upload the archive directly). Zenodo issues a DOI on the release.

## 7. Fill the DOI back in

Edit `CITATION.cff`: set `doi:`, bump `version:` to the tag, add your ORCID. Commit.

## Decisions

Settled by the maintainer, 2026-10-22:

- **Legacy dataset.** `bor.export` stays as a documented convenience: four membership files, person-free by default, one Splink fit shared by both layers. It is not the handoff, its group ids are per-build and it carries no evidence; the contract release is what to cite and what the graph loads.
- **The gold.** The release ships with the provisional gold, labeled `human_llm_provisional` in every metric row and in `DATA.md`: one human annotator, an LLM second reader and an LLM-run resolution of their disagreements. A release rebuilt after the blind human re-adjudication carries `blind_human`. Public wording about the evaluation ("blind human adjudication", "inter-annotator") does not go out ahead of that.
- **`bbl_status` keeps every PLUTO lot in both layers.** It is 1.7 million rows and 137 MB, but 6.6 MB gzipped, and 79% of the rows are `no_registration`. Dropping them would save 112 MB raw and 5 MB compressed and break the promise that a missing row means nothing. A loader that does not want them can skip them and answer "no HPD registration" from its own HPD data ([kg-mapping.md](kg-mapping.md)).

Still the KG's: confirming the snapshot id form above, and acceptance of design note 0007 (the fifth absence reason).

## Still open before a "1.0"

- The full stratified adjudication protocol (INDETERMINATE class, circularity and data-vintage controls) and the packaged case studies.
- v2: DuckDB-native over the public HPD/ACRIS/PLUTO CSVs, so reviewers reproduce without a private database.
