"""bor.eval.divergence — paired partition divergence vs Who Owns What.

How much, and in which direction, the beneficial-owner-group partition differs from WoW's
registration-clustering partition, over the buildings BOTH systems group (multi-building WoW
portfolios ∩ multi-member owner groups). A DIVERGENCE measure, not accuracy — there is no ground
truth; adjudication decides who is right.

Two directions (a WoW portfolio is an operational network; an owner group is an ownership claim):
  * owners crossing portfolios — an owner group spans >=2 WoW portfolios: BOR *unifies* what WoW
    split (noise in the operational signal; one owner's differently-named LLCs reunited).
  * portfolios hiding >1 owner — a WoW portfolio spans >=2 owner groups: the portfolio is an
    operational network (typically tied by a shared registration office) that spans several
    distinct owners, which BOR keeps apart. Not an error in the portfolio — a different question.

Mirrors WatchlineNYC's compare_kg.wow_divergence exactly, but computes the owner-group partition
off-graph (via bor.owner_groups) instead of reading it from Neo4j. Uses all member bbls, matching
the KG's ``UNWIND l.bbls`` universe.

    uv run python -m bor.eval.divergence     # (PG* / .env set; ~4 min: runs the resolution)
"""
from __future__ import annotations

from collections import defaultdict

from bor.owner_groups import bbl_assignments, resolve_owner_groups


def _wow_partition(conn) -> tuple[dict[str, int], dict[int, int]]:
    """WoW's multi-building portfolios as ``bbl -> orig_id`` plus per-portfolio building counts."""
    bbl_wow: dict[str, int] = {}
    wow_size: dict[int, int] = defaultdict(int)
    with conn.cursor() as cur:
        cur.execute("SELECT orig_id, bbls FROM wow.wow_portfolios WHERE array_length(bbls,1) >= 2")
        for pid, bbls in cur.fetchall():
            for b in (bbls or []):
                bbl_wow[str(b).strip()] = pid
                wow_size[pid] += 1
    return bbl_wow, wow_size


def divergence(conn, *, groups=None) -> dict:
    """Partition divergence of the owner-group layer vs WoW portfolios. Pass ``groups`` (from
    ``resolve_owner_groups``) to reuse a resolution; otherwise it runs one (~4 min)."""
    if groups is None:
        groups = resolve_owner_groups(conn)
    bbl_og = bbl_assignments(groups, rental_only=False)      # all member bbls (matches KG l.bbls)
    bbl_wow, wow_size = _wow_partition(conn)

    both = set(bbl_wow) & set(bbl_og)
    og_to_wow: dict[str, set[int]] = defaultdict(set)
    wow_to_og: dict[int, set[str]] = defaultdict(set)
    for b in both:
        og_to_wow[bbl_og[b]].add(bbl_wow[b])
        wow_to_og[bbl_wow[b]].add(bbl_og[b])

    cross = {g for g, ps in og_to_wow.items() if len(ps) >= 2}   # owners crossing portfolios
    hidden = {p for p, gs in wow_to_og.items() if len(gs) >= 2}  # portfolios hiding >1 owner
    return {
        "wow_portfolios": len(wow_size), "wow_bbls": sum(wow_size.values()),
        "owner_groups": len(set(bbl_og.values())), "owner_group_bbls": len(bbl_og),
        "shared_universe": len(both),
        "owners_crossing_portfolios": len(cross),
        "owners_crossing_bldgs": sum(1 for b in both if bbl_og[b] in cross),
        "portfolios_hiding_multiple_owners": len(hidden),
        "portfolios_hiding_bldgs": sum(1 for b in both if bbl_wow[b] in hidden),
        "agree": len(og_to_wow) - len(cross),
    }


def print_divergence(d: dict) -> None:
    print(f"WoW multi-building portfolios:        {d['wow_portfolios']:>6}  ({d['wow_bbls']} bbls)")
    print(f"beneficial owner groups (multi):      {d['owner_groups']:>6}  ({d['owner_group_bbls']} bbls)")
    print(f"shared universe (grouped in BOTH):    {d['shared_universe']:>6}  buildings")
    print()
    print("  (divergence, not accuracy — how far apart / which way the two groupings differ, not who is right)")
    print(f"owners CROSSING WoW portfolios:  {d['owners_crossing_portfolios']:>5} owner groups span >=2 WoW portfolios  ({d['owners_crossing_bldgs']} bldgs)")
    print(f"portfolios HIDING >1 owner:      {d['portfolios_hiding_multiple_owners']:>5} WoW portfolios span >=2 owner groups  ({d['portfolios_hiding_bldgs']} bldgs)")
    print(f"agree (1:1 on the rest):         {d['agree']:>5} owner groups map to a single WoW portfolio")


if __name__ == "__main__":
    import warnings; warnings.filterwarnings("ignore")
    import logging; logging.getLogger("splink").setLevel(logging.ERROR)
    from bor.db import pg_conn
    conn = pg_conn()
    try:
        print_divergence(divergence(conn))
    finally:
        conn.close()
