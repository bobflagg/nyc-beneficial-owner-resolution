# Release checklist — citeable artifact

How to cut a versioned, DOI'd release of this repo (the "software + data" artifact).
Steps marked **(you)** need account access I don't have (GitHub release UI, Zenodo).

## 0. Decide the release policy (blocking)

The dataset export (`bor.export`) is **person-free by default** — BBL-keyed, opaque group ids, no
owner names — matching the project's dual-use stance. Confirm this is the release scope, or decide to
opt into names (`--include-names`). Recommendation: **keep it person-free.** The person name is the
sensitive join and the mosaic/doxxing vector it raises; the public good (grouping
public parcels, typed as inferred) is fully delivered without it.

## 1. Freeze the resolution version

`pyproject.toml` pins `splink==4.0.16` (the version behind the published partition) and
`nyc-landlord-resolution @ v0.1.0`. Keep these pinned for the release so the numbers reproduce.

## 2. Generate the dataset

```bash
uv sync
cp .env.example .env          # PG* for the public-record Postgres
uv run python -m bor.export ./release           # person-free (default)
# or, only if the policy allows: uv run python -m bor.export ./release --include-names
```

Produces `release/{owner_groups,owner_group_bbls,operational_networks,operational_network_bbls}.csv`
+ `release/DATA.md`. This is the data half of the artifact — attach it to the release (below),
not committed to git (keeps the repo lean and the data tied to a versioned DOI).

## 3. Verify the numbers

```bash
uv run python -m bor.eval.divergence     # expect ~760 crossing / 616 hiding
```

Cross-check against `docs/parity.md`. Report figures as stable-to-~99.9%, not exact integers
(Splink u-sampling jitter; see parity.md).

## 4. Tag & release **(you)**

```bash
git tag -a v0.1.0 -m "Beneficial Ownership Resolution v0.1.0"
git push origin v0.1.0
```

Create a GitHub Release from the tag and attach the `release/` dataset (zip).

## 5. Mint a DOI on Zenodo **(you)**

Enable the GitHub↔Zenodo integration for this repo (or upload the release archive to Zenodo
directly). Zenodo issues a DOI on the release.

## 6. Fill the DOI back in

Edit `CITATION.cff`: set `doi:` to the Zenodo DOI, bump `version:` to the tag, and add your ORCID.
Commit. (`version` in `pyproject.toml` can drop the `.dev0` suffix at the same time.)

## Still open before a "1.0" release

- The full stratified adjudication protocol (INDETERMINATE class + circularity/data-vintage
  controls) and the packaged worked case studies — the remaining v1 evaluation items.
- v2: DuckDB-native over the public HPD/ACRIS/PLUTO CSVs, so reviewers reproduce with no private DB.
