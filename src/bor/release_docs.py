"""The data dictionary that ships inside a release: ``DATA.md``, generated from the contract.

    uv run python -m bor.release_docs <release_dir>

A hand-written dictionary drifts from the files it describes. This one is rendered from
:mod:`bor.release_schema` (columns, types, enums, keys, descriptions, vocabularies) and the release's own
``manifest.json`` and tables (provenance, row counts, checksums), so it cannot disagree with either, and
``build_release`` writes it before the checksums are taken. It never lists the checksums (the manifest does),
so rendering it again from the finished release gives the same bytes and the manifest still holds.

It says what a release is and is not. It carries no names; every grouping is a lead, not a determination
of ownership; a precision is not a link probability; and a missing row means nothing.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bor.release_schema import (ADJUDICATION_STATUSES, METRIC_NAMES, METRIC_SCOPES, PRECEDENCE, REASON_CODES,
                                RULES, SCHEMA_VERSION, STAGES, TABLES)
from bor.release_validate import read_release

_INTRO = """\
Owner Portfolios and Operational Networks resolved from NYC public records (HPD registrations and
contacts, ACRIS deeds, PLUTO), with the evidence behind every grouping. **This release contains no owner
names.** Lots are identified by BBL (the public tax-lot id); people, companies and decisions by opaque ids
that are local to one run.

**Read it as leads, not verdicts.** Every grouping is inferred by a method whose precision was measured on a
sample (`method_metrics`). A precision is the share of sampled pairs judged correct in one stratum; it is *not*
the probability that a given link is right, and a group's path chains several pairs. A lot's absence from a
group is a rule the method applied or a record it never saw. It is never evidence that the owners differ, and a
missing row in `bbl_status` means nothing.
"""

_KEYS = """\
- **Layers.** `owner_portfolio` (one resolved owner: identity links and deeds) and `operational_network`
  (operational linkage by name and address, looser by design). Ids are `OP-<n>` and `ON-<n>`, where `n` is the
  group's smallest node id. A node is in at most one group per layer; a BBL is in exactly one node.
- **Run-local ids.** Identities (`I…`), clusters (`C…`), base clusters (`BC…`), evidence (`DV…`), link sets
  (`CG…`, `LG…`), decisions (`D…`, `E…`, `G…`, `N…`), network edges (`NE…`) and masked addresses (`A…`) mean
  something only inside this run. Nothing is stable across releases; membership is the durable content.
- **`assertion_key`** = `<run_id>/<layer>/<group_id>` (a member adds `/n<node>`, a path step `/w<step>`). The
  KG's link id for a lot is `<assertion_key>#<bbl>`.
- **Observations** are HPD contacts, `registration:contact:k`. Join them to HPD on (`registration_id`,
  `registration_contact_id`), never on a name.
- **Counting unit** is the tax lot (BBL), not the building.
"""

_LIMITS = """\
Not promised: that a rerun gives identical groups (resolution is stochastic; a fixed run serializes
deterministically and is checksummed), recall, identity of groups across releases, and that any grouping is
true. A release is valid only with the source snapshot named in the manifest; a refreshed snapshot needs a newly
frozen release.
"""


def _enum(c) -> str:
    return ", ".join(f"`{v}`" for v in c.enum) if c.enum and len(c.enum) <= 6 else (f"{len(c.enum)} values, see below" if c.enum else "")


def render_data_md(manifest: dict, tables: dict | None = None) -> str:
    """The dictionary as Markdown. ``tables`` (as from ``read_release``) adds row counts."""
    m = manifest
    kind = ("an **excerpt** of run " + m["excerpt"]["of_run_id"] + " (a few Owner Portfolios and what they cite)"
            if m.get("excerpt") else "a **synthetic** release of made-up lots, for testing" if m.get("synthetic")
            else "a frozen release")
    out = [f"# Beneficial Ownership Resolution: release `{m['run_id']}`", "",
           f"This directory is {kind}. Contract version {m.get('schema_version', SCHEMA_VERSION)}.", "", _INTRO,
           "## Provenance", ""]
    rows = [("Run", m["run_id"]), ("Source snapshot", m["snapshot_id"]),
            ("Complete through", m.get("snapshot_date")), ("Deed cut-off", m.get("effective_date")), ("Built", m.get("created_at")),
            ("bor revision", m.get("bor_revision")), ("nlr revision", m.get("nlr_revision")),
            ("Source-tree hash", m.get("source_tree_hash")), ("Lockfile digest", m.get("dependency_lock_digest")),
            ("Splink threshold", m.get("threshold"))]
    out += ["| | |", "|---|---|"] + [f"| {k} | `{v}` |" for k, v in rows if v is not None] + [""]
    basis = m.get("snapshot_date_basis") or {}
    if basis:
        out += ["The snapshot is complete through the **earlier** of the newest dates of these columns, so it never "
                "claims more recent data than the dump holds (rows dated after the build are ignored and counted):", "",
                "| column | newest | rows dated after the build |", "|---|---|---|"]
        out += [f"| `{c}` | `{e.get('newest')}` | {e.get('future_dated_rows', 0):,} |" for c, e in basis.items()] + [""]
    code = m.get("code") or {}
    if any(isinstance(c, dict) and c.get("dirty") for c in code.values()):
        out += ["**Built from an uncommitted tree** (`manifest.code.*.dirty`); a tagged release is not.", ""]
    st = m.get("source_tables") or {}
    if st:
        out += ["Source tables, as fingerprinted (compare with your own load using `bor.manifest.fingerprint_sql`):", "",
                "| table | rows | fingerprint |", "|---|---|---|"]
        out += [f"| `{t}` | {e['row_count']:,} | `{e['fingerprint']}` |" for t, e in st.items()] + [""]
    mm = (tables or {}).get("method_metrics")
    if mm is not None and "adjudication_status" in mm.columns:
        statuses = sorted(set(mm["adjudication_status"].dropna()) - {"none"})
        if statuses:
            out += [f"Method metrics rest on a gold of status: {', '.join(f'`{s}`' for s in statuses)}. "
                    "Rows are `provisional` unless the status is `blind_human`.", ""]
    out += ["## Keys and ids", "", _KEYS, "## Files", ""]
    out += ["| file | rows | what it is |", "|---|---|---|"]
    for t in TABLES.values():
        if tables is not None and t.name not in tables:
            continue
        n = f"{len(tables[t.name]):,}" if tables is not None else ""
        out.append(f"| `{t.name}.csv` | {n} | {t.description.split('. ')[0].rstrip('.')}. |")
    out += ["", "`manifest.json` holds the provenance above and the sha256 of every file.", "", "## Tables", ""]
    for t in TABLES.values():
        if tables is not None and t.name not in tables:
            continue
        out += [f"### `{t.name}`", "", t.description, "", f"Key: {', '.join(f'`{k}`' for k in t.key)}.", ""]
        for fk in t.fks:
            out.append(f"References `{fk.table}` on {', '.join(f'`{c}`' for c in fk.cols)}.")
        if t.fks:
            out.append("")
        out += ["| column | type | null | values |", "|---|---|---|---|"]
        out += [f"| `{c.name}` | {c.type} | {'yes' if c.nullable else ''} | {_enum(c)} |" for c in t.columns] + [""]
    out += ["## Vocabularies", "",
            "**Stages** (the link-creating ones carry a path step; the others are group-level policy): "
            + ", ".join(f"`{s}`" for s in STAGES) + ".", "",
            "**Method scopes** (for split precision): " + ", ".join(f"`{s}`" for s in METRIC_SCOPES)
            + ". **Metrics:** " + ", ".join(f"`{s}`" for s in METRIC_NAMES) + ". **Gold status:** "
            + ", ".join(f"`{s}`" for s in ADJUDICATION_STATUSES) + ".", "",
            "**Rules:** " + ", ".join(f"`{r}`" for r in RULES) + ".", "",
            "**Reasons a lot is absent.** The primary reason is the earliest of these levels that applies:", ""]
    out += [f"{i}. `{top}`" for i, top in enumerate(PRECEDENCE, 1)] + ["", "| code | level | meaning |", "|---|---|---|"]
    out += [f"| `{c}` | `{top}` | {d} |" for c, (top, d) in REASON_CODES.items()] + ["", "## Limits", "", _LIMITS]
    return "\n".join(out)


def write_data_md(out_dir, manifest: dict, tables: dict | None = None) -> Path:
    path = Path(out_dir) / "DATA.md"
    path.write_text(render_data_md(manifest, tables))
    return path


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("release_dir")
    a = ap.parse_args()
    tables, manifest = read_release(a.release_dir)
    print(write_data_md(a.release_dir, manifest, tables))


if __name__ == "__main__":
    main()
