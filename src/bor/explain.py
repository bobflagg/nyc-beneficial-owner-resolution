"""Explain a release in plain language (W8): why is this lot in, or not in, a group?

    uv run python -m bor.explain ./release lot 3000010001
    uv run python -m bor.explain ./release pair 3000010001 3000010003
    uv run python -m bor.explain ./release group OP-1

Everything comes from the release tables; no database. Three questions:

* :func:`explain_lot` — is the lot in an Owner Portfolio and an Operational Network, and if not, the
  primary reason, every other reason that applies, and the facts behind them;
* :func:`explain_pair` — are two lots in one group? If so, the representative path between them, step
  by step, each step naming the evidence that joined its two nodes and how strong that kind is;
  if not, why, and (for the network) how the original connectivity runs across the boundary;
* :func:`explain_group` — what a group is made of and which kinds of evidence hold it together.

An explanation is a lead, not a finding. The path is *representative*: it is one connection that the
evidence supports, not the only, strongest or shortest one. Every group is derived by a method; none
is a determination of ownership.
"""
from __future__ import annotations

import json
import sys
from collections import deque
from dataclasses import dataclass, field

import pandas as pd

from bor import absence
from bor.release_schema import REASON_CODES
from bor.release_validate import read_release

LAYERS = ("owner_portfolio", "operational_network")
LAYER_NAME = {"owner_portfolio": "Owner Portfolio", "operational_network": "Operational Network"}

# How much weight a kind of evidence deserves, in plain words. The two weak stages are named in any
# path that needs them.
_STAGE_TEXT = {
    "identity.splink_base": "the same resolved person (a scored match between two HPD contacts)",
    "identity.splink_feedback": "a shared company (two otherwise separate resolved people with the same name "
                                "are bridged by a corporation on their buildings)",
    "identity.curated": "a hand-verified same-owner entry",
    "identity.registered_llc": "the same registered owner entity (DOF owner of record) on both",
    "deed.held_since": "a shared deed that is still each parcel's latest",
    "deed.linked_successor": "a shared deed whose parcel was later restructured into a single-purpose LLC "
                             "by the same grantee",
    "network.identity": "a resolved-owner link (as above)",
    "network.name": "a matching landlord name",
    "network.address": "a shared business address",
}
WEAK_STAGES = {
    "identity.splink_feedback": "the weakest identity evidence: a shared company, not a direct match",
    "deed.linked_successor": "the weakest deed evidence: it rests on a nominal-price restructuring",
    "network.address": "the weakest network evidence: a shared address can be an office many unrelated people use",
}
CAVEAT = ("This is a lead, not a determination of ownership. The groups are derived by a method whose "
          "precision is measured on a sample and is provisional; the path shown is one connection the "
          "evidence supports, not the only, strongest or shortest.")


@dataclass
class Explanation:
    """A structured answer with a plain-language rendering."""
    question: str
    answer: str
    details: list = field(default_factory=list)       # lines of supporting facts
    steps: list = field(default_factory=list)         # for a path: one dict per step
    weakest: list = field(default_factory=list)       # weak stages the answer depends on
    caveats: list = field(default_factory=lambda: [CAVEAT])
    data: dict = field(default_factory=dict)

    def render(self) -> str:
        out = [self.question, "  " + self.answer]
        out += ["  " + d for d in self.details]
        for i, s in enumerate(self.steps, 1):
            out.append(f"  {i}. {s['text']}")
            out += [f"       {x}" for x in s.get("evidence", [])]
        if self.weakest:
            out.append("  This depends on weak evidence: " + "; ".join(self.weakest) + ".")
        out += ["  Note: " + c for c in self.caveats]
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {"question": self.question, "answer": self.answer, "details": self.details, "steps": self.steps,
                "weakest": self.weakest, "caveats": self.caveats, "data": self.data}


class Release:
    """A release loaded for explaining. Tables are read as text (ids keep their form)."""

    def __init__(self, tables: dict, manifest: dict | None = None):
        self.t = tables
        self.manifest = manifest or {}
        self._node_lots = None

    @classmethod
    def from_dir(cls, path: str) -> "Release":
        tables, manifest = read_release(path)
        return cls(tables, manifest)

    def table(self, name) -> pd.DataFrame | None:
        return self.t.get(name)

    # ---- lookups
    def node_of(self, bbl: str):
        nobs = self.table("node_observations")
        if nobs is None:
            return None
        m = nobs[nobs["bbl"] == bbl]
        return None if m.empty else str(m.iloc[0]["node_id"])

    def lots_of(self, node: str) -> list[str]:
        nobs = self.table("node_observations")
        return sorted(nobs.loc[nobs["node_id"].astype(str) == node, "bbl"]) if nobs is not None else []

    def group_of_node(self, node: str, layer: str):
        gm = self.table("group_members")
        if gm is None:
            return None
        m = gm[(gm["layer"] == layer) & (gm["node_id"].astype(str) == node)]
        return None if m.empty else str(m.iloc[0]["group_id"])

    def group(self, group_id: str, layer: str):
        g = self.table("groups")
        m = g[(g["layer"] == layer) & (g["group_id"] == group_id)] if g is not None else None
        return None if m is None or m.empty else m.iloc[0]

    def node_label(self, node: str) -> str:
        """``lot 3000010001 (HPD registration 101, contact 10105)`` for a node, as far as the release says."""
        nobs = self.table("node_observations")
        m = nobs[nobs["node_id"].astype(str) == node] if nobs is not None else None
        if m is None or m.empty:
            return f"node {node}"
        r = m.iloc[0]
        more = f"; the node covers {len(m) - 1} more lot{'s' if len(m) > 2 else ''}" if len(m) > 1 else ""
        sel = r.get("selected_observation_id")
        if isinstance(sel, str) and sel:
            reg, contact, _ = sel.split(":")
            return f"lot {r['bbl']} (HPD registration {reg}, contact {contact}{more})"
        return f"lot {r['bbl']} (HPD registration {r['registration_id']}, contact not unique{more})"


def _desc(code: str) -> str:
    return REASON_CODES[code][1].rstrip(".")


def _describe_event(row) -> str:
    """One decision event as a sentence: the rule, what it did to what, and the numbers."""
    what = f"{row['subject_type']} {row['subject_id']}"
    if isinstance(row.get("counterpart_id"), str) and row["counterpart_id"]:
        what += f" against {row['counterpart_type']} {row['counterpart_id']}"
    num = ""
    if isinstance(row.get("score"), str) and row["score"]:
        num = f" (score {float(row['score']):.4f}"
        if isinstance(row.get("threshold"), str) and row["threshold"]:
            num += f" vs threshold {float(row['threshold']):g}"
        num += ")"
    extra = ""
    if isinstance(row.get("detail"), str) and row["detail"]:
        try:
            d = json.loads(row["detail"])
        except ValueError:
            d = {}
        words = []
        for k, v in sorted(d.items()):
            if k == "latest_amount":
                words.append(f"the onward deed was for ${float(v):,.0f}")
            elif k == "n_parcels":
                words.append(f"{v} parcels")
            elif k == "n_shared_corporations":
                words.append(f"{v} shared corporation(s)")
            elif k == "addr_degree":
                words.append(f"the address is shared by {v} landlords")
            elif k == "degree" or k == "hub_cap":
                words.append(f"{k.replace('_', ' ')} {v}")
            else:
                words.append(f"{k.replace('_', ' ')} {v}")
        extra = " [" + "; ".join(words) + "]" if words else ""
    return f"rule {row['rule']} {row['outcome']} {what}{num}{extra}"


# ---- steps ------------------------------------------------------------------------------------

def _explain_step(rel: Release, s: dict) -> dict:
    a, b, stage, btype, bid = str(s["node_a"]), str(s["node_b"]), s["stage"], s["basis_type"], s["basis_id"]
    ev: list[str] = []
    text = f"{rel.node_label(a)} is tied to {rel.node_label(b)} by {_STAGE_TEXT.get(stage, stage)}."
    de, sup = rel.table("decision_events"), rel.table("decision_support")

    if btype == "identity_cluster" and de is not None:
        d = de[(de["cluster_id"] == bid) & (de["outcome"] == "accepted") & (de["stage"] == stage)]
        if stage == "identity.splink_base":
            sc = pd.to_numeric(d["score"], errors="coerce").dropna()
            if len(sc):
                ev.append(f"{len(sc)} accepted match decision(s) in cluster {bid}; scores {sc.min():.4f} to {sc.max():.4f}"
                          f" (threshold {d.iloc[0]['threshold']}).")
        else:
            ev.append(f"{len(d)} accepted shared-company merge(s) in cluster {bid}; no direct score links the two sides.")
            if sup is not None and len(d):
                contacts = sorted(set(sup[sup["decision_id"].isin(d["decision_id"]) & (sup["support_type"] == "observation")]["support_id"]))
                if contacts:
                    ev.append("The company appears on HPD contacts " + ", ".join(contacts[:6]) +
                              (f" and {len(contacts) - 6} more" if len(contacts) > 6 else "") + ".")
    elif btype == "link_set":
        ls, lm = rel.table("link_sets"), rel.table("link_set_members")
        if ls is not None and lm is not None:
            row = ls[ls["set_id"] == bid]
            if len(row):
                ev.append(f"Link set {bid} ({row.iloc[0]['rule']}, {row.iloc[0]['size']} nodes).")
            for n in (a, b):
                lots = sorted(x for x in lm[(lm["set_id"] == bid) & (lm["node_id"].astype(str) == n)]["source_bbl"].dropna())
                if lots:
                    ev.append(f"Node {n} is in the set through PLUTO lot(s) {', '.join(lots)} owned by that entity.")
    elif btype == "evidence_item":
        items, mem = rel.table("evidence_items"), rel.table("evidence_members")
        if items is not None and mem is not None:
            it = items[items["evidence_id"] == bid]
            if len(it):
                ev.append(f"ACRIS deed {it.iloc[0]['document_id']} ({it.iloc[0]['stage']}).")
            for n in (a, b):
                for r in mem[(mem["evidence_id"] == bid) & (mem["node_id"].astype(str) == n)].itertuples():
                    if r.role == "held_under_joint_deed":
                        ev.append(f"Lot {r.bbl}: the joint deed is still its latest.")
                    else:
                        amt = f" for ${float(r.latest_amount):,.0f}" if pd.notna(r.latest_amount) and r.latest_amount != "" else ""
                        ev.append(f"Lot {r.bbl}: conveyed on by deed {r.latest_document_id}{amt}.")
    elif btype == "network_edge":
        e = rel.table("network_edges")
        if e is not None:
            r = e[e["edge_id"] == bid]
            if len(r):
                r = r.iloc[0]
                parts = [f"{k} {float(r[c]):g}" for k, c in (("identity", "identity_weight"), ("name", "name_weight"),
                                                              ("address", "address_weight")) if float(r[c]) > 0]
                ev.append(f"Edge {bid}: " + ", ".join(parts) + f" (total weight {float(r['weight']):g}).")
    return {"node_a": a, "node_b": b, "stage": stage, "basis_type": btype, "basis_id": bid,
            "text": text, "evidence": ev, "weak": stage in WEAK_STAGES}


def _tree_path(steps: pd.DataFrame, a: str, b: str):
    """The unique path between two nodes through a group's witness tree (or forest), as the steps in order."""
    adj: dict[str, list] = {}
    for s in steps.to_dict("records"):
        adj.setdefault(str(s["node_a"]), []).append((str(s["node_b"]), s))
        adj.setdefault(str(s["node_b"]), []).append((str(s["node_a"]), s))
    prev, q = {a: None}, deque([a])
    while q and b not in prev:
        u = q.popleft()
        for v, s in adj.get(u, []):
            if v not in prev:
                prev[v] = (u, s)
                q.append(v)
    if b not in prev:
        return None
    path, n = [], b
    while prev[n] is not None:
        u, s = prev[n]
        path.append((u, n, s))
        n = u
    return list(reversed(path))


def _published(rel: Release, stage: str) -> str:
    """The stage's published strict precision as stored in ``method_metrics`` (never recomputed), or ''."""
    m = rel.table("method_metrics")
    if m is None:
        return ""
    r = m[(m["stage"] == stage) & (m["metric"] == "precision_strict") & m["precision"].notna()]
    if r.empty:
        return ""
    r = r.iloc[0]
    prov = "provisional" if str(r["provisional"]) == "True" else "final"
    return (f"; published strict precision {float(r['precision']):.2f} (95% interval {float(r['ci_lower']):.2f} to "
            f"{float(r['ci_upper']):.2f}; {r['numerator']} of {r['denominator']} sampled pairs; {prov}; a share of "
            "sampled pairs, not the chance this link is right)")


def _weak_list(steps: list[dict], rel: Release | None = None) -> list[str]:
    seen, out = set(), []
    for s in steps:
        if s["weak"] and s["stage"] not in seen:
            seen.add(s["stage"])
            out.append(f"{s['stage']} ({WEAK_STAGES[s['stage']]}" + (_published(rel, s["stage"]) if rel else "") + ")")
    return out


# ---- the three questions -----------------------------------------------------------------------

def explain_lot(rel: Release, bbl: str, layer: str | None = None) -> Explanation:
    """Is the lot in an Owner Portfolio / Operational Network, and if not, why."""
    layers = [layer] if layer else list(LAYERS)
    out = Explanation(f"Lot {bbl}: is it in a group, and why or why not?", "")
    s = rel.table("bbl_status")
    answers, details = [], []
    node = rel.node_of(bbl)
    if node:
        details.append(f"It belongs to node {node}: {rel.node_label(node)}.")
    else:
        details.append("It is not in any node (no qualifying HPD owner contact was used for it).")
    ranks = absence.lot_event_ranks(rel.t) if rel.table("decision_events") is not None else None
    for lay in layers:
        nm = LAYER_NAME[lay]
        row = None if s is None else s[(s["layer"] == lay) & (s["bbl"] == bbl)]
        if row is None or row.empty:
            answers.append(f"{nm}: the release has no row for this lot (it is outside the snapshot and in no node).")
            continue
        r = row.iloc[0]
        status, gid, code = r["status"], r["group_id"], r["reason_code"]
        if status == "in_group":
            g = rel.group(gid, lay)
            size = f"{g['lot_count']} lots" if g is not None else "a group"
            answers.append(f"{nm}: in {gid} ({size}).")
        elif status == "excluded_from_footprint":
            answers.append(f"{nm}: a member of {gid} but left out of its rental footprint ({_desc(code)}).")
        else:
            top = REASON_CODES[code][0]
            answers.append(f"{nm}: not in a group. Primary reason: {code}, {_desc(code)} "
                           f"[{top.replace('_', ' ')}].")
            others = []
            if ranks is not None and len(ranks):
                mine = ranks[(ranks["layer"] == lay) & (ranks["bbl"] == bbl)]
                others = sorted({absence._CODE_OF[x] for x in mine["score"]} - {code})
            if others:
                details.append(f"{nm}: other reasons that also apply: " + ", ".join(others) + ".")
            de = rel.table("decision_events")
            if ranks is not None and len(ranks) and de is not None:
                mine = ranks[(ranks["layer"] == lay) & (ranks["bbl"] == bbl) & (ranks["score"] == absence._SCORE[code])]
                for did in sorted(set(mine["decision_id"]))[:3]:
                    details.append(f"{nm}: event {did}: " + _describe_event(de[de["decision_id"] == did].iloc[0]) + ".")
        out.data[lay] = {"status": status, "group_id": None if pd.isna(gid) else gid,
                         "reason_code": None if pd.isna(code) else code}
    out.answer = answers[0]
    out.details = answers[1:] + details
    if status_has_gate(out.data):
        out.details.append("This is a rule the method applied on purpose; the events behind it are in decision_events. "
                           "Absence from a group is never evidence that the owners differ.")
    return out


def status_has_gate(data: dict) -> bool:
    return any(d.get("reason_code") and REASON_CODES[d["reason_code"]][0] in ("excluded_by_policy", "below_eligibility_rule")
               for d in data.values())


def explain_pair(rel: Release, bbl_a: str, bbl_b: str, layer: str = "owner_portfolio") -> Explanation:
    """Are two lots in one group, and if so, the representative path between them."""
    nm = LAYER_NAME[layer]
    out = Explanation(f"Lots {bbl_a} and {bbl_b}: are they in the same {nm}, and why?", "")
    na, nb = rel.node_of(bbl_a), rel.node_of(bbl_b)
    missing = [b for b, n in ((bbl_a, na), (bbl_b, nb)) if n is None]
    if missing:
        out.answer = ("Not connected: " + ", ".join(missing) + " is in no node, so this method has no evidence for it. "
                      "See `lot` for the reason.")
        return out
    ga, gb = rel.group_of_node(na, layer), rel.group_of_node(nb, layer)
    out.data = {"layer": layer, "node_a": na, "node_b": nb, "group_a": ga, "group_b": gb}
    if ga and ga == gb:
        if na == nb:
            out.answer = f"Yes: both lots are in the same node ({na}), in {nm} {ga}."
            return out
        w = rel.table("group_witness")
        path = _tree_path(w[(w["layer"] == layer) & (w["group_id"] == ga)], na, nb) if w is not None else None
        if path is None:
            out.answer = (f"Both are in {nm} {ga}, but this group's path does not connect their nodes within its own "
                          f"edges (it is a forest; see `group {ga}`).")
            return out
        steps = [_explain_step(rel, s) | {"directed": (u, v)} for u, v, s in path]
        out.steps = steps
        out.weakest = _weak_list(steps, rel)
        out.answer = f"Yes: both are in {nm} {ga}, joined by a path of {len(steps)} step{'s' if len(steps) != 1 else ''}."
        return out
    # not in one group
    parts = []
    for b, g in ((bbl_a, ga), (bbl_b, gb)):
        parts.append(f"{b} is in {g}" if g else f"{b} is in no {nm}")
    out.answer = f"No: {parts[0]} and {parts[1]}."
    if layer == "operational_network" and ga and gb:
        out.details += _network_boundary(rel, na, nb)
    elif not ga or not gb:
        out.details.append("See `lot` for why a lot is not in a group.")
    if layer == "owner_portfolio":
        out.details += _near_misses(rel, na, nb)
    return out


def _near_misses(rel: Release, na: str, nb: str) -> list[str]:
    """What the release holds that bears on two nodes that are not in one Owner Portfolio: a decision
    between their identities that a gate did not accept, a deed they share that did not link them, and
    another reading of a node whose registration lists several contacts."""
    out: list[str] = []
    nim, ic, de = rel.table("node_identity_matches"), rel.table("identity_clusters"), rel.table("decision_events")
    if nim is not None and de is not None:
        def entities(n):
            ids = set(nim.loc[nim["node_id"].astype(str) == n, "identity_id"])
            if ic is not None and "base_cluster_id" in ic.columns:
                ids |= set(ic.loc[ic["identity_id"].isin(ids), "base_cluster_id"].dropna())
            return ids
        ea, eb = entities(na), entities(nb)
        hit = de[(de["outcome"] != "accepted")
                 & ((de["subject_id"].isin(ea) & de["counterpart_id"].isin(eb))
                    | (de["subject_id"].isin(eb) & de["counterpart_id"].isin(ea)))]
        for _, r in hit.iterrows():
            out.append(f"Closest evidence: a decision between them was not accepted: {_describe_event(r)} "
                       f"({_desc(r['reason_code'])}).")
    items, mem = rel.table("evidence_items"), rel.table("evidence_members")
    if items is not None and mem is not None:
        node = mem["node_id"].astype(str)
        for eid in sorted(set(mem.loc[node == na, "evidence_id"]) & set(mem.loc[node == nb, "evidence_id"])):
            doc = items.loc[items["evidence_id"] == eid, "document_id"].iloc[0]
            for r in mem[(mem["evidence_id"] == eid) & node.isin([na, nb]) & mem["excluded_reason"].notna()].itertuples():
                why = _desc(r.excluded_reason) if r.excluded_reason in REASON_CODES else r.excluded_reason
                out.append(f"Closest evidence: they share ACRIS deed {doc}, but it did not link them: "
                           f"the node of lot {r.bbl} was left out of every deed link ({why}).")
    ncl, nca, nobs = rel.table("node_cluster"), rel.table("node_cluster_alternatives"), rel.table("node_observations")
    if ncl is not None and nca is not None:
        chosen = dict(zip(ncl["node_id"].astype(str), ncl["cluster_id"]))
        for x, y in ((na, nb), (nb, na)):
            alt = nca[nca["node_id"].astype(str) == x]
            other = chosen.get(y)
            if other and other != chosen.get(x) and other in set(alt["cluster_id"]):
                votes = dict(zip(alt["cluster_id"], alt["votes"]))
                tie = ncl.loc[ncl["node_id"].astype(str) == x, "tied"].iloc[0] == "True"
                ambiguous = nobs is not None and (nobs.loc[nobs["node_id"].astype(str) == x, "ambiguous"] == "True").any()
                out.append(f"Closest evidence: {rel.node_label(x)} has more than one reading"
                           + (" (its registration lists several contacts and the release cannot say which is the owner)"
                              if ambiguous else "") + f". The method kept cluster {chosen[x]}; cluster {other}, which holds "
                           f"{rel.node_label(y)}, had {votes[other]} vote(s) against {votes[chosen[x]]}"
                           + (" and the tie was broken by a fixed rule." if tie else "."))
    return out


def _network_boundary(rel: Release, na: str, nb: str) -> list[str]:
    """For two nodes in different Operational Networks: whether they are in one original component, and
    the path between them in the complete edge table with the boundary marked."""
    mem, e = rel.table("network_membership"), rel.table("network_edges")
    if mem is None or e is None:
        return []
    info = mem.set_index(mem["node_id"].astype(str))
    ca, cb = info.loc[na, "component_id"], info.loc[nb, "component_id"]
    if ca != cb:
        return [f"They are in different original components ({ca}, {cb}): no name, address or identity edge connects them."]
    adj: dict[str, list] = {}
    for r in e.itertuples():
        adj.setdefault(str(r.node_a), []).append((str(r.node_b), r))
        adj.setdefault(str(r.node_b), []).append((str(r.node_a), r))
    prev, q = {na: None}, deque([na])
    while q and nb not in prev:
        u = q.popleft()
        for v, r in adj.get(u, []):
            if v not in prev:
                prev[v] = (u, r)
                q.append(v)
    path, n = [], nb
    while prev.get(n) is not None:
        u, r = prev[n]
        path.append((u, n, r))
        n = u
    crossing = [r.edge_id for _, _, r in path if str(r.crosses_networks) == "True"]
    return [f"They are in one original component ({ca}) that Louvain cut into several networks. The edges still connect "
            f"them in {len(path)} step(s), {len(crossing)} of which cross a network boundary ({', '.join(crossing)})."]


def explain_group(rel: Release, group_id: str, layer: str | None = None) -> Explanation:
    """What a group is made of and which kinds of evidence hold it together."""
    g = rel.table("groups")
    cand = g[g["group_id"] == group_id] if g is not None else None
    if cand is None or cand.empty:
        return Explanation(f"Group {group_id}", "Not in this release (it may have been dropped; see decision_events).")
    r = cand.iloc[0]
    lay = r["layer"]
    nm = LAYER_NAME[lay]
    gm, gb, w = rel.table("group_members"), rel.table("group_bbls"), rel.table("group_witness")
    nodes = sorted(gm[(gm["layer"] == lay) & (gm["group_id"] == group_id)]["node_id"].astype(str), key=int)
    lots = gb[(gb["layer"] == lay) & (gb["group_id"] == group_id)]
    out = Explanation(f"{nm} {group_id}: what is it made of?",
                      f"{len(nodes)} nodes covering {len(lots)} lots ({r['lot_count']} in the rental footprint).")
    if pd.notna(r["composition"]) and r["composition"]:
        out.details.append(f"Composition: {r['composition']} (identity: one resolved owner; deed_only: held together by "
                           "deeds alone; deed_bridged: a deed joins several resolved owners).")
    if pd.notna(r["split"]) and r["split"]:
        out.details.append(f"Cut out by: {r['split']}" + (" (a whole connected component)" if r["split"] == "wcc"
                                                          else " (a Louvain community of a larger component)") + ".")
    steps = [_explain_step(rel, s) for s in w[(w["layer"] == lay) & (w["group_id"] == group_id)].sort_values("step", key=pd.to_numeric).to_dict("records")]
    by = pd.Series([s["stage"] for s in steps]).value_counts() if steps else pd.Series(dtype=int)
    out.details.append("Its path uses: " + (", ".join(f"{n} × {k}" for k, n in by.items()) or "no steps (a single node)") + ".")
    out.weakest = _weak_list(steps, rel)
    pieces = pd.to_numeric(r.get("witness_pieces"), errors="coerce")
    if pd.notna(pieces) and int(pieces) > 1:
        out.details.append(f"Its own edges leave {r['witness_pieces']} separate pieces; the connection between them runs "
                           "through other networks (see `pair`).")
    out.data = {"layer": lay, "nodes": nodes, "lots": len(lots), "stages": {k: int(v) for k, v in by.items()}}
    return out


# ---- command line ------------------------------------------------------------------------------

def main(argv=None) -> None:  # pragma: no cover - thin wrapper
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if len(argv) < 3 or argv[1] not in ("lot", "pair", "group"):
        sys.exit("usage: python -m bor.explain <release_dir> (lot <bbl> | pair <bbl> <bbl> [layer] | group <id>) [--json]")
    rel = Release.from_dir(argv[0])
    cmd = argv[1]
    if cmd == "lot":
        e = explain_lot(rel, argv[2], argv[3] if len(argv) > 3 else None)
    elif cmd == "pair":
        e = explain_pair(rel, argv[2], argv[3], argv[4] if len(argv) > 4 else "owner_portfolio")
    else:
        e = explain_group(rel, argv[2])
    print(json.dumps(e.to_dict(), indent=2) if as_json else e.render())


if __name__ == "__main__":
    main()
