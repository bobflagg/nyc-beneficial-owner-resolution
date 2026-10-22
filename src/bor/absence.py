"""Why is this lot not in a group? The per-lot absence summary (``bbl_status``), W6.

A lot has one status per layer:

* ``in_group`` — in a group's rental footprint;
* ``excluded_from_footprint`` — in a group, but a co-op or condo left out of its rental footprint;
* ``not_in_group`` — with a reason.

The reason is the **primary** one: of everything that applies to the lot, the reason from the earliest
stage that removed it (``PRECEDENCE``: outside source coverage, outside method input, excluded by
policy, below an eligibility rule, no qualifying linkage; ties inside a level follow the order of
``REASON_CODES``). Two kinds of thing apply to a lot:

* facts about the source: no HPD registration, no qualifying owner contact, a node the identity
  resolution could not match;
* the lot's own ``decision_events``, found by :func:`lot_event_ranks` — the single rule for tying an
  event to lots, shared with the validator so the summary and its check cannot drift apart.

The summary is a *summary*: the detail, with every reason that applies, stays in ``decision_events``.
It describes what the pipeline decided; it never establishes that no real relationship exists.
"""
from __future__ import annotations

import pandas as pd

from bor.release_schema import PRECEDENCE, REASON_CODES

LAYERS = ("owner_portfolio", "operational_network")
RANK = {code: (PRECEDENCE.index(top), i) for i, (code, (top, _)) in enumerate(REASON_CODES.items())}
_ORDER = sorted(RANK, key=RANK.get)
_SCORE = {code: i for i, code in enumerate(_ORDER)}          # one integer per reason, in precedence order
_CODE_OF = {i: code for code, i in _SCORE.items()}
STATUS_COLUMNS = ["layer", "bbl", "status", "group_id", "reason_code", "top_level_reason"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["decision_id", "layer", "bbl", "score"])


def lot_event_ranks(T: dict) -> pd.DataFrame:
    """Every non-accepted event with a reason, tied to the lots it bears on, as
    ``[decision_id, layer, bbl, score]`` (``score`` orders reasons by precedence, lower first).

    An event bears on a lot when it names it directly (a ``bbl`` or ``parcel``), names a node, an
    identity, a base cluster, a masked address or a published group that contains it, or (a deed-level
    screen) cites it as a parcel in ``decision_support``. Events of layer ``identity`` bear on both
    layers."""
    de, nobs = T.get("decision_events"), T.get("node_observations")
    if de is None or nobs is None:
        return _empty()
    ev = de[(de["outcome"] != "accepted") & de["reason_code"].notna()]
    if ev.empty:
        return _empty()
    refs = []
    for side in ("subject", "counterpart"):
        r = ev[["decision_id", "layer", "reason_code", f"{side}_type", f"{side}_id"]].dropna(subset=[f"{side}_id"])
        refs.append(r.rename(columns={f"{side}_type": "ref_type", f"{side}_id": "ref_id"}))
    refs = pd.concat(refs, ignore_index=True)
    refs["ref_id"] = refs["ref_id"].astype(str)
    refs["score"] = refs["reason_code"].map(_SCORE)

    def lots(kind, mapping):
        r = refs[refs["ref_type"] == kind].merge(mapping, on="ref_id")
        return r[["decision_id", "layer", "bbl", "score"]]

    s = lambda x: x.astype(str)
    parts = [refs[refs["ref_type"].isin(["bbl", "parcel"])].rename(columns={"ref_id": "bbl"})
             [["decision_id", "layer", "bbl", "score"]],
             lots("node", pd.DataFrame({"ref_id": s(nobs["node_id"]), "bbl": s(nobs["bbl"])}))]
    nim, ic = T.get("node_identity_matches"), T.get("identity_clusters")
    if nim is not None:
        ident = pd.DataFrame({"ref_id": s(nim["identity_id"]), "bbl": s(nim["bbl"])})
        parts.append(lots("identity", ident))
        if ic is not None and "base_cluster_id" in ic.columns:
            base = ic[["identity_id", "base_cluster_id"]].merge(nim[["identity_id", "bbl"]], on="identity_id")
            parts.append(lots("base_cluster", pd.DataFrame({"ref_id": s(base["base_cluster_id"]), "bbl": s(base["bbl"])})))
    gb = T.get("group_bbls")
    if gb is not None:
        parts.append(lots("group", pd.DataFrame({"ref_id": s(gb["group_id"]), "bbl": s(gb["bbl"])})))
    man = T.get("masked_address_nodes")
    if man is not None:
        by_node = pd.DataFrame({"node_id": s(nobs["node_id"]), "bbl": s(nobs["bbl"])})
        mm = man.assign(node_id=s(man["node_id"])).merge(by_node, on="node_id")
        parts.append(lots("address", pd.DataFrame({"ref_id": s(mm["address_id"]), "bbl": mm["bbl"]})))
    sup = T.get("decision_support")
    if sup is not None:
        parcels = sup[sup["support_type"] == "bbl"][["decision_id", "support_id"]].rename(columns={"support_id": "bbl"})
        d = refs[refs["ref_type"] == "deed_document"].drop_duplicates("decision_id").merge(parcels, on="decision_id")
        parts.append(d[["decision_id", "layer", "bbl", "score"]])
    out = pd.concat(parts, ignore_index=True)
    ident_ev = out[out["layer"] == "identity"]
    both = pd.concat([out[out["layer"] != "identity"]] + [ident_ev.assign(layer=l) for l in LAYERS], ignore_index=True)
    return both.drop_duplicates()


def _top(code):
    return REASON_CODES[code][0] if code in REASON_CODES else pd.NA


def bbl_status_table(universe, registered, T: dict) -> pd.DataFrame:
    """One row per (layer, lot) over ``universe`` plus every lot that is in a node or a group.

    ``registered``: lots with an HPD registration. ``T``: the release tables (node_observations,
    node_cluster, group_bbls, decision_events and the rest that :func:`lot_event_ranks` reads)."""
    nobs, ncl, gb = T["node_observations"], T["node_cluster"], T["group_bbls"]
    in_lwc = set(nobs["bbl"].astype(str))
    matched_nodes = set(ncl["node_id"].astype(str))
    node_of = dict(zip(nobs["bbl"].astype(str), nobs["node_id"].astype(str)))
    lots = pd.Index(sorted(set(map(str, universe)) | in_lwc | set(gb["bbl"].astype(str))))
    ranks = lot_event_ranks(T)
    best = ranks.groupby(["layer", "bbl"])["score"].min()
    registered = set(map(str, registered))

    out = []
    for layer in LAYERS:
        df = pd.DataFrame({"layer": layer, "bbl": lots})
        g = gb[gb["layer"] == layer].assign(bbl=lambda d: d["bbl"].astype(str)).set_index("bbl")
        gid = df["bbl"].map(g["group_id"])
        in_g = df["bbl"].isin(g.index)
        is_rental = df["bbl"].map(g["rental"].map(lambda v: str(v).lower() in ("true", "1"))).fillna(False).astype(bool)
        status = pd.Series("not_in_group", index=df.index, dtype=object)
        status[in_g & is_rental] = "in_group"
        status[in_g & ~is_rental] = "excluded_from_footprint"

        # facts about the source, as reason scores
        lwc = df["bbl"].isin(in_lwc)
        fact = pd.Series(pd.NA, index=df.index, dtype="object")
        fact[~lwc & ~df["bbl"].isin(registered)] = _SCORE["no_registration"]
        fact[~lwc & df["bbl"].isin(registered)] = _SCORE["no_owner_contact"]
        if layer == "owner_portfolio":                      # the identity resolution only feeds this layer's facts
            unmatched = lwc & ~df["bbl"].map(node_of).isin(matched_nodes)
            fact[unmatched] = _SCORE["unmatched_node"]
        ev = pd.Series(df.set_index(["layer", "bbl"]).index.map(best.to_dict().get), index=df.index, dtype="object")
        score = pd.concat([fact, ev], axis=1).apply(pd.to_numeric, errors="coerce").min(axis=1)
        score = score.fillna(_SCORE["no_linkage"])
        reason = score.astype(int).map(_CODE_OF)

        reason[status == "in_group"] = pd.NA
        reason[status == "excluded_from_footprint"] = "coop_condo_excluded"
        gid[status == "not_in_group"] = pd.NA
        df["status"], df["group_id"], df["reason_code"] = status, gid, reason
        df["top_level_reason"] = df["reason_code"].map(_top)
        out.append(df[STATUS_COLUMNS])
    return pd.concat(out, ignore_index=True)
