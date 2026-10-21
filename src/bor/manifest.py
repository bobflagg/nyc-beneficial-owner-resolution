"""The release manifest: what a release was built from, by what code, and what it contains.

A release is valid only when the KG loads the matching source snapshot (docs/release-contract.md),
so the manifest has to let a reader *check* that, not trust it:

* ``source_tables`` — row count and an order-independent fingerprint of every table bor read.
  The fingerprint is ``sum(first 60 bits of md5(row::text))``; the KG runs the same SQL on its own
  tables (see :func:`fingerprint_sql`) and refuses a mismatch.
* ``source_tree_hash`` and ``code`` — the code that ran, hashed from the files themselves, because a
  commit SHA plus a "dirty" flag does not identify modified content. nlr is included, since its
  changes are part of what produced the result.
* ``dependency_lock_digest`` and ``environment`` — the lock file, and the versions actually loaded.
* ``effective_date`` — the deed cut-off the queries used in place of ``CURRENT_DATE``.
* ``output_checksums`` — sha256 of every file in the release, computed last.

``snapshot_id`` takes whatever form the KG defines (an open KG decision); it is supplied by the
caller and repeated exactly.
"""
from __future__ import annotations

import hashlib
import importlib.metadata as md
import inspect
import json
import platform
import subprocess
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from bor import release_schema as schema

# Tables bor reads. landlords_with_connections is derived from wow_landlords by bor.build_lwc; its
# node ids are assigned by an unordered row_number(), so it is fingerprinted too: the KG's release
# is only meaningful against the same node numbering.
SOURCE_TABLES = (
    "hpd_contacts", "hpd_registrations", "hpd_registrations_grouped_by_bbl_with_contacts",
    "wow_landlords", "landlords_with_connections", "pluto_latest",
    "real_property_master", "real_property_legals", "real_property_parties",
)
FINGERPRINT_METHOD = "count + sum(first 60 bits of md5(row::text)) as numeric"
_CODE_SUFFIXES = (".py", ".sql")


def fingerprint_sql(table: str) -> str:
    """The SQL that fingerprints ``table``. Order-independent, so row order and physical layout do
    not matter; it does depend on column order and types, which a dump preserves."""
    return (f"SELECT count(*), coalesce(sum(('x' || substr(md5(t::text), 1, 15))::bit(60)::bigint), 0) "
            f"FROM {table} t")


def source_tables(conn, tables=SOURCE_TABLES) -> dict:
    out = {}
    cur = conn.cursor()
    for t in tables:
        cur.execute(fingerprint_sql(t))
        n, f = cur.fetchone()
        out[t] = {"row_count": int(n), "fingerprint": str(f), "fingerprint_method": FINGERPRINT_METHOD}
    return out


# ---- code identity -------------------------------------------------------------------------------

def tree_hash(root: Path, suffixes=_CODE_SUFFIXES) -> str:
    """sha256 over the relative paths and contents of the code files under ``root``."""
    h = hashlib.sha256()
    for f in sorted(p for p in Path(root).rglob("*") if p.suffix in suffixes and "__pycache__" not in p.parts):
        h.update(str(f.relative_to(root)).encode() + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _git(root: Path, *args) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _is_ignored(path: Path) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(path), "check-ignore", "-q", str(path)], capture_output=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _package_state(package_dir: Path, dist_name: str, repo_root: Path | None) -> dict:
    """Revision, dirty flag and tree hash of one package. In a git checkout the revision is the HEAD
    commit and ``dirty`` says whether code files differ from it; an installed copy has the commit
    from pip's direct_url.json when installed from git, and is never dirty (it is what it is)."""
    state = {"version": md.version(dist_name), "tree_hash": tree_hash(package_dir),
             "revision": None, "dirty": None, "checkout": None}
    root = repo_root or package_dir
    top = _git(root, "rev-parse", "--show-toplevel")
    # A package installed under a checkout's own .venv is inside that repo's tree but is not part of
    # it (the .venv is ignored); only a package git actually tracks has a revision of its own.
    if top and not _is_ignored(package_dir):
        state["revision"] = _git(Path(top), "rev-parse", "HEAD")
        status = _git(Path(top), "status", "--porcelain", "--untracked-files=all", "--", str(package_dir),
                      "pyproject.toml", "uv.lock") or ""
        state["dirty"] = bool(status.strip())
        state["checkout"] = top
    else:
        try:
            direct = json.loads(md.distribution(dist_name).read_text("direct_url.json") or "{}")
            state["revision"] = direct.get("vcs_info", {}).get("commit_id")
        except (md.PackageNotFoundError, json.JSONDecodeError):
            pass
    return state


def code_state() -> dict:
    """bor's and nlr's identity. Neither is trusted to be a clean checkout: the tree hashes are the
    ground truth."""
    import nlr

    bor_dir = Path(__file__).resolve().parent
    nlr_dir = Path(nlr.__file__).resolve().parent
    return {"bor": _package_state(bor_dir, "nyc-beneficial-owner-resolution", bor_dir.parents[1]),
            "nlr": _package_state(nlr_dir, "nyc-landlord-resolution", None)}


def combined_tree_hash(code: dict) -> str:
    return hashlib.sha256(f"bor:{code['bor']['tree_hash']}|nlr:{code['nlr']['tree_hash']}".encode()).hexdigest()


def lock_digest(path: Path) -> str | None:
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def environment() -> dict:
    def v(name):
        try:
            return md.version(name)
        except md.PackageNotFoundError:
            return None
    return {"python": platform.python_version(), "platform": platform.platform(),
            **{n: v(n) for n in ("splink", "duckdb", "pandas", "numpy", "psycopg2-binary")}}


def normalizer_versions() -> dict:
    """A content version for each normalizer: a hash of its source. It changes when the code does."""
    import nlr
    from bor import operational_network, splink_bridge

    def h(fn):
        return hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()[:12]

    return {"business_address_mask": h(operational_network._norm_bizaddr),
            "owner_name": h(nlr.normalize_name),
            "name_match_key": h(splink_bridge._norm),
            "nlr_address_key": h(nlr.splink_source._addr_key)}


def parameters(resolution_params: dict | None, as_of: date) -> dict:
    """Every constant that shapes the result."""
    from bor import _edges, deed_edges, llc_edges, operational_network

    return {
        "resolution": resolution_params or {},
        "deed": {"min_parcels": deed_edges.MIN_PARCELS, "max_parcels": deed_edges.MAX_PARCELS,
                 "hub_cap": deed_edges.DEED_HUB_CAP, "successor_max": deed_edges.SUCCESSOR_MAX,
                 "nominal_max": deed_edges.NOMINAL_MAX, "restructure_min_date": str(deed_edges.RESTRUCT_MIN_DATE),
                 "as_of": as_of.isoformat()},
        "operational_network": {"name_weight": operational_network.NAME_WEIGHT_MULTIPLIER,
                                "address_weight": operational_network.ADDRESS_WEIGHT_MULTIPLIER,
                                "max_address_degree": operational_network.MAX_ADDR_DEGREE,
                                "max_size": operational_network.MAX_SIZE},
        "edges": {"identity_weight": _edges.SPLINK_WEIGHT, "star_above": _edges.STAR_ABOVE},
        "registered_llc": {"max_degree": llc_edges.DEFAULT_MAX_DEGREE},
        "owner_group": {"min_size": 2},
    }


# ---- assembly ------------------------------------------------------------------------------------

def file_checksums(out_dir: Path) -> dict:
    """sha256 of every file in a release directory except the manifest itself."""
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(Path(out_dir).iterdir()) if f.is_file() and f.name != "manifest.json"}


def build_manifest(conn, *, snapshot_id: str, pluto_snapshot_id: str | None = None, as_of: date | None = None,
                   run_id: str | None = None, resolution_params: dict | None = None,
                   artifacts: dict | None = None, lock_file: Path | None = None,
                   tables=SOURCE_TABLES, diagnostics: dict | None = None) -> dict:
    """The manifest for a release about to be built, without ``output_checksums`` (added by
    :func:`write_manifest` once the files exist)."""
    from bor import deed_edges

    as_of = as_of or date.today()
    run_id = run_id or f"{as_of.isoformat()}-{uuid.uuid4().hex[:8]}"
    code = code_state()
    lock = lock_file or Path(__file__).resolve().parents[2] / "uv.lock"
    return {
        "schema_version": schema.SCHEMA_VERSION,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "pluto_snapshot_id": pluto_snapshot_id or snapshot_id,
        "effective_date": as_of.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bor_revision": code["bor"]["revision"],
        "nlr_revision": code["nlr"]["revision"] or f"v{code['nlr']['version']}",
        "source_tree_hash": combined_tree_hash(code),
        "code": code,
        "dependency_lock_digest": lock_digest(lock),
        "environment": environment(),
        "threshold": (resolution_params or {}).get("threshold"),
        "parameters": parameters(resolution_params, as_of),
        "source_tables": source_tables(conn, tables),
        "deed_selection_rule": {"rule": deed_edges.DEED_DOCTYPE_RULE, "version": "1"},
        "normalizer_versions": normalizer_versions(),
        "artifacts": artifacts or {},
        "stage_vocabulary_version": schema.SCHEMA_VERSION,
        "reason_vocabulary_version": schema.SCHEMA_VERSION,
        "diagnostics": diagnostics or {},
    }


def write_manifest(out_dir, manifest: dict) -> Path:
    """Checksum the release files, then write ``manifest.json`` (checksums last, so they cover
    everything the manifest describes)."""
    out = Path(out_dir)
    m = dict(manifest)
    m["output_checksums"] = file_checksums(out)
    path = out / "manifest.json"
    path.write_text(json.dumps(m, indent=2, sort_keys=False, default=str) + "\n")
    return path
