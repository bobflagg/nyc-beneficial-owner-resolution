"""bor/owner_groups.py — the beneficial owner group, computed off-graph.

The owner-identity partition: *who is the apparent same owner across differently-named LLCs*,
distinct from the operational network (shared-office clustering) and from management. It is the
connected components of the owner-identity edges — ``CONNECTED_BY_SPLINK`` (record-linkage model
∪ curated ∪ registered-LLC) ∪ ``CONNECTED_BY_DEED`` (the name-free ACRIS veil-pierce) — with a
co-op/condo exclusion.

WatchlineNYC computes this over Neo4j (union-find on materialized edges). BOR computes the
*same* partition off-graph: it runs the four edge builders in memory and union-finds their pairs,
then applies the identical rules — ``min_size=2``, ``OP-<min nodeid>`` roots, RENTAL-only
building_count, and dropping groups that are >50% co-op/condo. The union-find, composition, and
drop logic are ported verbatim from ``portfolio/owner_groups.py`` so BOR's partition matches the
live graph (parity is the acceptance test).

Keying: nodeids come from ``landlords_with_connections`` (lwc). lwc's ``nodeid = row_number()`` is
a per-build surrogate — stable *within* one build (all edge builders read the same lwc), so the
union-find is correct; it is not stable *across* builds, so persisted/exported ids are re-keyed
onto a stable representative (see ``stable_key``) and exports are BBL-keyed (person-safe).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

from bor.curated_owners import curated_edges
from bor.deed_edges import deed_edges
from bor.llc_edges import llc_edges
from bor.splink_bridge import DEFAULT_THRESHOLD, splink_edges

OWNER_GROUP_METHOD = "splink-identity+curated+llc"

# Co-op/condo classification (forked from portfolio/coop_condo.py, verbatim): a building is
# co-op/condo when >50% of its owner-role HPD contacts are described CO-OP/CONDO. Such buildings
# are owned by shareholders, not a landlord; owner groups exclude them and drop groups they dominate.
_COOP_CONDO_SQL = """
    SELECT g.bbl AS bbl
    FROM hpd_contacts c
    JOIN hpd_registrations_grouped_by_bbl_with_contacts g ON g.registrationid = c.registrationid
    WHERE c.type IN ('HeadOfficer','IndividualOwner','CorporateOwner')
    GROUP BY g.bbl
    HAVING avg(CASE WHEN c.contactdescription IN ('CO-OP','CONDO') THEN 1.0 ELSE 0.0 END) > 0.5
"""

_LWC_SQL = "SELECT nodeid, name, bbls::text[] AS bbls FROM landlords_with_connections"


# --- pure union-find + composition (verbatim from portfolio/owner_groups.py) --------------------

def _union_groups(pairs, *, min_size: int = 2) -> dict[int, str]:
    """Union-find over ``pairs`` (nodeid pairs). Returns ``{nodeid: 'OP-<root>'}`` for components
    of >= ``min_size`` members; root = MIN nodeid, so ids are deterministic given the edge set."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(x, x) != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    nodes: set[int] = set()
    for a, b in pairs:
        nodes.add(a); nodes.add(b); union(a, b)

    comp: dict[int, list[int]] = defaultdict(list)
    for n in nodes:
        comp[find(n)].append(n)

    out: dict[int, str] = {}
    for root, members in comp.items():
        if len(members) >= min_size:
            gid = f"OP-{root}"
            for m in members:
                out[m] = gid
    return out


def _roots(pairs) -> dict[int, int]:
    """Union-find over ``pairs``; ``{node: root}`` with root = MIN nodeid (matches _union_groups)."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return {n: find(n) for n in parent}


def classify_composition(identity_pairs, deed_pairs, *, min_size: int = 2) -> dict[str, str]:
    """Per owner group: ``identity`` (one resolved entity), ``deed_only`` (exists purely via deed
    edges — the intended veil-pierce), or ``deed_bridged`` (a deed fuses >=2 identity entities —
    the higher-bar case). Returns ``{owner_group_id: composition}``."""
    id_root = _roots(identity_pairs)
    id_multinode = {r for r in set(id_root.values())
                    if sum(1 for v in id_root.values() if v == r) >= 2}
    all_root = _roots(list(identity_pairs) + list(deed_pairs))

    members: dict[int, list[int]] = defaultdict(list)
    for node, root in all_root.items():
        members[root].append(node)

    out: dict[str, str] = {}
    for root, ms in members.items():
        if len(ms) < min_size:
            continue
        gid = f"OP-{root}"
        entities = {id_root[n] for n in ms if n in id_root and id_root[n] in id_multinode}
        out[gid] = ("deed_bridged" if len(entities) >= 2
                    else "identity" if len(entities) == 1
                    else "deed_only")
    return out


# --- off-graph assembly -------------------------------------------------------------------------

@dataclass
class OwnerGroup:
    """A beneficial owner group. ``bbls`` are the attributed (rental) buildings; ``total_bbls``
    the full footprint. ``stable_key`` re-keys the group off the per-build nodeid onto the min
    (name, bbls-derived) member identity, for cross-build-stable, person-free references."""
    owner_group_id: str            # OP-<min nodeid> — deterministic within a build
    members: list[int]             # lwc nodeids
    bbls: list[str]                # rental bbls (attributed footprint)
    total_bbls: list[str]          # all bbls (full footprint)
    composition: str               # identity | deed_only | deed_bridged
    name: str | None = None        # person anchor (member with the most buildings)
    stable_key: str = field(default="")

    @property
    def building_count(self) -> int:
        return len(self.bbls)

    @property
    def total_building_count(self) -> int:
        return len(self.total_bbls)


def _coop_condo_bbls(conn) -> set[str]:
    cur = conn.cursor()
    cur.execute(_COOP_CONDO_SQL)
    return {str(r[0]).strip() for r in cur.fetchall()}


def _identity_and_deed_pairs(conn, *, threshold: float, include_deed: bool):
    """Return (identity_pairs, deed_pairs) as lists of (src, dst) nodeid tuples.
    identity = CONNECTED_BY_SPLINK (model ∪ curated ∪ registered-LLC); deed = CONNECTED_BY_DEED."""
    frames = [splink_edges(conn, threshold=threshold), curated_edges(conn), llc_edges(conn)]
    identity = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["src", "dst"])
    id_pairs = list(zip(identity["src"].astype(int), identity["dst"].astype(int)))
    deed_pairs: list[tuple[int, int]] = []
    if include_deed:
        d = deed_edges(conn)
        if len(d):
            deed_pairs = list(zip(d["src"].astype(int), d["dst"].astype(int)))
    return id_pairs, deed_pairs


def resolve_owner_groups(conn, *, threshold: float = DEFAULT_THRESHOLD,
                         include_deed: bool = True, min_size: int = 2) -> list[OwnerGroup]:
    """Resolve beneficial owner groups off-graph. Runs the four edge builders, union-finds their
    pairs (CONNECTED_BY_SPLINK ∪ CONNECTED_BY_DEED), maps components to buildings via lwc, applies
    the co-op/condo exclusion, and returns the surviving groups. KG-free."""
    id_pairs, deed_pairs = _identity_and_deed_pairs(conn, threshold=threshold, include_deed=include_deed)
    assign = _union_groups(id_pairs + deed_pairs, min_size=min_size)   # {nodeid: OP-id}
    if not assign:
        return []
    comp = classify_composition(id_pairs, deed_pairs, min_size=min_size)

    lwc = pd.read_sql(_LWC_SQL, conn)
    lwc = lwc[lwc["nodeid"].isin(assign)].copy()
    lwc["nodeid"] = lwc["nodeid"].astype(int)
    coop = _coop_condo_bbls(conn)

    # gather per group: members, name-anchor candidate, and bbl sets
    members: dict[str, list[int]] = defaultdict(list)
    total_bbls: dict[str, set[str]] = defaultdict(set)
    rental_bbls: dict[str, set[str]] = defaultdict(set)
    best_name: dict[str, tuple[int, str]] = {}   # gid -> (n_bbls, name) for the person anchor
    for nodeid, name, bbls in zip(lwc["nodeid"], lwc["name"], lwc["bbls"]):
        gid = assign[nodeid]
        members[gid].append(nodeid)
        clean = [str(b).strip() for b in (bbls or []) if b]
        total_bbls[gid].update(clean)
        rental_bbls[gid].update(b for b in clean if b not in coop)
        if name and (gid not in best_name or len(clean) > best_name[gid][0]):
            best_name[gid] = (len(clean), name)

    groups: list[OwnerGroup] = []
    for gid, mem in members.items():
        total = total_bbls[gid]
        rental = rental_bbls[gid]
        # drop co-op/condo-DOMINATED groups (>50% of buildings co-op/condo): management artifacts
        if len(total) > 0 and 2 * len(rental) < len(total):
            continue
        mem_sorted = sorted(mem)
        groups.append(OwnerGroup(
            owner_group_id=gid,
            members=mem_sorted,
            bbls=sorted(rental),
            total_bbls=sorted(total),
            composition=comp.get(gid, "identity"),
            name=best_name.get(gid, (0, None))[1],
            stable_key="OG:" + min(str(n) for n in mem_sorted),  # placeholder stable rep; see note
        ))
    return sorted(groups, key=lambda g: g.owner_group_id)


def assignments(groups: list[OwnerGroup]) -> dict[int, str]:
    """``{nodeid: owner_group_id}`` over the surviving groups — the partition to parity-check."""
    return {n: g.owner_group_id for g in groups for n in g.members}


def bbl_assignments(groups: list[OwnerGroup], *, rental_only: bool = True) -> dict[str, str]:
    """``{bbl: owner_group_id}`` — the person-free export/benchmark key. Rental bbls by default."""
    out: dict[str, str] = {}
    for g in groups:
        for bbl in (g.bbls if rental_only else g.total_bbls):
            out[bbl] = g.owner_group_id
    return out
