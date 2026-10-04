"""bor.eval.wow_structure — what holds Who Owns What's portfolios together.

A DESCRIPTIVE analysis of the graph WoW ships in ``wow.wow_portfolios`` (its per-portfolio ``graph``
column: owner nodes, business-address nodes, and typed edges). It answers a structural question —
*what kind of link makes a portfolio?* — not an accuracy question; nothing here is adjudicated.

Findings are reported as counts and shares:

  * edge types — how much of the graph is shared business address versus shared name;
  * multi-owner portfolios — portfolios with two or more owner nodes, the only ones where a link
    between *different* contact records has to carry the meaning;
  * address-dependent portfolios — multi-owner portfolios whose owner nodes would fall apart into
    separate components if every shared-address edge were removed, i.e. portfolios held together by
    shared business addresses alone;
  * hub addresses — an address that many owner nodes in one portfolio list.

Definitions (kept explicit because the numbers depend on them):

  * an *owner node* is a node of type ``owner``; address nodes are not counted;
  * *address degree* is the number of owner nodes in the portfolio listing the identical ``bizAddr``
    string, a lower bound on the address's citywide degree (a hub can span portfolios, and spelling
    variants of one address count separately);
  * *address-dependent* uses only edges between owner nodes whose type is not ``bizaddr``.

    uv run python -m bor.eval.wow_structure                      # report
    uv run python -m bor.eval.wow_structure --out summary.json --details portfolios.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

HUB_DEGREE = 25        # owner nodes sharing one address: BOR's aggregator-masking degree
MID_HUB_DEGREE = 10    # a looser "busy address" threshold, reported alongside


@dataclass(frozen=True)
class PortfolioStats:
    orig_id: str
    n_bbls: int
    n_owners: int
    edge_types: dict[str, int]
    multi_owner: bool
    address_dependent: bool
    max_address_degree: int


def parse_graph(graph) -> dict:
    """``wow_portfolios.graph`` arrives as a dict (jsonb) or a JSON string; normalize to a dict."""
    if graph is None:
        return {"nodes": [], "edges": []}
    if isinstance(graph, (str, bytes)):
        graph = json.loads(graph)
    return {"nodes": graph.get("nodes") or [], "edges": graph.get("edges") or []}


def _components(ids, edges) -> int:
    """Connected components among ``ids`` using only the given (source, target) edges."""
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    return len({find(i) for i in ids})


def analyze_graph(orig_id, graph, n_bbls: int) -> PortfolioStats:
    """Structural stats for one portfolio's graph. Pure — no database."""
    g = parse_graph(graph)
    owners = [n for n in g["nodes"] if n.get("type") == "owner"]
    edge_types = Counter(e.get("type") for e in g["edges"])
    multi = len(owners) >= 2
    ids = [o["id"] for o in owners]
    address_dependent = False
    if multi:
        non_address = [(e["source"], e["target"]) for e in g["edges"] if e.get("type") != "bizaddr"]
        address_dependent = _components(ids, non_address) > 1
    degree = Counter(o.get("bizAddr") for o in owners if o.get("bizAddr"))
    return PortfolioStats(
        orig_id=str(orig_id), n_bbls=int(n_bbls), n_owners=len(owners),
        edge_types={str(k): v for k, v in edge_types.items()},
        multi_owner=multi, address_dependent=address_dependent,
        max_address_degree=max(degree.values()) if degree else 0,
    )


def summarize(stats, *, hub_degree: int = HUB_DEGREE) -> dict:
    """Aggregate per-portfolio stats into the report numbers."""
    n_port = n_bbl = 0
    edges: Counter = Counter()
    multi_p = multi_b = dep_p = dep_b = hub_p = hub_b = dep_mid = dep_hub = 0
    sizes: list[int] = []
    for s in stats:
        n_port += 1
        n_bbl += s.n_bbls
        edges.update(s.edge_types)
        if not s.multi_owner:
            continue
        multi_p += 1
        multi_b += s.n_bbls
        sizes.append(s.n_owners)
        if s.max_address_degree >= hub_degree:
            hub_p += 1
            hub_b += s.n_bbls
        if s.address_dependent:
            dep_p += 1
            dep_b += s.n_bbls
            dep_mid += s.max_address_degree >= MID_HUB_DEGREE
            dep_hub += s.max_address_degree >= hub_degree
    total_edges = sum(edges.values())
    share = lambda a, b: (a / b) if b else 0.0
    return {
        "portfolios": n_port, "buildings": n_bbl,
        "edges": {"total": total_edges, "by_type": dict(edges),
                  "share_bizaddr": share(edges.get("bizaddr", 0), total_edges),
                  "share_name": share(edges.get("name", 0), total_edges)},
        "multi_owner": {"portfolios": multi_p, "buildings": multi_b,
                        "share_of_portfolios": share(multi_p, n_port), "share_of_buildings": share(multi_b, n_bbl),
                        "median_owner_nodes": statistics.median(sizes) if sizes else 0,
                        "max_owner_nodes": max(sizes) if sizes else 0},
        "address_dependent": {"portfolios": dep_p, "buildings": dep_b,
                             "share_of_multi_owner_portfolios": share(dep_p, multi_p),
                             "share_of_multi_owner_buildings": share(dep_b, multi_b),
                             "share_of_all_buildings": share(dep_b, n_bbl),
                             f"with_address_degree_ge_{MID_HUB_DEGREE}": dep_mid,
                             f"with_address_degree_ge_{hub_degree}": dep_hub},
        "hub_addresses": {"hub_degree": hub_degree, "portfolios": hub_p, "buildings": hub_b,
                          "share_of_all_buildings": share(hub_b, n_bbl)},
    }


def iter_portfolio_stats(conn):
    """Stream every WoW portfolio's stats from Postgres (server-side cursor; the graphs are large)."""
    with conn.cursor(name="bor_wow_structure") as cur:
        cur.itersize = 2000
        cur.execute("SELECT orig_id, graph, bbls FROM wow.wow_portfolios WHERE graph IS NOT NULL")
        for orig_id, graph, bbls in cur:
            yield analyze_graph(orig_id, graph, len(bbls or []))


def format_report(m: dict) -> str:
    pct = lambda x: f"{x * 100:.1f}%"
    e, mo, ad, hub = m["edges"], m["multi_owner"], m["address_dependent"], m["hub_addresses"]
    by = e["by_type"]
    hub_key = f"with_address_degree_ge_{hub['hub_degree']}"
    mid_key = f"with_address_degree_ge_{MID_HUB_DEGREE}"
    lines = [
        "WoW graph structure (wow.wow_portfolios) — descriptive, not accuracy",
        f"portfolios: {m['portfolios']:,}   buildings: {m['buildings']:,}",
        f"edges: {e['total']:,} — shared business address {by.get('bizaddr', 0):,} ({pct(e['share_bizaddr'])}), "
        f"shared name {by.get('name', 0):,} ({pct(e['share_name'])})",
        f"multi-owner portfolios (>=2 owner nodes): {mo['portfolios']:,} ({pct(mo['share_of_portfolios'])} of portfolios) "
        f"hold {mo['buildings']:,} buildings ({pct(mo['share_of_buildings'])})",
        f"  median {mo['median_owner_nodes']:g} owner nodes, max {mo['max_owner_nodes']:,}",
        f"  held together only by shared-address edges: {ad['portfolios']:,} "
        f"({pct(ad['share_of_multi_owner_portfolios'])} of multi-owner) / {ad['buildings']:,} buildings "
        f"({pct(ad['share_of_multi_owner_buildings'])} of multi-owner; {pct(ad['share_of_all_buildings'])} of all buildings)",
        f"    of those, with an address shared by >={MID_HUB_DEGREE} owner nodes: "
        f"{ad[mid_key]:,}; by >={hub['hub_degree']}: {ad[hub_key]:,}",
        f"hub addresses (>={hub['hub_degree']} owner nodes in one portfolio): {hub['portfolios']:,} portfolios "
        f"hold {hub['buildings']:,} buildings ({pct(hub['share_of_all_buildings'])} of all)",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--hub-degree", type=int, default=HUB_DEGREE,
                    help="owner nodes sharing one address to call it a hub (default %(default)s)")
    ap.add_argument("--out", help="write the summary as JSON")
    ap.add_argument("--details", help="write one CSV row per multi-owner portfolio")
    args = ap.parse_args(argv)

    from bor.db import pg_conn
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            database = cur.fetchone()[0]
        rows: list[PortfolioStats] = []
        summary_stats = []
        for s in iter_portfolio_stats(conn):
            summary_stats.append(s)
            if args.details and s.multi_owner:
                rows.append(s)
    finally:
        conn.close()

    summary = summarize(summary_stats, hub_degree=args.hub_degree)
    summary["meta"] = {"database": database, "hub_degree": args.hub_degree,
                       "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    print(format_report(summary))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    if args.details:
        with open(args.details, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["orig_id", "n_bbls", "n_owner_nodes", "address_dependent", "max_address_degree",
                        "edges_bizaddr", "edges_name"])
            for s in rows:
                w.writerow([s.orig_id, s.n_bbls, s.n_owners, int(s.address_dependent), s.max_address_degree,
                            s.edge_types.get("bizaddr", 0), s.edge_types.get("name", 0)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
