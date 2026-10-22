"""Regenerate tests/fixtures/synthetic_release (synthetic; not real data).

    uv run python tests/fixtures/make_synthetic_release.py

One run, ``synthetic-0001``, built to exercise every table of the contract and every case a consumer
has to handle. Every BBL starts with 9 (there is no borough 9) and every id is in a reserved range, so
nothing in it can be mistaken for a real lot or a real run; ``manifest.synthetic`` is true.
``bbl_status`` is computed by the real ``bor.absence.bbl_status_table``, not written by hand.

Cases (node ids are 9xxx; a group is named for its smallest node):

A  9001-9007  A transitive feedback bridge. OP-9001: 9001-9002 by a scored decision, 9002-9003 by a
              feedback merge through a private company (9001 and 9003 were never compared), 9003-9005
              by a scored decision; 9005 is a co-op, left out of the rental footprint. 9004 scored
              above threshold against 9003 and was blocked by the first-name veto. 9006-9007 link but
              are co-ops: the group OP-9006 is dropped.
B  9010-9013  A deed that mixes held and transferred parcels (OP-9010, deed_only): two parcels still
              held under the joint deed, two moved onward at $0 into single-purpose LLCs, and a fifth
              (9013) rejected because its onward transfer was not nominal.
C  9030-9033  A hub-capped node with another valid link. 9030 is on too many multi-parcel deeds, so it
              is left out of every deed clique, but it stays in OP-9030 through its identity (9031).
              Its parcel is on the same deed as 9032 and 9033, which the deed does link (OP-9032).
D  9040-9041  A deed screened out as co-op/condo dominated: both lots absent, with the deed as the reason.
E  9050-9052  An ambiguous contact mapping. 9050's registration has two contacts, two identities, two
              clusters, tied; the tie rule picks one (OP-9050 with 9051). 9052, in the other cluster, has no group.
F  9060-9067  A connected component split across communities. Louvain cuts NC-1 into ON-9060 and
              ON-9063; the edge 9062-9063 crosses the boundary. A masked hub address (A9000001) leaves
              9066 and 9067 without a network. 9060-9061 are also one Owner Portfolio (OP-9060).
G  9070-9073  A deed that bridges two resolved owners (OP-9070, deed_bridged).
H  9080-9083  Link sets: a registered-LLC set (OP-9080) and a curated owner (OP-9082).
I  9090-9091  A node that matched no identity (9090), and a node with no linkage at all (9091).
U             Two lots outside the method's input: one with no HPD registration, one registered with
              no qualifying owner contact.
"""
import hashlib
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from bor import absence                                           # noqa: E402
from bor.identity_events import EVENT_COLUMNS                     # noqa: E402
from bor.release_schema import TABLES                             # noqa: E402
from bor.release_validate import validate_release                 # noqa: E402

D = os.path.join(os.path.dirname(__file__), "synthetic_release")
R = "synthetic-0001"
RV = "synthetic-0"
OP, ON = "owner_portfolio", "operational_network"
T: dict[str, list] = {name: [] for name in TABLES}


def add(table, **row):
    T[table].append(row)


def bbl(block, lot):
    return f"9{block:04d}{lot:05d}"


# --- lots and nodes -------------------------------------------------------------------------------

NODES = {                                   # node id -> its lots
    9001: [bbl(1, 1)], 9002: [bbl(1, 2)], 9003: [bbl(1, 3)], 9004: [bbl(1, 4)], 9005: [bbl(1, 5)],
    9006: [bbl(1, 6)], 9007: [bbl(1, 7)],
    9010: [bbl(2, 1)], 9011: [bbl(2, 2)], 9012: [bbl(2, 3), bbl(2, 4)], 9013: [bbl(2, 5)],
    9030: [bbl(3, 1)], 9031: [bbl(3, 2)], 9032: [bbl(3, 3)], 9033: [bbl(3, 4)],
    9040: [bbl(4, 1)], 9041: [bbl(4, 2)],
    9050: [bbl(5, 1)], 9051: [bbl(5, 2)], 9052: [bbl(5, 3)],
    **{9060 + i: [bbl(6, 1 + i)] for i in range(8)},
    9070: [bbl(7, 1)], 9071: [bbl(7, 2)], 9072: [bbl(7, 3)], 9073: [bbl(7, 4)],
    9080: [bbl(8, 1)], 9081: [bbl(8, 2)], 9082: [bbl(8, 3)], 9083: [bbl(8, 4)],
    9090: [bbl(9, 1)], 9091: [bbl(9, 2)],
}
COOP = {bbl(1, 5), bbl(1, 6), bbl(1, 7)}                       # lots of co-ops/condos
U_NO_REGISTRATION, U_NO_CONTACT = bbl(99, 1), bbl(99, 2)
LOT_NODE = {b: n for n, bs in NODES.items() for b in bs}
REG = {b: 700000 + i for i, b in enumerate(sorted(LOT_NODE), 1)}      # one registration per lot
CONTACT = {b: REG[b] * 100 + 5 for b in LOT_NODE}
OBS = {b: f"{REG[b]}:{CONTACT[b]}:0" for b in LOT_NODE}               # the person contact behind each lot


def first_lot(n):
    return NODES[n][0]


# --- identities and clusters ------------------------------------------------------------------------

CLUSTERS = {                                # cluster -> nodes whose identity belongs to it
    "A": [9001, 9002, 9003, 9005], "Ad": [9004], "Afg": [9006, 9007],
    "B1": [9010], "B2": [9011], "B3": [9012], "B4": [9013],
    "C": [9030, 9031], "C3": [9032], "C4": [9033], "D1": [9040], "D2": [9041],
    "F": [9060, 9061], **{f"F{n}": [n] for n in range(9062, 9068)},
    "G1": [9070, 9071], "G2": [9072, 9073],
    **{f"H{n}": [n] for n in range(9080, 9084)}, "I": [9091],
}
BASE = {9001: "ab", 9002: "ab", 9003: "ce", 9005: "ce"}               # base clusters finer than the cluster
IDENT, CL_ID = {}, {}
_i = 0
for ci, (name, nodes) in enumerate(CLUSTERS.items(), 1):
    CL_ID[name] = f"C{9000000 + ci}"
    for n in nodes:
        _i += 1
        IDENT[n] = f"I{9000000 + _i}"
BASE_OF = {n: f"{name}/{BASE.get(n, '')}" for name, nodes in CLUSTERS.items() for n in nodes}
BC_ID = {b: f"BC{9000000 + i}" for i, b in enumerate(sorted(set(BASE_OF.values())), 1)}
for n in sorted(BASE_OF):
    add("identity_clusters", identity_id=IDENT[n], cluster_id=CL_ID[BASE_OF[n].split("/")[0]],
        base_cluster_id=BC_ID[BASE_OF[n]])
# Case E: node 9050's registration lists two contacts; each is an identity in a different cluster
E_X, E_Y = (f"{REG[bbl(5, 1)]}:{REG[bbl(5, 1)] * 100 + k}:0" for k in (5, 6))
for j, (key, cluster, obs) in enumerate((("9050a", "Ea", E_X), ("9051", "Ea", OBS[bbl(5, 2)]),
                                         ("9050b", "Eb", E_Y), ("9052", "Eb", OBS[bbl(5, 3)])), 1):
    IDENT[key] = f"I{9000000 + _i + j}"
    CL_ID[cluster] = f"C{9000000 + len(CLUSTERS) + (1 if cluster == 'Ea' else 2)}"
    BC_ID.setdefault(cluster, f"BC{9000000 + len(BC_ID) + 1}")
    add("identity_clusters", identity_id=IDENT[key], cluster_id=CL_ID[cluster], base_cluster_id=BC_ID[cluster])
IDENT[9051], IDENT[9052] = IDENT["9051"], IDENT["9052"]
for key, obs in (("9050a", E_X), ("9050b", E_Y), ("9051", OBS[bbl(5, 2)]), ("9052", OBS[bbl(5, 3)])):
    lot = bbl(5, {"9050a": 1, "9050b": 1, "9051": 2, "9052": 3}[key])
    add("identity_observations", identity_id=IDENT[key], bbl=lot, observation_id=obs,
        tied_registration=str(key.startswith("9050")))
for n in sorted(BASE_OF):
    for b in NODES[n]:
        add("identity_observations", identity_id=IDENT[n], bbl=b, observation_id=OBS[b], tied_registration="False")

# --- observations, nodes -------------------------------------------------------------------------------

CORP = [f"{REG[bbl(1, 1)]}:{REG[bbl(1, 1)] * 100 + 1}:0", f"{REG[bbl(1, 3)]}:{REG[bbl(1, 3)] * 100 + 1}:0"]
all_obs = {o: (o.split(":")[0], o.split(":")[1]) for o in [*OBS.values(), *CORP, E_Y]}
for o, (reg, contact) in sorted(all_obs.items()):
    add("observations", observation_id=o, registration_id=reg, registration_contact_id=contact, k=0, pair_variants=1)
for n, lots in NODES.items():
    for b in lots:
        if n == 9050:
            add("node_observations", node_id=n, bbl=b, registration_id=REG[b], n_candidates=2, selected_observation_id=None, ambiguous="True")
            add("node_observation_alternatives", node_id=n, bbl=b, observation_id=E_X)
            add("node_observation_alternatives", node_id=n, bbl=b, observation_id=E_Y)
        else:
            add("node_observations", node_id=n, bbl=b, registration_id=REG[b], n_candidates=1,
                selected_observation_id=OBS[b], ambiguous="False")
        if n == 9090:
            continue                                      # matched no identity
        if n == 9050:
            for key in ("9050a", "9050b"):
                add("node_identity_matches", node_id=n, identity_id=IDENT[key], bbl=b)
        elif n in IDENT:
            add("node_identity_matches", node_id=n, identity_id=IDENT[n], bbl=b)
node_cluster = {n: CL_ID[name] for name, ns in CLUSTERS.items() for n in ns}
node_cluster[9050], node_cluster[9051], node_cluster[9052] = CL_ID["Ea"], CL_ID["Ea"], CL_ID["Eb"]
for n in sorted(node_cluster):
    if n == 9050:
        add("node_cluster", node_id=n, cluster_id=CL_ID["Ea"], n_clusters=2, tied="True")
        add("node_cluster_alternatives", node_id=n, cluster_id=CL_ID["Ea"], votes=1, selected="True")
        add("node_cluster_alternatives", node_id=n, cluster_id=CL_ID["Eb"], votes=1, selected="False")
    else:
        add("node_cluster", node_id=n, cluster_id=node_cluster[n], n_clusters=1, tied="False")

# --- decision events -------------------------------------------------------------------------------------

_n = {"D": 0, "E": 0, "G": 0, "N": 0}


def event(prefix, layer, stage, subject, outcome, rule, *, counterpart=None, reason=None, score=None,
          threshold=None, cluster=None, detail=None, support=()):
    _n[prefix] += 1
    did = f"{prefix}{9000000 + _n[prefix]}"
    add("decision_events", decision_id=did, layer=layer, stage=stage, subject_type=subject[0], subject_id=subject[1],
        counterpart_type=counterpart[0] if counterpart else None, counterpart_id=counterpart[1] if counterpart else None,
        outcome=outcome, reason_code=reason, rule=rule, rule_version=RV, score=score, threshold=threshold,
        cluster_id=cluster, detail=json.dumps(detail, sort_keys=True) if detail else None)
    for typ, sid, role in support:
        add("decision_support", decision_id=did, support_type=typ, support_id=sid, role=role)
    return did


# A
event("D", "identity", "identity.splink_base", ("identity", IDENT[9001]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9002]), score=0.9995, threshold=0.999, cluster=CL_ID["A"],
      support=[("observation", OBS[first_lot(9001)], "endpoint_a"), ("observation", OBS[first_lot(9002)], "endpoint_b")])
event("D", "identity", "identity.splink_feedback", ("base_cluster", BC_ID["A/ab"]), "accepted", "shared_company_feedback",
      counterpart=("base_cluster", BC_ID["A/ce"]), cluster=CL_ID["A"], detail={"note": "shared private company; degree cap passed"},
      support=[("observation", CORP[0], "bridging_company"), ("observation", CORP[1], "bridging_company")])
event("D", "identity", "identity.splink_base", ("identity", IDENT[9004]), "rejected", "first_name_veto",
      counterpart=("identity", IDENT[9003]), reason="first_name_veto", score=0.9996, threshold=0.999,
      detail={"note": "scored above threshold; blocked by the gate"},
      support=[("observation", OBS[first_lot(9004)], "endpoint_a"), ("observation", OBS[first_lot(9003)], "endpoint_b")])
event("D", "identity", "identity.splink_feedback", ("base_cluster", BC_ID["Ad/"]), "rejected", "shared_company_guard",
      counterpart=("base_cluster", BC_ID["A/ab"]), reason="shared_company_name_not_rare",
      detail={"note": "the shared company's name is common"})
event("D", "identity", "identity.splink_base", ("identity", IDENT[9003]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9005]), score=0.9997, threshold=0.999, cluster=CL_ID["A"],
      support=[("observation", OBS[first_lot(9003)], "endpoint_a"), ("observation", OBS[first_lot(9005)], "endpoint_b")])
event("D", "identity", "identity.splink_base", ("identity", IDENT[9006]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9007]), score=0.9993, threshold=0.999, cluster=CL_ID["Afg"],
      support=[("observation", OBS[first_lot(9006)], "endpoint_a"), ("observation", OBS[first_lot(9007)], "endpoint_b")])
event("G", OP, "owner_portfolio.footprint", ("bbl", bbl(1, 5)), "excluded", "coop_condo_contact_rule",
      reason="coop_condo_excluded", counterpart=("group", "OP-9001"), detail={"note": "co-op lot in a surviving group"},
      support=[("bbl", bbl(1, 5), "excluded_lot")])
event("G", OP, "owner_portfolio.footprint", ("group", "OP-9006"), "dropped", "group_footprint_rule",
      reason="coop_condo_dominated", detail={"lots": 2, "rental_lots": 0})
for lot in (bbl(1, 6), bbl(1, 7)):
    event("G", OP, "owner_portfolio.footprint", ("bbl", lot), "excluded", "group_footprint_rule",
          reason="coop_condo_dominated", counterpart=("group", "OP-9006"))

# B
D1, L3, L4, L5 = "2999010100001001", "2999060100002001", "2999060100002002", "2999060100002003"
event("E", OP, "deed.linked_successor", ("parcel", bbl(2, 5)), "rejected", "deed_successor_guard",
      counterpart=("deed_document", D1), reason="successor_transfer_not_nominal", detail={"latest_amount": 3200000.0},
      support=[("document", D1, "joint_deed"), ("document", L5, "latest_deed")])
# C
event("D", "identity", "identity.splink_base", ("identity", IDENT[9030]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9031]), score=0.9996, threshold=0.999, cluster=CL_ID["C"],
      support=[("observation", OBS[first_lot(9030)], "endpoint_a"), ("observation", OBS[first_lot(9031)], "endpoint_b")])
event("E", OP, "deed.group", ("node", "9030"), "excluded", "deed_hub_cap", reason="deed_hub_capped",
      detail={"deeds": 21, "hub_cap": 20})
# D
D3 = "2999040400005001"
event("E", OP, "deed.held_since", ("deed_document", D3), "excluded", "coop_condo_deed_rule", reason="coop_condo_dominated",
      detail={"n_parcels": 2, "screen": "co-op/condo parcels are the majority"},
      support=[("document", D3, "deed"), ("bbl", bbl(4, 1), "parcel"), ("bbl", bbl(4, 2), "parcel")])
# E
event("D", "identity", "identity.splink_base", ("identity", IDENT["9050a"]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9051]), score=0.9994, threshold=0.999, cluster=CL_ID["Ea"],
      support=[("observation", E_X, "endpoint_a"), ("observation", OBS[first_lot(9051)], "endpoint_b")])
event("D", "identity", "identity.splink_base", ("identity", IDENT["9050b"]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9052]), score=0.9994, threshold=0.999, cluster=CL_ID["Eb"],
      support=[("observation", E_Y, "endpoint_a"), ("observation", OBS[first_lot(9052)], "endpoint_b")])
# F
event("D", "identity", "identity.splink_base", ("identity", IDENT[9060]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9061]), score=0.9998, threshold=0.999, cluster=CL_ID["F"],
      support=[("observation", OBS[first_lot(9060)], "endpoint_a"), ("observation", OBS[first_lot(9061)], "endpoint_b")])
ADDR = "A9000001"
event("N", ON, "network.address", ("address", ADDR), "masked", "aggregator_address_mask", reason="aggregator_address_masked",
      detail={"degree": 4, "threshold": 3})
# G
event("D", "identity", "identity.splink_base", ("identity", IDENT[9070]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9071]), score=0.9996, threshold=0.999, cluster=CL_ID["G1"],
      support=[("observation", OBS[first_lot(9070)], "endpoint_a"), ("observation", OBS[first_lot(9071)], "endpoint_b")])
event("D", "identity", "identity.splink_base", ("identity", IDENT[9072]), "accepted", "splink_model",
      counterpart=("identity", IDENT[9073]), score=0.9996, threshold=0.999, cluster=CL_ID["G2"],
      support=[("observation", OBS[first_lot(9072)], "endpoint_a"), ("observation", OBS[first_lot(9073)], "endpoint_b")])

# --- deed evidence -------------------------------------------------------------------------------------------

D2, D4 = "2999020200003001", "2999030300004001"
item = lambda eid, stage, doc, n: add("evidence_items", evidence_id=eid, stage=stage, document_id=doc, parcel_count=n, rule_version=RV)
member = lambda eid, b, role, doc, latest, amt, why=None: add(
    "evidence_members", evidence_id=eid, bbl=b, node_id=LOT_NODE[b], role=role, original_document_id=doc,
    latest_document_id=latest, latest_amount=amt, excluded_reason=why)
item("DV9000001", "deed.linked_successor", D1, 4)
member("DV9000001", bbl(2, 1), "held_under_joint_deed", D1, D1, 1250000.0)
member("DV9000001", bbl(2, 2), "held_under_joint_deed", D1, D1, 1250000.0)
member("DV9000001", bbl(2, 3), "transferred_onward", D1, L3, 0.0)
member("DV9000001", bbl(2, 4), "transferred_onward", D1, L4, 0.0)
item("DV9000002", "deed.held_since", D2, 3)
member("DV9000002", bbl(3, 1), "held_under_joint_deed", D2, D2, 640000.0, "deed_hub_capped")
member("DV9000002", bbl(3, 3), "held_under_joint_deed", D2, D2, 640000.0)
member("DV9000002", bbl(3, 4), "held_under_joint_deed", D2, D2, 640000.0)
item("DV9000003", "deed.held_since", D4, 2)
member("DV9000003", bbl(7, 2), "held_under_joint_deed", D4, D4, 900000.0)
member("DV9000003", bbl(7, 3), "held_under_joint_deed", D4, D4, 900000.0)

# --- link sets --------------------------------------------------------------------------------------------------

add("link_sets", set_id="LG9000001", stage="identity.registered_llc", rule="registered_llc_owner_match", rule_version=RV, size=2)
add("link_set_members", set_id="LG9000001", node_id=9080, source_bbl=bbl(8, 1))
add("link_set_members", set_id="LG9000001", node_id=9081, source_bbl=bbl(8, 2))
add("link_sets", set_id="CG9000001", stage="identity.curated", rule="curated_owner_list", rule_version=RV, size=2)
add("link_set_members", set_id="CG9000001", node_id=9082, source_bbl=None)
add("link_set_members", set_id="CG9000001", node_id=9083, source_bbl=None)

# --- the network ----------------------------------------------------------------------------------------------------

EDGES = [  # id, a, b, name, address, identity
    ("NE9000001", 9060, 9061, 1.5, 0.0, 100.0), ("NE9000002", 9060, 9062, 1.5, 0.0, 0.0),
    ("NE9000003", 9061, 9062, 1.5, 1.0, 0.0), ("NE9000004", 9062, 9063, 1.5, 0.0, 0.0),
    ("NE9000005", 9063, 9064, 0.0, 2.0, 0.0), ("NE9000006", 9064, 9065, 1.5, 0.0, 0.0),
]
COMMUNITY = {9060: 0, 9061: 0, 9062: 0, 9063: 1, 9064: 1, 9065: 1}
NET = {9060: "ON-9060", 9061: "ON-9060", 9062: "ON-9060", 9063: "ON-9063", 9064: "ON-9063", 9065: "ON-9063"}
for eid, a, b, name, address, ident in EDGES:
    add("network_edges", edge_id=eid, component_id="NC-1", node_a=a, node_b=b, name_weight=name, address_weight=address,
        identity_weight=ident, weight=name + address + ident, crosses_networks=str(NET[a] != NET[b]))
for n, net in NET.items():
    add("network_membership", node_id=n, component_id="NC-1", community_id=COMMUNITY[n], operational_network_id=net)
add("split_attempts", split_id="SP9000001", component_id="NC-1", parent_community_id=None, level=0, outcome="split", communities=2)
add("masked_addresses", address_id=ADDR, method="network_address_edge_mask", normalizer_version="synthetic", degree=4,
    degree_unit="landlords (lwc nodes)", threshold=3, decision="masked")
for n in (9061, 9065, 9066, 9067):
    add("masked_address_nodes", address_id=ADDR, node_id=n)

# --- groups, members, lots, witness -------------------------------------------------------------------------------------

EDGE_STAGE = {e[0]: ("network.identity" if e[5] else "network.name" if e[3] else "network.address") for e in EDGES}
GROUPS = [  # layer, id, composition, split, nodes, witness steps (a, b, stage, basis_type, basis_id)
    (OP, "OP-9001", "identity", None, [9001, 9002, 9003, 9005], [
        (9001, 9002, "identity.splink_base", "identity_cluster", CL_ID["A"]),
        (9002, 9003, "identity.splink_feedback", "identity_cluster", CL_ID["A"]),
        (9003, 9005, "identity.splink_base", "identity_cluster", CL_ID["A"])]),
    (OP, "OP-9010", "deed_only", None, [9010, 9011, 9012], [
        (9010, 9011, "deed.linked_successor", "evidence_item", "DV9000001"),
        (9011, 9012, "deed.linked_successor", "evidence_item", "DV9000001")]),
    (OP, "OP-9030", "identity", None, [9030, 9031], [(9030, 9031, "identity.splink_base", "identity_cluster", CL_ID["C"])]),
    (OP, "OP-9032", "deed_only", None, [9032, 9033], [(9032, 9033, "deed.held_since", "evidence_item", "DV9000002")]),
    (OP, "OP-9050", "identity", None, [9050, 9051], [(9050, 9051, "identity.splink_base", "identity_cluster", CL_ID["Ea"])]),
    (OP, "OP-9060", "identity", None, [9060, 9061], [(9060, 9061, "identity.splink_base", "identity_cluster", CL_ID["F"])]),
    (OP, "OP-9070", "deed_bridged", None, [9070, 9071, 9072, 9073], [
        (9070, 9071, "identity.splink_base", "identity_cluster", CL_ID["G1"]),
        (9071, 9072, "deed.held_since", "evidence_item", "DV9000003"),
        (9072, 9073, "identity.splink_base", "identity_cluster", CL_ID["G2"])]),
    (OP, "OP-9080", "identity", None, [9080, 9081], [(9080, 9081, "identity.registered_llc", "link_set", "LG9000001")]),
    (OP, "OP-9082", "identity", None, [9082, 9083], [(9082, 9083, "identity.curated", "link_set", "CG9000001")]),
    (ON, "ON-9060", None, "louvain", [9060, 9061, 9062], [
        (9060, 9061, EDGE_STAGE["NE9000001"], "network_edge", "NE9000001"),
        (9061, 9062, EDGE_STAGE["NE9000003"], "network_edge", "NE9000003")]),
    (ON, "ON-9063", None, "louvain", [9063, 9064, 9065], [
        (9063, 9064, EDGE_STAGE["NE9000005"], "network_edge", "NE9000005"),
        (9064, 9065, EDGE_STAGE["NE9000006"], "network_edge", "NE9000006")]),
]
for layer, gid, comp, split, nodes, steps in GROUPS:
    key = f"{R}/{layer}/{gid}"
    lots = [b for n in nodes for b in NODES[n]]
    rental = [b for b in lots if b not in COOP]
    add("groups", layer=layer, group_id=gid, assertion_key=key, composition=comp, split=split, lot_count=len(rental),
        total_lot_count=len(lots), witness_pieces=1)
    for n in nodes:
        add("group_members", layer=layer, group_id=gid, node_id=n, assertion_key=f"{key}/n{n}")
    for b in lots:
        add("group_bbls", layer=layer, group_id=gid, bbl=b, rental=str(b not in COOP))
    for i, (a, b, stage, bt, bid) in enumerate(steps, 1):
        add("group_witness", layer=layer, group_id=gid, step=i, node_a=a, node_b=b, stage=stage, basis_type=bt,
            basis_id=bid, assertion_key=f"{key}/w{i}")

# --- assemble, then the absence summary from the real code ----------------------------------------------------------------------

frames = {}
for name, rows in T.items():
    cols = [c.name for c in TABLES[name].columns]
    if rows:
        frames[name] = pd.DataFrame(rows, columns=cols).astype(object).where(lambda d: d.notna(), None)
frames["decision_events"] = frames["decision_events"][EVENT_COLUMNS]
S = {k: v.astype(str).where(v.notna(), None) for k, v in frames.items()}
universe = [*LOT_NODE, U_NO_REGISTRATION, U_NO_CONTACT]
registered = [*LOT_NODE, U_NO_CONTACT]
status = absence.bbl_status_table(universe, registered, S)
frames["bbl_status"] = status.sort_values(["layer", "bbl"]).reset_index(drop=True)

METRICS = [  # not measurements: the shape of what a consumer displays
    dict(stage="identity.splink_base", metric="precision", unit="pair", population="synthetic", n=10, numerator=5,
         denominator=10, precision=0.5, ci_lower=0.25, ci_upper=0.75, confidence_level=0.95, interval_method="synthetic",
         estimator="synthetic", strata_ref=None, eval_artifact="synthetic", eval_version="synthetic-0",
         adjudication_status="synthetic", provisional="True", note="SYNTHETIC fixture value, not a measurement"),
    dict(stage="identity.splink_feedback", metric="precision", unit="pair", population=None, n=None, numerator=None,
         denominator=None, precision=None, ci_lower=None, ci_upper=None, confidence_level=None, interval_method=None,
         estimator=None, strata_ref=None, eval_artifact=None, eval_version=None, adjudication_status="none",
         provisional="True", note="synthetic fixture: unevaluated"),
]
frames["method_metrics"] = pd.DataFrame(METRICS, columns=[c.name for c in TABLES["method_metrics"].columns])

os.makedirs(D, exist_ok=True)
for stale in os.listdir(D):
    os.remove(os.path.join(D, stale))
for name, df in frames.items():
    df.to_csv(os.path.join(D, f"{name}.csv"), index=False)

manifest = {
    "schema_version": "0.1.0", "run_id": R, "snapshot_id": "synthetic-2026-10-22", "pluto_snapshot_id": "synthetic-pluto",
    "effective_date": "2026-10-22", "synthetic": True, "bor_revision": "fixture", "nlr_revision": "fixture",
    "source_tree_hash": "fixture", "dependency_lock_digest": "fixture", "threshold": 0.999,
    "parameters": {"splink_threshold": 0.999, "louvain_seed": 42, "max_address_degree": 3},
    "source_tables": {t: {"row_count": 0, "fingerprint": "synthetic", "fingerprint_method": "synthetic"}
                      for t in ("hpd_contacts", "hpd_registrations", "wow_landlords", "real_property_master", "pluto_latest")},
    "deed_selection_rule": {"rule": "doctype ILIKE '%DEED%'", "version": "fixture"},
    "normalizer_versions": {"business_address": "fixture", "owner_name": "fixture"},
    "artifacts": {"group_witness": "representative", "observations": "complete", "decision_events": "complete",
                  "network_edges": "complete"},
    "stage_vocabulary_version": "0.1.0", "reason_vocabulary_version": "0.1.0",
    "note": "Synthetic fixture for the release contract. Not real data: every BBL starts with 9 and no id is a real one.",
}
files = sorted(f for f in os.listdir(D) if f.endswith(".csv"))
manifest["output_checksums"] = {f: hashlib.sha256(open(os.path.join(D, f), "rb").read()).hexdigest() for f in files}
json.dump(manifest, open(os.path.join(D, "manifest.json"), "w"), indent=2)

from bor.release_validate import read_release                     # noqa: E402
tables, mf = read_release(D)
found = validate_release(tables, mf, path=D)
for v in found:
    print(v)
print(len(files), "tables;", sum(v.severity == "error" for v in found), "errors")
sys.exit(1 if any(v.severity == "error" for v in found) else 0)
