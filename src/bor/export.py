"""bor.export — the citeable dataset export.

Writes the resolved layers as a small set of CSVs suitable for a versioned, DOI'd data release.

**Person-free by default.** The project's dual-use reflection argues for capability governance over a
one-click bulk person-profiling affordance, and flags the doxxing / mosaic risk of a person-linked
dataset. So this export is keyed on **BBL** (a public parcel identifier) and **opaque group ids**,
and carries composition + building counts but **no owner names**. Names are the sensitive join; a
release that includes them is a deliberate choice — pass ``include_names=True`` to opt in, and only
do so if the release policy calls for it.

    uv run python -m bor.export ./release      # (PG* / .env set; runs both resolutions, ~5 min)
"""
from __future__ import annotations

import csv
import os

from bor.operational_network import resolve_operational_networks
from bor.owner_groups import resolve_owner_groups
from bor.splink_bridge import DEFAULT_THRESHOLD

_DICTIONARY = """# Beneficial Ownership Resolution — dataset

Resolved from NYC public records (HPD registrations, ACRIS deeds, PLUTO); see the repo README. Every grouping is an **inference** — a lead to verify, not a
legal determination of ownership. Keyed on BBL (public parcel id) and opaque group ids; {names_clause}.

## Files

- `owner_groups.csv` — one row per beneficial owner group.
  `owner_group_id` (opaque), `composition` (identity | deed_only | deed_bridged),
  `building_count` (rental buildings attributed), `total_building_count` (full footprint){name_col}.
- `owner_group_bbls.csv` — `bbl`, `owner_group_id`. The building→owner-group map (rental).
- `operational_networks.csv` — one row per operational-network portfolio.
  `portfolio_id` (opaque), `building_count`, `split` (wcc = exact | louvain = oversized-tail split).
- `operational_network_bbls.csv` — `bbl`, `portfolio_id`. The building→operational-network map.

Group ids are stable within a build, not across builds (they key off a per-build surrogate); join
on the ids within this release, and treat membership as the durable content. See docs/parity.md for
reproducibility (owner groups reproduce the graph exactly; the operational-network Louvain tail is
approximate).
"""


def export(conn, out_dir: str, *, include_names: bool = False,
           threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Resolve both layers and write the release CSVs into ``out_dir``. Returns a small manifest."""
    os.makedirs(out_dir, exist_ok=True)
    groups = resolve_owner_groups(conn, threshold=threshold)
    nets = resolve_operational_networks(conn, threshold=threshold)

    def _write(name, header, rows):
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    og_header = ["owner_group_id", "composition", "building_count", "total_building_count"]
    if include_names:
        og_header.append("name")
    _write("owner_groups.csv", og_header, [
        [g.owner_group_id, g.composition, g.building_count, g.total_building_count]
        + ([g.name or ""] if include_names else [])
        for g in groups
    ])
    _write("owner_group_bbls.csv", ["bbl", "owner_group_id"],
           [[bbl, g.owner_group_id] for g in groups for bbl in g.bbls])

    _write("operational_networks.csv", ["portfolio_id", "building_count", "split"],
           [[n.portfolio_id, n.building_count, n.split] for n in nets])
    _write("operational_network_bbls.csv", ["bbl", "portfolio_id"],
           [[bbl, n.portfolio_id] for n in nets for bbl in n.bbls])

    names_clause = (
        "and **includes owner names** (person anchors) — this is a person-linked release"
        if include_names else
        "and contains **no owner names** (names withheld — the sensitive join)")
    name_col = ", `name` (person anchor — INCLUDED in this build)" if include_names else ""
    with open(os.path.join(out_dir, "DATA.md"), "w") as f:
        f.write(_DICTIONARY.format(names_clause=names_clause, name_col=name_col))

    manifest = {
        "owner_groups": len(groups),
        "owner_group_bbls": sum(len(g.bbls) for g in groups),
        "operational_networks": len(nets),
        "operational_network_bbls": sum(len(n.bbls) for n in nets),
        "includes_names": include_names,
    }
    return manifest


if __name__ == "__main__":
    import sys, warnings, logging
    warnings.filterwarnings("ignore"); logging.getLogger("splink").setLevel(logging.ERROR)
    from bor.db import pg_conn
    out = sys.argv[1] if len(sys.argv) > 1 else "release"
    include_names = "--include-names" in sys.argv[2:]
    conn = pg_conn()
    try:
        m = export(conn, out, include_names=include_names)
    finally:
        conn.close()
    print(f"wrote release to {out}/ :", m)
