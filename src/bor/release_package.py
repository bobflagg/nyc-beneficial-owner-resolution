"""Package a release directory for publication: one zip, its checksum, and release notes.

    uv run python -m bor.release_package release/contract [--out dist]

Publishing is the one step that cannot be taken back, so this refuses anything that should not be
published, rather than trusting whoever runs it to have pointed at the right directory:

* the release must validate against the contract (columns, keys, invariants, checksums);
* it must not be synthetic or an excerpt, and must have been built from clean trees at a released
  version (no ``.dev`` suffix), so the manifest identifies the code that made it;
* the directory may hold only the contract's tables, ``DATA.md`` and ``manifest.json``. Anything else,
  such as a file left from an earlier export, is refused by name. This is the guard that matters: the
  ``release/`` directory of a checkout can hold an export that includes owner names.

The zip is reproducible (sorted entries, fixed timestamps), so the same release always gives the same
checksum.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

from bor.release_schema import TABLES, ReleaseInputError
from bor.release_validate import read_release, validate_release

ALLOWED = {f"{name}.csv" for name in TABLES} | {"DATA.md", "manifest.json"}
_EPOCH = (1980, 1, 1, 0, 0, 0)               # zip's earliest timestamp, so entries do not carry the build time


def package_release(path, out_dir="dist") -> dict:
    """Validate ``path`` and write ``<out_dir>/<name>.zip``, ``.zip.sha256`` and ``-NOTES.md``."""
    src = Path(path)
    if not src.is_dir():
        raise ReleaseInputError(f"{src} is not a directory")
    tables, manifest = read_release(str(src))
    if manifest is None:
        raise ReleaseInputError(f"{src} has no manifest.json: it is not a release")

    if manifest.get("synthetic"):
        raise ReleaseInputError("this is a synthetic release (made-up lots, for tests); it is not published")
    if manifest.get("excerpt"):
        raise ReleaseInputError("this is an excerpt of a release, not a whole one; it is not published")
    code = manifest.get("code") or {}
    unclean = sorted(k for k in ("bor", "nlr") if (code.get(k) or {}).get("dirty") is not False)
    if unclean:
        raise ReleaseInputError(f"built from an unclean or unidentified tree ({', '.join(unclean)}); "
                                "rebuild with REQUIRE_CLEAN=1 from committed code")
    version = (code.get("bor") or {}).get("version") or ""
    if not version or "dev" in version:
        raise ReleaseInputError(f"bor version {version!r} is a development version; release a version "
                                "(for example 0.1.0), then rebuild")

    files = sorted(p.name for p in src.iterdir())
    extra = [f for f in files if f not in ALLOWED]
    if extra:
        raise ReleaseInputError("not part of a release, so not published: " + ", ".join(extra)
                                + ". A release holds only the contract's tables, DATA.md and manifest.json")
    missing = [f for f in ("DATA.md", "manifest.json") if f not in files]
    if missing:
        raise ReleaseInputError("a release needs " + ", ".join(missing))
    errors = [v for v in validate_release(tables, manifest, path=str(src)) if v.severity == "error"]
    if errors:
        raise ReleaseInputError(f"the release does not validate ({len(errors)} errors; first: {errors[0]})")

    name = f"bor-v{version}-{manifest['snapshot_id']}"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files:
            info = zipfile.ZipInfo(f"{name}/{f}", date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (src / f).read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = out / f"{archive.name}.sha256"
    checksum.write_text(f"{digest}  {archive.name}\n")
    notes = out / f"{name}-NOTES.md"
    notes.write_text(release_notes(manifest, tables, version, archive.name, digest))
    return {"zip": archive, "sha256": checksum, "notes": notes, "digest": digest, "files": files,
            "bytes": archive.stat().st_size, "version": version, "run_id": manifest["run_id"]}


def release_notes(manifest: dict, tables: dict, version: str, zip_name: str, digest: str) -> str:
    """Release notes for the GitHub release, from the manifest alone."""
    mm = tables.get("method_metrics")
    status = sorted(set(mm["adjudication_status"].dropna()) - {"none"}) if mm is not None else []
    gold = (f"The method's measured precision rests on a gold of status `{status[0]}`"
            + (" (provisional)." if mm is not None and (mm["provisional"] == "True").any() else ".")) if status else \
        "No method precision is published with this release."
    names_line = ("**Names of people and companies are included**, as HPD and ACRIS filed them, in their own tables "
                  "(see `DATA.md`)." if "observation_contacts" in tables else "**No owner names.**")
    return f"""# Beneficial Ownership Resolution v{version}: release data

Owner Portfolios and Operational Networks resolved from NYC public records (HPD, ACRIS, PLUTO), with the
evidence behind every grouping. {names_line} Every grouping is a lead, not a determination of
ownership, and a precision is the share of sampled pairs judged correct, not the chance that a given link is right.

| | |
|---|---|
| Run | `{manifest['run_id']}` |
| Source snapshot | `{manifest['snapshot_id']}` (complete through {manifest['snapshot_date']}) |
| bor / nlr | `{manifest['code']['bor']['version']}` at `{manifest['bor_revision'][:10]}` / `{manifest['code']['nlr']['version']}` at `{manifest['nlr_revision'][:10]}` |
| Tables | {len(tables)} |
| Contract | version {manifest['schema_version']} |

{gold}

**License:** the data is CC BY 4.0; the code is MIT. Please cite the repository (see `CITATION.cff`) and name
the release by its run id and source snapshot.

The release is valid only with the matching source snapshot: compare `manifest.json`'s `source_tables`
with your own load of the same dump. Start with `DATA.md` inside the archive. The format and the checks a
loader makes are in `docs/release-contract.md` and `docs/kg-mapping.md` in the repository.

**Verify the download**

```bash
shasum -a 256 -c {zip_name}.sha256
```

`{digest}`
"""


def main() -> None:  # pragma: no cover - thin wrapper
    ap = argparse.ArgumentParser(prog="bor.release_package")
    ap.add_argument("release_dir")
    ap.add_argument("--out", default="dist")
    a = ap.parse_args()
    try:
        r = package_release(a.release_dir, a.out)
    except ReleaseInputError as e:
        sys.exit(f"error: {e}")
    print(f"{r['zip']}  ({r['bytes'] / 1e6:.1f} MB, {len(r['files'])} files)\n{r['sha256']}\n{r['notes']}\nsha256 {r['digest']}")


if __name__ == "__main__":
    main()
