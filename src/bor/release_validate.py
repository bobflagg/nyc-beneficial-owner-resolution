"""Validate a release directory (or in-memory tables) against :mod:`bor.release_schema`.

    uv run python -m bor.release_validate ./release

Checks, in order: columns, types, nullability, enums, keys, foreign keys, then the cross-table
invariants the contract promises (witness trees, reason consistency, node/cluster agreement, ...).
Tables that are absent are skipped; a table whose foreign-key parent is absent is an error.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass

import pandas as pd

from bor.release_schema import (ARTIFACT_KINDS, DEED_RULE_FIELDS, MANIFEST_REQUIRED, PRECEDENCE,
                                REASON_CODES, SCHEMA_VERSION, SOURCE_TABLE_FIELDS, TABLES, Table)


@dataclass(frozen=True)
class Violation:
    table: str
    check: str
    message: str
    count: int = 1
    severity: str = "error"

    def __str__(self) -> str:
        return f"[{self.severity}] {self.table}: {self.check}: {self.message} ({self.count})"


_TRUE = {"true", "1", "t", "yes"}
_FALSE = {"false", "0", "f", "no"}


# ---- reading -------------------------------------------------------------------------------------

def read_release(path: str) -> tuple[dict[str, pd.DataFrame], dict | None]:
    """Read every known ``<table>.csv`` in ``path`` as strings (so ids keep leading zeros), and
    ``manifest.json`` if present."""
    tables = {}
    for name in TABLES:
        f = os.path.join(path, f"{name}.csv")
        if os.path.exists(f):
            tables[name] = pd.read_csv(f, dtype=str, keep_default_na=False, na_values=[""])
    mf = os.path.join(path, "manifest.json")
    manifest = json.load(open(mf)) if os.path.exists(mf) else None
    return tables, manifest


# ---- per-table checks ----------------------------------------------------------------------------

def _coerce(df: pd.DataFrame, t: Table) -> tuple[pd.DataFrame, list[Violation]]:
    out, bad = df.copy(), []
    for c in t.columns:
        if c.name not in out.columns:
            continue
        col = out[c.name]
        if c.type in ("int", "float"):
            num = pd.to_numeric(col, errors="coerce")
            invalid = int((col.notna() & num.isna()).sum())
            if c.type == "int":
                frac = int((num.notna() & (num != num.round())).sum())
                invalid += frac
                num = num.round().astype("Int64")
            if invalid:
                bad.append(Violation(t.name, "type", f"{c.name}: {invalid} values are not {c.type}", invalid))
            out[c.name] = num
        elif c.type == "bool":
            if col.dtype == bool or str(col.dtype) == "boolean":
                continue
            low = col.astype("string").str.lower()
            mapped = low.map(lambda v: True if v in _TRUE else (False if v in _FALSE else pd.NA))
            invalid = int((col.notna() & mapped.isna()).sum())
            if invalid:
                bad.append(Violation(t.name, "type", f"{c.name}: {invalid} values are not boolean", invalid))
            out[c.name] = mapped.astype("boolean")
    return out, bad


def _check_table(df: pd.DataFrame, t: Table) -> tuple[pd.DataFrame, list[Violation]]:
    v: list[Violation] = []
    names = [c.name for c in t.columns]
    missing = [c.name for c in t.columns if c.name not in df.columns and not c.optional]
    extra = [c for c in df.columns if c not in names]
    if missing:
        v.append(Violation(t.name, "columns", f"missing columns {missing}", len(missing)))
        return df, v
    if extra:
        v.append(Violation(t.name, "columns", f"unknown columns {extra}", len(extra), "warning"))
    df, bad = _coerce(df, t)
    v += bad
    for c in t.columns:
        if c.name not in df.columns:
            continue
        col = df[c.name]
        if not c.nullable:
            n = int(col.isna().sum())
            if n:
                v.append(Violation(t.name, "null", f"{c.name} must not be null", n))
        if c.enum is not None:
            n = int((col.notna() & ~col.isin(c.enum)).sum())
            if n:
                v.append(Violation(t.name, "enum", f"{c.name} outside {list(c.enum)[:6]}...", n))
    dup = int(df.duplicated(list(t.key)).sum())
    if dup:
        v.append(Violation(t.name, "key", f"{dup} duplicate rows on key {list(t.key)}", dup))
    return df, v


def _check_fks(tables: dict[str, pd.DataFrame]) -> list[Violation]:
    v = []
    for name, df in tables.items():
        for fk in TABLES[name].fks:
            if fk.table not in tables:
                v.append(Violation(name, "fk_parent_missing", f"{list(fk.cols)} -> {fk.table} (absent)"))
                continue
            if any(c not in df.columns for c in fk.cols):
                continue
            child = df[list(fk.cols)].dropna().drop_duplicates()
            parent = tables[fk.table][list(fk.ref_cols)].drop_duplicates()
            parent.columns = list(fk.cols)
            m = child.merge(parent, on=list(fk.cols), how="left", indicator=True)
            n = int((m["_merge"] == "left_only").sum())
            if n:
                v.append(Violation(name, "fk", f"{n} {list(fk.cols)} values not in {fk.table}.{list(fk.ref_cols)}", n))
    return v


# ---- cross-table invariants ----------------------------------------------------------------------

def _missing_from(values: pd.Series, target: pd.Series) -> int:
    return int((~values.dropna().isin(set(target.dropna()))).sum())


def _inv_observations(T):
    o = T.get("observations")
    if o is None:
        return []
    n = int((o["k"] >= o["pair_variants"]).sum())
    return [Violation("observations", "k", "k must be below pair_variants", n)] if n else []


def _inv_node_observations(T):
    df = T.get("node_observations")
    if df is None:
        return []
    v = []
    n = int(df["bbl"].duplicated().sum())
    if n:
        v.append(Violation("node_observations", "bbl_once", "a BBL must belong to exactly one node", n))
    amb = df["ambiguous"].fillna(False).astype(bool)
    n = int((amb & (df["selected_observation_id"].notna() | (df["n_candidates"] <= 1))).sum())
    if n:
        v.append(Violation("node_observations", "ambiguous", "ambiguous rows must have >1 candidate and no selection", n))
    n = int((~amb & (df["n_candidates"] == 1) & df["selected_observation_id"].isna()).sum())
    if n:
        v.append(Violation("node_observations", "selected", "a unique candidate must be selected", n))
    n = int(((df["n_candidates"] == 0) & df["selected_observation_id"].notna()).sum())
    if n:
        v.append(Violation("node_observations", "selected", "no candidates but a selection", n))
    alt = T.get("node_observation_alternatives")
    if alt is not None:
        keyed = df[amb][["node_id", "bbl", "n_candidates"]]
        cnt = alt.groupby(["node_id", "bbl"]).size().rename("n_alt").reset_index()
        m = keyed.merge(cnt, on=["node_id", "bbl"], how="left")
        n = int((m["n_alt"].fillna(0) != m["n_candidates"]).sum())
        if n:
            v.append(Violation("node_observation_alternatives", "alternatives",
                               "ambiguous rows need one alternative per candidate", n))
        n = int((~alt.set_index(["node_id", "bbl"]).index.isin(keyed.set_index(["node_id", "bbl"]).index)).sum())
        if n:
            v.append(Violation("node_observation_alternatives", "alternatives", "alternatives for unambiguous rows", n))
    return v


def _inv_node_cluster(T):
    nc = T.get("node_cluster")
    if nc is None:
        return []
    v = []
    n = int(((nc["n_clusters"] == 1) & nc["tied"].fillna(False).astype(bool)).sum())
    if n:
        v.append(Violation("node_cluster", "tied", "a node in one cluster cannot be tied", n))
    alt = T.get("node_cluster_alternatives")
    if alt is not None:
        sel = alt[alt["selected"].fillna(False).astype(bool)]
        n = int((sel.groupby("node_id").size() != 1).sum())
        if n:
            v.append(Violation("node_cluster_alternatives", "selected", "exactly one selected cluster per node", n))
        m = sel.merge(nc[["node_id", "cluster_id"]], on=["node_id", "cluster_id"], how="left", indicator=True)
        n = int((m["_merge"] == "left_only").sum())
        if n:
            v.append(Violation("node_cluster_alternatives", "selected", "selected cluster differs from node_cluster", n))
        per = alt.groupby("node_id").size().rename("n_alt").reset_index()
        m = nc[nc["n_clusters"] > 1][["node_id", "n_clusters"]].merge(per, on="node_id", how="left")
        n = int((m["n_alt"].fillna(0) != m["n_clusters"]).sum())
        if n:
            v.append(Violation("node_cluster_alternatives", "alternatives", "straddling nodes need one row per cluster", n))
    return v


def _inv_identity_clusters(T):
    ic = T.get("identity_clusters")
    if ic is None:
        return []
    io = T.get("identity_observations")
    if io is not None:
        n = int((~ic["identity_id"].isin(set(io["identity_id"]))).sum())
        if n:
            return [Violation("identity_clusters", "observations", "every clustered identity needs observations", n)]
    if "base_cluster_id" not in ic.columns:
        return []
    g = ic.dropna(subset=["base_cluster_id"]).groupby("base_cluster_id")["cluster_id"].nunique()
    n = int((g > 1).sum())
    return [Violation("identity_clusters", "base_cluster", "a base cluster belongs to one final cluster", n)] if n else []


_SUBJECT_TARGETS = {
    "identity": ("identity_clusters", "identity_id"), "base_cluster": ("identity_clusters", "base_cluster_id"),
    "cluster": ("identity_clusters", "cluster_id"), "node": ("node_observations", "node_id"),
    "bbl": ("node_observations", "bbl"), "group": ("groups", "group_id"),
    "address": ("masked_addresses", "address_id"), "component": ("network_membership", "component_id"),
    "parcel": ("node_observations", "bbl"),
}


def _inv_decision_events(T):
    de = T.get("decision_events")
    if de is None:
        return []
    v = []
    n = int((de["counterpart_type"].isna() != de["counterpart_id"].isna()).sum())
    if n:
        v.append(Violation("decision_events", "counterpart", "counterpart type and id go together", n))
    acc = de["outcome"] == "accepted"
    n = int((acc & de["reason_code"].notna()).sum() + (~acc & de["reason_code"].isna()).sum())
    if n:
        v.append(Violation("decision_events", "reason", "accepted events carry no reason; every other outcome has one", n))
    for side in ("subject", "counterpart"):
        ids = de.loc[de[f"{side}_type"] == "identity", f"{side}_id"].astype(str)
        known = set()
        for tbl in ("identity_clusters", "identity_observations"):
            if tbl in T:
                known |= set(T[tbl]["identity_id"].astype(str))
        if known and len(ids) and int((~ids.isin(known)).sum()):
            v.append(Violation("decision_events", "reference",
                               f"{side} identity in neither identity_clusters nor identity_observations",
                               int((~ids.isin(known)).sum())))
        for typ, (tbl, col) in _SUBJECT_TARGETS.items():
            if typ in ("group", "identity"):
                continue                      # group: checked below (dropped groups are not published)
            if tbl not in T or col not in T[tbl].columns:
                continue
            ids = de.loc[de[f"{side}_type"] == typ, f"{side}_id"]
            m = _missing_from(ids.astype(str), T[tbl][col].astype(str))
            if m:
                v.append(Violation("decision_events", "reference", f"{side} {typ} not in {tbl}.{col}", m))
    if "groups" in T:
        grp = de[(de["subject_type"] == "group")]
        published = set(T["groups"]["group_id"].astype(str))
        dropped = grp["outcome"] == "dropped"
        n = int((dropped & grp["subject_id"].astype(str).isin(published)).sum()
                + (~dropped & ~grp["subject_id"].astype(str).isin(published)).sum())
        if n:
            v.append(Violation("decision_events", "reference",
                               "a group subject is in groups unless its outcome is dropped", n))
    if "identity_clusters" in T:
        m = _missing_from(de["cluster_id"], T["identity_clusters"]["cluster_id"])
        if m:
            v.append(Violation("decision_events", "reference", "cluster_id not in identity_clusters", m))
    sup = T.get("decision_support")
    if sup is not None:
        for typ, (tbl, col) in {"observation": ("observations", "observation_id"),
                                "bbl": ("node_observations", "bbl")}.items():
            if tbl in T:
                m = _missing_from(sup.loc[sup["support_type"] == typ, "support_id"], T[tbl][col])
                if m:
                    v.append(Violation("decision_support", "reference", f"{typ} support not in {tbl}.{col}", m))
    return v


def _inv_groups(T):
    g, gm, gb = T.get("groups"), T.get("group_members"), T.get("group_bbls")
    v = []
    if g is not None and gb is not None:
        rental = gb[gb["rental"].fillna(False).astype(bool)].groupby(["layer", "group_id"]).size().rename("r")
        total = gb.groupby(["layer", "group_id"]).size().rename("t")
        m = g.set_index(["layer", "group_id"]).join(rental).join(total)
        n = int(((m["r"].fillna(0) != m["lot_count"]) | (m["t"].fillna(0) != m["total_lot_count"])).sum())
        if n:
            v.append(Violation("groups", "counts", "lot counts disagree with group_bbls", n))
    if g is not None:
        want = g["layer"].map({"owner_portfolio": "OP-", "operational_network": "ON-"})
        n = int((~pd.Series([str(i).startswith(p) for i, p in zip(g["group_id"], want)], index=g.index)).sum())
        if n:
            v.append(Violation("groups", "group_id_prefix",
                               "group ids start OP- in owner_portfolio and ON- in operational_network", n))
    keys = [("groups", g), ("group_members", gm), ("group_witness", T.get("group_witness"))]
    seen = pd.concat([d["assertion_key"] for _, d in keys if d is not None], ignore_index=True) \
        if any(d is not None for _, d in keys) else pd.Series(dtype=str)
    n = int(seen.duplicated().sum())
    if n:
        v.append(Violation("groups", "assertion_key", "assertion keys must be unique across the release", n))
    return v


def _inv_witness(T):
    w, gm = T.get("group_witness"), T.get("group_members")
    if w is None or gm is None:
        return []
    v = []
    members = gm.groupby(["layer", "group_id"])["node_id"].apply(set).to_dict()
    cycles = disconnected = outside = 0
    for key, edges in w.sort_values("step").groupby(["layer", "group_id"]):
        mem = members.get(key, set())
        parent = {n: n for n in mem}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b in zip(edges["node_a"], edges["node_b"]):
            if a not in mem or b not in mem:
                outside += 1
                continue
            ra, rb = find(a), find(b)
            if ra == rb:
                cycles += 1
            else:
                parent[ra] = rb
        if mem and len({find(x) for x in mem}) != 1:
            disconnected += 1
    for count, msg in ((outside, "witness edge endpoint is not a member of the group"),
                       (cycles, "witness edge closes a cycle (must be a spanning tree)"),
                       (disconnected, "witness edges do not connect the group")):
        if count:
            v.append(Violation("group_witness", "tree", msg, count))
    missing = set(members) - {k for k, _ in w.groupby(["layer", "group_id"])}
    multi = {k for k, m in members.items() if len(m) > 1}
    n = len(missing & multi)
    if n:
        v.append(Violation("group_witness", "tree", "groups with several members and no witness", n))
    return v


_RANK = {code: (PRECEDENCE.index(top), i) for i, (code, (top, _)) in enumerate(REASON_CODES.items())}


def _inv_bbl_status(T):
    s = T.get("bbl_status")
    if s is None:
        return []
    v = []
    ing = s["status"] == "in_group"
    exf = s["status"] == "excluded_from_footprint"
    n = int((ing & (s["group_id"].isna() | s["reason_code"].notna())).sum())
    if n:
        v.append(Violation("bbl_status", "status", "in_group rows need a group and no reason", n))
    n = int((exf & (s["group_id"].isna() | s["reason_code"].isna())).sum())
    if n:
        v.append(Violation("bbl_status", "status", "excluded_from_footprint rows need a group and a reason", n))
    nig = s["status"] == "not_in_group"
    n = int((nig & (s["reason_code"].isna() | s["group_id"].notna())).sum())
    if n:
        v.append(Violation("bbl_status", "status", "not_in_group rows need a reason and no group", n))
    top = s["reason_code"].map(lambda c: REASON_CODES[c][0] if c in REASON_CODES else pd.NA)
    n = int((s["reason_code"].notna() & (top != s["top_level_reason"])).sum())
    if n:
        v.append(Violation("bbl_status", "reason", "top_level_reason disagrees with reason_code", n))
    gb = T.get("group_bbls")
    if gb is not None:
        non_rental = gb.loc[~gb["rental"].fillna(True).astype(bool), ["layer", "bbl"]].assign(_nr=True)
        m = s.merge(non_rental, on=["layer", "bbl"], how="left")
        n = int((exf.reset_index(drop=True) != m["_nr"].fillna(False).astype(bool)).sum())
        if n:
            v.append(Violation("bbl_status", "footprint",
                               "excluded_from_footprint must match group_bbls.rental = false", n))
    de, nobs = T.get("decision_events"), T.get("node_observations")
    if de is not None and nobs is not None:
        ev = de[de["outcome"] != "accepted"].dropna(subset=["reason_code"]).copy()
        ev["rank"] = ev["reason_code"].map(_RANK)
        node_bbl = nobs[["node_id", "bbl"]].assign(node_id=lambda d: d["node_id"].astype(str))
        parts = [ev[ev["subject_type"] == "bbl"].rename(columns={"subject_id": "bbl"})[["layer", "bbl", "rank"]],
                 ev[ev["subject_type"] == "node"].merge(node_bbl, left_on="subject_id", right_on="node_id")[["layer", "bbl", "rank"]]]
        nim = T.get("node_identity_matches")
        if nim is not None:
            for side in ("subject", "counterpart"):
                idev = ev[ev[f"{side}_type"] == "identity"]
                parts.append(idev.merge(nim[["identity_id", "bbl"]], left_on=f"{side}_id", right_on="identity_id")
                             [["layer", "bbl", "rank"]])
        grp = s.dropna(subset=["group_id"])[["layer", "bbl", "group_id"]]
        parts.append(ev[ev["subject_type"] == "group"].merge(grp, left_on=["layer", "subject_id"], right_on=["layer", "group_id"])[["layer", "bbl", "rank"]])
        lot_ev = pd.concat(parts, ignore_index=True)
        # identity-layer events (vetoes, guards) bear on both layers
        ident = lot_ev[lot_ev["layer"] == "identity"].drop(columns="layer")
        best = pd.concat([lot_ev[lot_ev["layer"] != "identity"], *[ident.assign(layer=l) for l in s["layer"].unique()]])
        best = best.groupby(["layer", "bbl"])["rank"].min().rename("best").reset_index()
        m = s.dropna(subset=["reason_code"]).assign(rank=lambda d: d["reason_code"].map(_RANK)).merge(
            best, on=["layer", "bbl"])
        n = int((m["rank"] > m["best"]).sum())
        if n:
            v.append(Violation("bbl_status", "precedence",
                               "reason_code must be the highest-precedence reason among the lot's events", n))
    return v


def _inv_metrics(T):
    m = T.get("method_metrics")
    if m is None:
        return []
    v = []
    n = int((m["precision"].isna() & m["note"].isna()).sum())
    if n:
        v.append(Violation("method_metrics", "null", "an unevaluated metric needs a note", n))
    p = m.dropna(subset=["precision"])
    n = int(((p["precision"] < 0) | (p["precision"] > 1)).sum())
    n += int(((p["ci_lower"] > p["precision"]) | (p["ci_upper"] < p["precision"])).sum())
    if n:
        v.append(Violation("method_metrics", "interval", "precision must lie in [0,1] and inside its interval", n))
    return v


def _inv_evidence(T):
    items, members, nobs = T.get("evidence_items"), T.get("evidence_members"), T.get("node_observations")
    v = []
    if items is not None and members is not None:
        cnt = members.groupby("evidence_id").size()
        n = int((items.set_index("evidence_id")["parcel_count"] != cnt.reindex(items["evidence_id"]).fillna(0).to_numpy()).sum())
        if n:
            v.append(Violation("evidence_items", "parcel_count", "parcel_count must equal the member rows", n))
        roles = members.groupby("evidence_id")["role"].apply(lambda r: (r == "transferred_onward").any())
        want = roles.reindex(items["evidence_id"]).fillna(False).map({True: "deed.linked_successor", False: "deed.held_since"})
        n = int((items["stage"].to_numpy() != want.to_numpy()).sum())
        if n:
            v.append(Violation("evidence_items", "stage",
                               "a deed is linked_successor if any member was transferred onward, else held_since", n))
        n = int((members["role"].eq("held_under_joint_deed") & members["latest_document_id"].notna()
                 & (members["latest_document_id"] != members["original_document_id"])).sum())
        n += int((members["role"].eq("transferred_onward") & (members["latest_document_id"] == members["original_document_id"])).sum())
        if n:
            v.append(Violation("evidence_members", "roles",
                               "held members have the joint deed as latest; transferred ones a different deed", n))
    if members is not None and nobs is not None:
        m = members.merge(nobs[["node_id", "bbl"]], on="bbl", how="left", suffixes=("", "_obs"))
        n = int((m["node_id_obs"].isna() | (m["node_id"] != m["node_id_obs"])).sum())
        if n:
            v.append(Violation("evidence_members", "node", "a member's node must be the node of its BBL", n))
    return v


_BASIS_TABLE = {"identity_cluster": ("identity_clusters", "cluster_id"),
                "evidence_item": ("evidence_items", "evidence_id"), "link_set": ("link_sets", "set_id"),
                "network_edge": ("network_edges", "edge_id")}
_STAGE_BASIS = {"identity.splink_base": "identity_cluster", "identity.splink_feedback": "identity_cluster",
                "identity.curated": "link_set", "identity.registered_llc": "link_set",
                "deed.held_since": "evidence_item", "deed.linked_successor": "evidence_item",
                "network.name": "network_edge", "network.address": "network_edge"}


def _inv_witness_basis(T):
    w = T.get("group_witness")
    if w is None:
        return []
    v = []
    expected = w["stage"].map(_STAGE_BASIS)
    n = int((expected != w["basis_type"]).sum())
    if n:
        v.append(Violation("group_witness", "basis_type", "a step's stage fixes the kind of evidence it cites", n))
    for kind, (tbl, col) in _BASIS_TABLE.items():
        if tbl in T:
            m = _missing_from(w.loc[w["basis_type"] == kind, "basis_id"], T[tbl][col])
            if m:
                v.append(Violation("group_witness", "basis", f"{kind} basis not in {tbl}.{col}", m))
    ls = T.get("link_sets")
    if ls is not None:
        sets = ls.set_index("set_id")["stage"]
        used = w[w["basis_type"] == "link_set"]
        n = int((used["stage"].to_numpy() != used["basis_id"].map(sets).to_numpy()).sum())
        if n:
            v.append(Violation("group_witness", "basis_stage", "a link-set step has the stage of its set", n))
    return v


def _inv_link_sets(T):
    ls, lm = T.get("link_sets"), T.get("link_set_members")
    if ls is None or lm is None:
        return []
    v = []
    cnt = lm.groupby("set_id")["node_id"].nunique()
    n = int((ls.set_index("set_id")["size"] != cnt.reindex(ls["set_id"]).fillna(0).to_numpy()).sum())
    if n:
        v.append(Violation("link_sets", "size", "size must equal the number of member nodes", n))
    stage = lm["set_id"].map(ls.set_index("set_id")["stage"])
    n = int(((stage == "identity.curated") & lm["source_bbl"].notna()).sum()
            + ((stage == "identity.registered_llc") & lm["source_bbl"].isna()).sum())
    if n:
        v.append(Violation("link_set_members", "source_bbl",
                           "a registered-LLC member cites its lot; a curated owner has none", n))
    return v


_INVARIANTS = (_inv_witness_basis, _inv_link_sets, _inv_evidence, _inv_observations, _inv_node_observations, _inv_node_cluster, _inv_identity_clusters, _inv_decision_events,
               _inv_groups, _inv_witness, _inv_bbl_status, _inv_metrics)


# ---- manifest ------------------------------------------------------------------------------------

def check_manifest(manifest: dict | None, path: str | None = None) -> list[Violation]:
    if manifest is None:
        return [Violation("manifest", "missing", "manifest.json is required")]
    v = [Violation("manifest", "field", f"missing {k}") for k in MANIFEST_REQUIRED if k not in manifest]
    if manifest.get("schema_version") not in (None, SCHEMA_VERSION):
        v.append(Violation("manifest", "schema_version", f"{manifest['schema_version']} != {SCHEMA_VERSION}"))
    for name, entry in (manifest.get("source_tables") or {}).items():
        miss = [f for f in SOURCE_TABLE_FIELDS if not isinstance(entry, dict) or f not in entry]
        if miss:
            v.append(Violation("manifest", "source_tables", f"{name} lacks {miss}"))
    rule = manifest.get("deed_selection_rule")
    if rule is not None and (not isinstance(rule, dict) or any(f not in rule for f in DEED_RULE_FIELDS)):
        v.append(Violation("manifest", "deed_selection_rule", f"needs {list(DEED_RULE_FIELDS)}"))
    for name, kind in (manifest.get("artifacts") or {}).items():
        if name not in TABLES:
            v.append(Violation("manifest", "artifacts", f"unknown artifact {name}"))
        elif kind not in ARTIFACT_KINDS:
            v.append(Violation("manifest", "artifacts", f"{name}: {kind} not in {list(ARTIFACT_KINDS)}"))
    if path:
        for fname, digest in (manifest.get("output_checksums") or {}).items():
            f = os.path.join(path, fname)
            if not os.path.exists(f):
                v.append(Violation("manifest", "checksum", f"{fname} listed but missing"))
            elif hashlib.sha256(open(f, "rb").read()).hexdigest() != digest:
                v.append(Violation("manifest", "checksum", f"{fname} does not match its checksum"))
    return v


# ---- entry points --------------------------------------------------------------------------------

def validate_release(tables: dict[str, pd.DataFrame], manifest: dict | None = None, *,
                     require: tuple[str, ...] = (), path: str | None = None,
                     check_manifest_too: bool = True) -> list[Violation]:
    """Return every violation found (an empty list means the release satisfies the contract)."""
    v: list[Violation] = []
    if check_manifest_too:
        v += check_manifest(manifest, path)
    for name in require:
        if name not in tables:
            v.append(Violation(name, "missing", "required table is absent"))
    typed: dict[str, pd.DataFrame] = {}
    for name, df in tables.items():
        if name not in TABLES:
            v.append(Violation(name, "unknown_table", "not in the contract", severity="warning"))
            continue
        typed[name], bad = _check_table(df, TABLES[name])
        v += bad
    v += _check_fks(typed)
    if not any(x.severity == "error" and x.check in ("columns", "type") for x in v):
        for inv in _INVARIANTS:
            v += inv(typed)
    return v


def main() -> None:  # pragma: no cover
    path = sys.argv[1]
    tables, manifest = read_release(path)
    found = validate_release(tables, manifest, path=path)
    for x in found:
        print(x)
    errors = [x for x in found if x.severity == "error"]
    print(f"{len(tables)} tables, {len(errors)} errors, {len(found) - len(errors)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
