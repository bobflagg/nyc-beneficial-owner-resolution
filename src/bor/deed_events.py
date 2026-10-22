"""Deed-layer release tables from the trace of :func:`bor.deed_edges.deed_edges`.

The deed code filters candidate deeds in SQL and in Python, then unions its two paths before mapping
to nodes. With ``trace`` it keeps what it dropped and why; this module turns that into the release
contract (docs/release-contract.md):

* ``evidence_items`` / ``evidence_members`` — each deed that links two or more landlord nodes, with a
  row per parcel saying whether it is still **held** under the joint deed or was **transferred
  onward** by the same grantee into a single-purpose LLC (the linked-successor guard), the parcel's
  latest deed and its recorded consideration. A deed is ``deed.linked_successor`` if any member
  depends on that guard, else ``deed.held_since``; the per-member role is the truth either way.
* ``decision_events`` (layer ``owner_portfolio``) — what a gate blocked: a deed-level screen (parcel
  count, institutional party, co-op/condo majority), a parcel the linked-successor guard rejected
  (conveyed on to someone else, successor not a shell, onward transfer not nominal), and a node left
  out of every clique by the hub cap. ``decision_support`` cites the ACRIS documents.

**Only decisions that could have changed a link are recorded.** A deed whose parcels all belong to
one landlord node would link nothing whether it passed or not, so its gates are not events.
"""
from __future__ import annotations

import json

import pandas as pd

from bor.identity_events import EVENT_COLUMNS, SUPPORT_COLUMNS
from bor.release_schema import REASON_CODES

LAYER = "owner_portfolio"

# reason -> (rule, outcome). A policy exclusion is `excluded`; a failed eligibility rule `rejected`.
_DEED_SCREEN = {
    "deed_parcels_out_of_range": ("deed_size_range", "rejected"),
    "institutional_screen": ("institutional_screen", "excluded"),
    "coop_condo_dominated": ("coop_condo_deed_rule", "excluded"),
}
_PARCEL_RULE = {
    "deed_not_latest": "deed_latest_rule",
    "successor_not_shell": "deed_successor_guard",
    "successor_transfer_not_nominal": "deed_successor_guard",
}
ITEM_COLUMNS = ["evidence_id", "stage", "document_id", "parcel_count", "rule_version"]
MEMBER_COLUMNS = ["evidence_id", "bbl", "node_id", "role", "original_document_id", "latest_document_id",
                  "latest_amount", "excluded_reason"]


def _num(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


def doc_amounts(conn, docs) -> dict:
    """Recorded consideration (``docamount``) of each document, for the held deeds."""
    docs = sorted(set(docs))
    if not docs:
        return {}
    cur = conn.cursor()
    cur.execute("SELECT documentid, docamount FROM real_property_master WHERE documentid = ANY(%s)", (docs,))
    return {str(d): _num(a) for d, a in cur.fetchall()}


def _nodes(bbls, bbl_nodes) -> set:
    return {bbl_nodes[b] for b in bbls if b in bbl_nodes}


def evidence_tables(trace: dict, amounts: dict, rule_version: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """``(evidence_items, evidence_members, report)`` for every deed that links two or more nodes."""
    groups, bbl_nodes, hubs = trace["groups"], trace["bbl_nodes"], trace["hubs"]
    held = {d: set(b) for d, b in zip(trace["held"]["doc"], trace["held"]["bbls"])}
    by_doc = {d: g for d, g in trace["parcels"].groupby("doc")}

    items, members, dropped_no_node = [], [], 0
    for i, doc in enumerate(sorted(groups), 1):
        eid = f"DV{i:07d}"
        rows = {}                                    # bbl -> (role, latest_doc, latest_amount)
        p = by_doc.get(doc)
        if p is not None:
            for r in p.itertuples():
                if r.outcome == "held":
                    rows[r.bbl] = ("held_under_joint_deed", doc, _num(r.latest_amount))
                elif r.outcome == "restructured":
                    rows[r.bbl] = ("transferred_onward", r.latest_doc, _num(r.latest_amount))
        for b in held.get(doc, ()):                  # held-since parcels: the joint deed is the latest
            rows[b] = ("held_under_joint_deed", doc, amounts.get(doc))
        kept = [(b, v) for b, v in sorted(rows.items()) if b in bbl_nodes]
        dropped_no_node += len(rows) - len(kept)
        for b, (role, ldoc, amt) in kept:
            node = bbl_nodes[b]
            members.append((eid, b, node, role, doc, ldoc, amt,
                            "deed_hub_capped" if node in hubs else None))
        stage = ("deed.linked_successor" if any(v[0] == "transferred_onward" for _, v in kept)
                 else "deed.held_since")
        items.append((eid, stage, doc, len(kept), rule_version))
    return (pd.DataFrame(items, columns=ITEM_COLUMNS), pd.DataFrame(members, columns=MEMBER_COLUMNS),
            {"parcels_without_a_node": dropped_no_node})


def _detail(**kv) -> str | None:
    kv = {k: v for k, v in kv.items() if v is not None}
    return json.dumps(kv, sort_keys=True) if kv else None


def event_tables(trace: dict, rule_version: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(decision_events, decision_support)`` for the deed gates that could have changed a link."""
    bbl_nodes, hubs, cap = trace["bbl_nodes"], trace["hubs"], trace["hub_cap"]
    rows, support = [], []

    def add(**kw):
        row = dict.fromkeys(EVENT_COLUMNS)
        row.update(layer=LAYER, rule_version=rule_version, **kw)
        rows.append(row)
        return len(rows) - 1

    # Deed-level screens: only for deeds whose parcels would have linked two or more nodes.
    for key, stage in (("screens_held", "deed.held_since"), ("screens_joint", "deed.linked_successor")):
        for r in trace[key].itertuples():
            if len(_nodes(r.bbls, bbl_nodes)) < 2:
                continue
            rule, outcome = _DEED_SCREEN[r.reason]
            k = add(stage=stage, subject_type="deed_document", subject_id=r.doc, outcome=outcome,
                    reason_code=r.reason, rule=rule,
                    detail=_detail(n_parcels=int(r.n_parcels), screen=r.screen))
            support.append((k, "document", r.doc, "deed"))
            support += [(k, "bbl", b, "parcel") for b in sorted(set(r.bbls)) if b in bbl_nodes]

    # Parcel-level linked-successor outcomes: a rejected parcel of a deed that could have linked nodes.
    parcels = trace["parcels"]
    reach = {d: len(_nodes(g["bbl"], bbl_nodes)) for d, g in parcels.groupby("doc")}
    for r in parcels[parcels["outcome"] == "rejected"].itertuples():
        if reach.get(r.doc, 0) < 2 or r.bbl not in bbl_nodes:
            continue
        k = add(stage="deed.linked_successor", subject_type="parcel", subject_id=r.bbl,
                counterpart_type="deed_document", counterpart_id=r.doc, outcome="rejected",
                reason_code=r.reason, rule=_PARCEL_RULE[r.reason],
                detail=_detail(latest_amount=_num(r.latest_amount)))
        support.append((k, "document", r.doc, "joint_deed"))
        support.append((k, "document", r.latest_doc, "latest_deed"))

    # Hub nodes: left out of every deed clique.
    for node, n in sorted(hubs.items()):
        add(stage="deed.group", subject_type="node", subject_id=str(node), outcome="excluded",
            reason_code="deed_hub_capped", rule="deed_hub_cap", detail=_detail(deeds=n, hub_cap=cap))

    events = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    order = events.sort_values(["stage", "subject_type", "subject_id", "counterpart_id", "reason_code"],
                               na_position="first", kind="stable").index
    new_id = {int(old): f"E{i:07d}" for i, old in enumerate(order, 1)}
    events = events.loc[order].reset_index(drop=True)
    events["decision_id"] = [f"E{i:07d}" for i in range(1, len(events) + 1)]
    sup = pd.DataFrame([(new_id[k], t, s, role) for k, t, s, role in support], columns=SUPPORT_COLUMNS)
    sup = sup.drop_duplicates().sort_values(SUPPORT_COLUMNS).reset_index(drop=True)
    return events, sup


def deed_tables(conn, trace: dict, rule_version: str) -> tuple[dict, dict]:
    """The deed-layer tables and a report, from a trace filled by ``deed_edges(..., trace=trace)``."""
    amounts = doc_amounts(conn, trace["held"]["doc"])
    items, members, report = evidence_tables(trace, amounts, rule_version)
    events, support = event_tables(trace, rule_version)
    report.update({
        "deed_evidence_items": len(items),
        "deed_items_linked_successor": int((items["stage"] == "deed.linked_successor").sum()),
        "deed_evidence_members": len(members),
        "deed_events_by_reason": {k: int(v) for k, v in events.groupby("reason_code").size().items()},
        "held_trace_matches_sql": bool(trace.get("held_consistent")),
        "joint_trace_matches_sql": bool(trace.get("joint_consistent")),
    })
    assert set(events["reason_code"]) <= set(REASON_CODES)
    return {"evidence_items": items, "evidence_members": members,
            "deed_events": events, "deed_support": support}, report
