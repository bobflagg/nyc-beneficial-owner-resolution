"""A self-contained excerpt of a real release: a few Owner Portfolios, everything they cite, nothing else.

    uv run python -m bor.excerpt <release> <out> OP-67966 [OP-… ] [--note "…"]

A full release is too large to ship as a test fixture (hundreds of MB), but a consumer needs real rows
to test against. An excerpt keeps the **same run and snapshot** (``run_id``, ``snapshot_id``, source
fingerprints, assertion keys), so a consumer verifies it exactly as it verifies the whole release, and
says what it left out in ``manifest.excerpt``. Nothing is rewritten: every row is a row of the parent,
or it is not in the excerpt.

What is kept, for the selected groups ``G``:

* **Nodes and lots.** Every member node of ``G`` and every lot of those nodes (``node_observations``),
  with the observations they select or could select (``node_observation_alternatives``), and their
  identities, clusters and identity observations (``node_identity_matches``, ``identity_clusters``,
  ``identity_observations``, ``node_cluster`` and ``node_cluster_alternatives``). A cluster can reach
  nodes outside ``G``; those nodes are not kept, so a kept cluster may be only part of the parent's.
* **Groups.** ``groups``, ``group_members``, ``group_bbls`` and ``group_witness`` for ``G`` only.
* **Evidence a witness step cites**, whole: a deed's ``evidence_items`` with *all* its members (a deed
  keeps its parcel count), a link set with all its members. The nodes of those parcels that are not in
  ``G`` come along as bystanders: their lots and observations, and nothing about their identities.
  Other deeds are kept only if all their parcels are in the excerpt.
* **Decision events** all of whose references (subject, counterpart, cluster, and for a deed-level
  event the parcels it cites) are in the excerpt, with their ``decision_support``. An event that
  points outside is omitted and counted in ``manifest.excerpt.events_omitted``; the summary table
  ``bbl_status`` still carries the reason the parent computed from it.
* **Masked addresses** of the kept nodes. ``degree`` stays the parent's: the excerpt lists only the
  kept nodes, so for an excerpt ``degree`` is at least the number of rows, not equal to it.
* ``bbl_status`` for the kept lots (rows whose group is not kept are left out).
* ``method_metrics`` whole: it describes the run, not any lot, it is small, and ``explain`` shows it.

Not kept: the whole network layer.
Operational Network seeds are not supported yet: a network is a graph component, and keeping one means
keeping every group it touches. The synthetic fixture covers that layer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from bor.manifest import write_manifest
from bor.release_docs import write_data_md
from bor.release_validate import read_release, validate_release



def _s(series) -> set:
    return set(series.dropna().astype(str))


def _take(df: pd.DataFrame, col: str, values) -> pd.DataFrame:
    return df[df[col].astype(str).isin(set(map(str, values)))]


def excerpt_release(tables: dict, manifest: dict, groups, *, note: str | None = None) -> tuple[dict, dict]:
    """``(tables, manifest)`` of the excerpt of ``groups`` (Owner Portfolio ids) from a release."""
    groups = list(dict.fromkeys(groups))
    if not groups or any(not g.startswith("OP-") for g in groups):
        raise ValueError("an excerpt is cut around Owner Portfolios (OP-…); operational networks are not supported")
    T = tables
    published = _s(T["groups"].loc[T["groups"]["layer"] == "owner_portfolio", "group_id"])
    missing = [g for g in groups if g not in published]
    if missing:
        raise ValueError(f"not an Owner Portfolio of this release: {missing}")
    out: dict[str, pd.DataFrame] = {}

    # --- groups, nodes, lots -------------------------------------------------------------------
    op = lambda df: df[df["layer"] == "owner_portfolio"]
    out["groups"] = _take(op(T["groups"]), "group_id", groups)
    out["group_members"] = _take(op(T["group_members"]), "group_id", groups)
    out["group_bbls"] = _take(op(T["group_bbls"]), "group_id", groups)
    out["group_witness"] = _take(op(T["group_witness"]), "group_id", groups)
    nodes = _s(out["group_members"]["node_id"])

    # --- evidence a witness step cites, whole --------------------------------------------------
    w = out["group_witness"]
    cited_items = _s(w.loc[w["basis_type"] == "evidence_item", "basis_id"])
    cited_sets = _s(w.loc[w["basis_type"] == "link_set", "basis_id"])
    members = T["evidence_members"]
    keep_items = set(cited_items)
    nobs_all = T["node_observations"]
    lots = _s(nobs_all.loc[nobs_all["node_id"].astype(str).isin(nodes), "bbl"])
    for eid, g in members.groupby("evidence_id"):               # a deed wholly inside is kept too
        if eid not in keep_items and set(g["bbl"].astype(str)) <= lots:
            keep_items.add(eid)
    out["evidence_items"] = _take(T["evidence_items"], "evidence_id", keep_items)
    out["evidence_members"] = _take(members, "evidence_id", keep_items)
    bystanders = _s(out["evidence_members"]["node_id"]) - nodes
    out["link_sets"] = _take(T["link_sets"], "set_id", cited_sets)
    out["link_set_members"] = _take(T["link_set_members"], "set_id", cited_sets)

    # --- node, lot and identity rows ------------------------------------------------------------
    all_nodes = nodes | bystanders
    nobs = _take(nobs_all, "node_id", all_nodes)
    out["node_observations"] = nobs
    lots = _s(nobs["bbl"])
    alt = _take(T["node_observation_alternatives"], "node_id", all_nodes) if "node_observation_alternatives" in T else None
    if alt is not None:
        out["node_observation_alternatives"] = alt
    nim = _take(T["node_identity_matches"], "node_id", nodes)
    out["node_identity_matches"] = nim
    ncl = _take(T["node_cluster"], "node_id", nodes)
    out["node_cluster"] = ncl
    nca = _take(T["node_cluster_alternatives"], "node_id", nodes) if "node_cluster_alternatives" in T else None
    if nca is not None:
        out["node_cluster_alternatives"] = nca
    # identity rows: the nodes' own, then one identity for every other cluster a kept row names
    ic_all = T["identity_clusters"]
    idents = _s(nim["identity_id"])
    clusters = _s(ncl["cluster_id"]) | (_s(nca["cluster_id"]) if nca is not None else set())
    extra = ic_all[ic_all["cluster_id"].astype(str).isin(clusters - _s(_take(ic_all, "identity_id", idents)["cluster_id"]))]
    idents |= _s(extra.sort_values("identity_id").drop_duplicates("cluster_id")["identity_id"])
    out["identity_clusters"] = _take(ic_all, "identity_id", idents)
    out["identity_observations"] = _take(T["identity_observations"], "identity_id", idents)
    clusters = _s(out["identity_clusters"]["cluster_id"])
    base_clusters = _s(out["identity_clusters"]["base_cluster_id"])

    # --- masked addresses ----------------------------------------------------------------------
    if "masked_address_nodes" in T:
        man = _take(T["masked_address_nodes"], "node_id", all_nodes)
        out["masked_address_nodes"] = man
        out["masked_addresses"] = _take(T["masked_addresses"], "address_id", _s(man["address_id"]))
    addresses = _s(out["masked_addresses"]["address_id"]) if "masked_addresses" in out else set()

    # --- decision events whose every reference is inside ---------------------------------------
    de, sup = T["decision_events"], T["decision_support"]
    inside = {"identity": idents, "base_cluster": base_clusters, "cluster": clusters, "node": all_nodes,
              "bbl": lots, "parcel": lots, "group": set(groups), "address": addresses}
    sup_bbls = sup[sup["support_type"] == "bbl"].groupby("decision_id")["support_id"].apply(lambda s: set(s.astype(str)))

    def keep(row) -> bool:
        for side in ("subject", "counterpart"):
            typ, ident = row[f"{side}_type"], row[f"{side}_id"]
            if pd.isna(typ):
                continue
            if typ == "deed_document":
                cited = sup_bbls.get(row["decision_id"], set())
                if not cited or not cited <= lots:
                    return False
            elif str(ident) not in inside.get(typ, set()):
                return False
        return pd.isna(row["cluster_id"]) or str(row["cluster_id"]) in clusters

    mask = de.apply(keep, axis=1)
    out["decision_events"] = de[mask]
    out["decision_support"] = _take(sup, "decision_id", _s(de.loc[mask, "decision_id"]))
    # support can cite an observation outside the excerpt (a bridging company's contact): keep it
    obs_needed = (_s(nobs["selected_observation_id"]) | _s(out["identity_observations"]["observation_id"])
                  | (_s(alt["observation_id"]) if alt is not None else set())
                  | _s(out["decision_support"].loc[out["decision_support"]["support_type"] == "observation", "support_id"]))
    out["observations"] = _take(T["observations"], "observation_id", obs_needed)

    # --- names, for exactly the ids the excerpt keeps -----------------------------------------------
    from bor.names import cited_documents, named_lots
    if "observation_contacts" in T:
        out["observation_contacts"] = _take(T["observation_contacts"], "observation_id", _s(out["observations"]["observation_id"]))
    if "identity_names" in T:
        out["identity_names"] = _take(T["identity_names"], "identity_id", _s(out["identity_observations"]["identity_id"]) | idents)
    if "node_names" in T:
        out["node_names"] = _take(T["node_names"], "node_id", all_nodes)
    if "deed_documents" in T:
        docs = set(cited_documents(out))
        out["deed_documents"] = _take(T["deed_documents"], "document_id", docs)
        if "deed_parties" in T:
            out["deed_parties"] = _take(T["deed_parties"], "document_id", docs)
    if "lot_addresses" in T:
        out["lot_addresses"] = _take(T["lot_addresses"], "bbl", set(named_lots(out)))

    if "method_metrics" in T:
        out["method_metrics"] = T["method_metrics"]

    # --- the per-lot summary --------------------------------------------------------------------
    s = T["bbl_status"]
    s = s[s["bbl"].astype(str).isin(lots)]
    out["bbl_status"] = s[s["group_id"].isna() | s["group_id"].isin(set(groups))]

    out = {k: v.reset_index(drop=True) for k, v in out.items()}
    tables_omitted = sorted(set(T) - set(out))
    m = json.loads(json.dumps(manifest))
    m.pop("output_checksums", None)
    for pkg in (m.get("code") or {}).values():           # older releases recorded the builder's local path
        pkg.pop("checkout", None)
    m["excerpt"] = {
        "of_run_id": manifest["run_id"], "seed_groups": groups,
        "rule": "bor.excerpt: the groups, their lots and nodes, what their witness cites, events wholly inside",
        "tables_omitted": tables_omitted,
        "events_omitted": int(len(de) - mask.sum()),
        "evidence_omitted": int(T["evidence_items"]["evidence_id"].nunique() - len(out["evidence_items"])),
    }
    m["artifacts"] = {k: v for k, v in (manifest.get("artifacts") or {}).items() if k in out}
    if note:
        m["note"] = note
    return out, m


def write_excerpt(tables: dict, manifest: dict, out_dir) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.csv"):
        stale.unlink()
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False)
    write_data_md(out, manifest, tables)
    write_manifest(out, manifest)
    return out


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("release")
    ap.add_argument("out")
    ap.add_argument("groups", nargs="+", help="Owner Portfolio ids, e.g. OP-67966")
    ap.add_argument("--note")
    a = ap.parse_args()
    tables, manifest = read_release(a.release)
    ex, m = excerpt_release(tables, manifest, a.groups, note=a.note)
    path = write_excerpt(ex, m, a.out)
    tables2, manifest2 = read_release(str(path))
    found = validate_release(tables2, manifest2, path=str(path))
    for x in found:
        print(x)
    print({k: len(v) for k, v in ex.items()})
    print(json.dumps(m["excerpt"], indent=2))
    raise SystemExit(1 if any(x.severity == "error" for x in found) else 0)


if __name__ == "__main__":
    main()
