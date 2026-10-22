# Release checklist: the citeable artifact

How to cut a versioned, DOI'd release. Steps marked **(you)** need account access or a decision that belongs to the maintainer. Nothing here pushes or tags for you.

There are two products. The **contract release** is the handoff to the knowledge graph and the thing to cite: a directory of CSVs and a manifest, frozen and checksummed, with the evidence behind every grouping ([release-contract.md](release-contract.md), [kg-mapping.md](kg-mapping.md)). The **legacy dataset** (`bor.export`) is the four-file membership list the first release was going to be. The graph treats it as superseded; it stays for people who want only memberships (see Open decisions).

## 0. Policy: no names (blocking)

A release is **person-free**. The contract release has no name column anywhere, by construction (the validator and `DATA.md` both say so). The legacy export is person-free by default; `bor.export --include-names` writes person anchors and is never part of a release. The person name is the sensitive join and the doxxing vector; the public good (grouping public parcels, labeled as inferred) is fully delivered without it. A directory produced with `--include-names` carries a `DATA.md` that says "person-linked" and must not be attached to anything.

## 1. Preconditions

- **nlr is released and pinned.** The release is built with `nyc-landlord-resolution` 0.2.0 (it returns the captured decisions the evidence tables come from). Until the tag exists, `pyproject.toml` still pins `v0.1.0`, which has no `Resolution`, and only a local checkout of nlr's `capture-decisions` branch works (`make … NLR=<path>`). **(you)** tag nlr, then move the pin and `uv lock`.
- **The work is merged and the trees are clean.** The manifest records each package's revision, a dirty flag and a hash of the code itself. A tagged release is built with `REQUIRE_CLEAN=1`, which refuses an unclean tree.
- **Versions.** `splink==4.0.16` stays pinned (the version behind the published partition). Drop `.dev0` from `pyproject.toml` and `CITATION.cff` at tag time.
- **The test suite passes against the reference Postgres** (`PGDATABASE=justfixwow make test NLR=…`; about half an hour). The offline subset runs without it.
- **The evaluation is scored with counts.** `uv run python -m bor.eval.score --key eval_out/blinding_key.jsonl --annotations eval_out/annotations.jsonl --out eval_out` records the counts behind each proportion and the gold's annotators (the figures themselves do not change). A `metrics.json` from an older scorer is refused with this instruction.

## 2. Build and validate

```bash
make build-release SNAPSHOT_ID=<id> REQUIRE_CLEAN=1 EVAL_DIR=eval_out GOLD_STATUS=<status> [AS_OF=YYYY-MM-DD] [NLR=<path>]
make validate-release
```

`SNAPSHOT_ID` takes the form the KG defines and is repeated exactly in the manifest. `GOLD_STATUS` says who produced the gold behind the metrics (`human_llm_provisional` today; `blind_human` only after a second blind human and human arbitration). The release lands in `release/contract` (git-ignored): 27 files (25 tables, `DATA.md`, `manifest.json`), 200 MB, 21 MB zipped. `bbl_status.csv` is 137 MB of it, because it covers every PLUTO lot in both layers and about four fifths of those rows are lots with no HPD registration. `DATA.md` is generated from the contract and the manifest, so it matches the files.

The build validates itself; a nonzero error count is a failed build. `python -m bor.explain release/contract lot <bbl>` (or `make explain ARGS="lot <bbl>"`) answers from the release alone and is the quickest read on whether it makes sense.

## 3. Regenerate the fixtures from the release

A dry run on 2026-10-22 (bor `cee24f3`, nlr `6a9b1a1`, both clean; placeholder snapshot id) built in about ten minutes with 0 validation errors and matched the earlier reference build exactly: the same row counts in every table checked, and the same group for every node in both layers (15,623 Owner Portfolio nodes, 30,924 Operational Network nodes) from a fresh Splink fit.

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

## Open decisions

- **Legacy dataset.** Keep `bor.export` as a documented convenience, or retire it in favor of the contract release. Its four files carry only memberships and its group ids are per-build.
- **The gold.** Ship with the provisional gold labeled as such, or wait for the blind human re-adjudication. Either way the labels in `method_metrics` say which. Public wording about the evaluation ("blind human adjudication", "inter-annotator") should not go out ahead of it.
- **`bbl_status` size.** Keep every PLUTO lot in both layers (a missing row would otherwise be ambiguous), or publish only lots with a node or a reason other than `no_registration`. The contract promises that a missing row means nothing, so shrinking it is a contract change.
- **`snapshot_id` form** (the KG's) and **KG acceptance of design note 0007** (the fifth absence reason).

## Still open before a "1.0"

- The full stratified adjudication protocol (INDETERMINATE class, circularity and data-vintage controls) and the packaged case studies.
- v2: DuckDB-native over the public HPD/ACRIS/PLUTO CSVs, so reviewers reproduce without a private database.
