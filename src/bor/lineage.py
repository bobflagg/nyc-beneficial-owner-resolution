"""Mapping tables from resolution nodes to the HPD records behind them (W0 of the KG handoff).

bor's nodes are ``landlords_with_connections`` (lwc) rows and its identity edges come from nlr
identities (``unique_id`` = md5 of a person owner contact's kind, name and address). The KG needs
to get from either back to HPD contact records. This module builds the lookup tables and a report
of what does not map cleanly; see docs/w0-findings.md for the measurements behind the design.

Tables (no names; HPD ids and BBLs only):

* ``node_observations``       — one row per (lwc node, BBL): the registration WoW used and the
  contact it selected, or null with ``ambiguous`` when WoW's own ordering leaves a tie.
* ``node_observation_alternatives`` — the tied candidates for ambiguous rows.
* ``identity_observations``   — nlr identity -> the HPD contacts (per BBL) it aggregates.
* ``node_identity_matches``   — the (name, bbl) matches bor uses to attach identities to nodes.
* ``node_cluster``            — the cluster each node is assigned, with ``n_clusters`` and
  ``tied`` (the tie rule is arbitrary; see :func:`bor.splink_bridge.select_cluster`).
* ``node_cluster_alternatives`` — the clusters of nodes that straddle several.
* ``identity_clusters``       — final cluster of each identity.
* ``observations``            — every observation referenced above.

**Observation id** ``"{registrationid}:{registrationcontactid}:{k}"``. HPD's contact id is not
unique (1,028 repeated pairs, 616 with differing content), so ``k`` is the 0-based rank of the
row's content digest among the distinct contents sharing the (registration, contact id) pair; it
is 0 for the 99.9% of pairs that are unique. The digest is :data:`DIGEST_SQL`; it is used only to
number, never exported, so the ids reveal nothing about the contact.

**Identity side is temporary.** nlr's extraction drops contact ids, so ``identity_observations``
re-derives them with SQL that mirrors nlr's ``EXTRACT_SQL``. Every (identity, bbl) in the
resolved frame must be found; :func:`build_mapping` reports any that are not. W2 replaces this by
capturing the lineage inside nlr.
"""
from __future__ import annotations

import json
import os

import pandas as pd

from bor.splink_bridge import node_cluster_votes, select_cluster

OWNER_ROLES = ("HeadOfficer", "IndividualOwner", "CorporateOwner", "JointOwner")

# WoW's order when it picks one contact per registration
# (who-owns-what portfoliograph/sql/landlords_to_standardize.sql).
WOW_ROLE_ORDER = ("IndividualOwner", "HeadOfficer", "JointOwner", "CorporateOwner")

# NULL and '' hash alike on purpose: both mean "not recorded".
DIGEST_SQL = ("md5(concat_ws('|', coalesce(type,''), coalesce(firstname,''), coalesce(middleinitial,''),"
              " coalesce(lastname,''), coalesce(corporationname,''), coalesce(businesshousenumber,''),"
              " coalesce(businessstreetname,''), coalesce(businessapartment,''),"
              " coalesce(businesscity,''), coalesce(businessstate,''), coalesce(businesszip,'')))")

_ROLES_SQL = ",".join(f"'{r}'" for r in OWNER_ROLES)

_CONTACT_OBS = f"""
contact_obs AS (
  SELECT registrationid, registrationcontactid, type, firstname, lastname, corporationname,
         businesshousenumber, businessstreetname, businessapartment, businesscity, businessstate,
         businesszip,
         dense_rank() OVER (PARTITION BY registrationid, registrationcontactid ORDER BY digest) - 1 AS k
  FROM (SELECT DISTINCT registrationid, registrationcontactid, type, firstname, middleinitial,
               lastname, corporationname, businesshousenumber, businessstreetname,
               businessapartment, businesscity, businessstate, businesszip,
               {DIGEST_SQL} AS digest
        FROM hpd_contacts) d
)"""

# One row per (lwc node, BBL, candidate contact): WoW's candidate filter, then its role order.
_NODE_OBS_SQL = f"""
WITH {_CONTACT_OBS},
node_bbl AS (
  SELECT l.nodeid, btrim(b) AS bbl FROM landlords_with_connections l, unnest(l.bbls::text[]) AS b
),
wl AS (SELECT btrim(bbl) AS bbl, registrationid, name FROM wow_landlords WHERE bbl IS NOT NULL),
cand AS (
  SELECT nb.nodeid, nb.bbl, wl.registrationid, o.registrationcontactid, o.k,
         array_position(ARRAY[{",".join(f"'{r}'" for r in WOW_ROLE_ORDER)}]::text[], o.type) AS prec
  FROM node_bbl nb
  JOIN wl ON wl.bbl = nb.bbl
  LEFT JOIN contact_obs o ON o.registrationid = wl.registrationid
       AND o.type IN ({_ROLES_SQL})
       AND (o.firstname IS NOT NULL OR o.lastname IS NOT NULL)
       AND (o.businesshousenumber IS NOT NULL OR o.businessstreetname IS NOT NULL)
       AND length(concat(o.businesshousenumber, o.businessstreetname)) > 2
       AND upper(concat_ws(' ', o.firstname, o.lastname)) = wl.name
)
SELECT c.* FROM cand c
LEFT JOIN (SELECT nodeid, bbl, min(prec) AS p FROM cand GROUP BY 1, 2) b
  ON b.nodeid = c.nodeid AND b.bbl = c.bbl
WHERE c.prec IS NOT DISTINCT FROM b.p
"""

# nlr's most-recent-registration rule, keeping every registration tied for first (nlr's own
# DISTINCT ON picks one of them arbitrarily), and nlr's identity formula over the contact.
_IDENTITY_OBS_SQL = f"""
WITH {_CONTACT_OBS},
ranked AS (
  SELECT btrim(r.bbl) AS bbl, r.registrationid,
         dense_rank() OVER (PARTITION BY btrim(r.bbl)
                            ORDER BY r.registrationenddate DESC NULLS LAST,
                                     r.lastregistrationdate DESC NULLS LAST) AS rk
  FROM hpd_registrations r WHERE r.bbl IS NOT NULL
),
top AS (SELECT bbl, registrationid, count(*) OVER (PARTITION BY bbl) AS n_tied FROM ranked WHERE rk = 1),
n AS (
  SELECT t.bbl, t.n_tied, o.registrationid, o.registrationcontactid, o.k,
    NULLIF(upper(btrim(o.firstname)),'') AS fn, NULLIF(upper(btrim(o.lastname)),'') AS ln,
    NULLIF(upper(btrim(o.corporationname)),'') AS corp,
    NULLIF(upper(btrim(o.businesshousenumber)),'') AS bh, NULLIF(upper(btrim(o.businessstreetname)),'') AS bs,
    NULLIF(upper(btrim(o.businessapartment)),'') AS ba, NULLIF(upper(btrim(o.businesscity)),'') AS bc,
    NULLIF(upper(btrim(o.businessstate)),'') AS bst, NULLIF(btrim(o.businesszip),'') AS bz
  FROM top t
  JOIN contact_obs o ON o.registrationid = t.registrationid
  WHERE o.type IN ({_ROLES_SQL})
    AND (o.firstname IS NOT NULL OR o.lastname IS NOT NULL OR o.corporationname IS NOT NULL)
    AND (o.businesshousenumber IS NOT NULL OR o.businessstreetname IS NOT NULL)
    AND length(concat(o.businesshousenumber, o.businessstreetname)) > 2
)
SELECT bbl, n_tied, registrationid, registrationcontactid, k,
  md5((CASE WHEN fn IS NOT NULL OR ln IS NOT NULL THEN 'person' ELSE 'org' END) || '|' ||
      coalesce(coalesce(NULLIF(trim(concat_ws(' ', fn, ln)),''), corp), '') || '|' ||
      concat_ws('|', bh, bs, ba, bz, bc, bst)) AS unique_id
FROM n
"""


def observation_id(registrationid, registrationcontactid, k) -> str:
    return f"{int(registrationid)}:{int(registrationcontactid)}:{int(k)}"


def _with_obs_id(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["observation_id"] = [observation_id(r, c, k) for r, c, k in
                            zip(df["registrationid"], df["registrationcontactid"], df["k"])]
    return df


def node_observation_tables(cand: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """From candidate rows ``[nodeid, bbl, registrationid, registrationcontactid, k]`` (null
    contact when none qualified) to ``node_observations`` and the alternatives of tied rows."""
    has = cand.dropna(subset=["registrationcontactid"])
    has = _with_obs_id(has.astype({"registrationcontactid": "int64", "k": "int64"}))
    counts = has.groupby(["nodeid", "bbl"])["observation_id"].nunique().rename("n_candidates")
    base = cand[["nodeid", "bbl", "registrationid"]].drop_duplicates().set_index(["nodeid", "bbl"])
    out = base.join(counts).fillna({"n_candidates": 0}).reset_index()
    out["n_candidates"] = out["n_candidates"].astype(int)
    one = has.drop_duplicates(["nodeid", "bbl", "observation_id"])
    one = one[one.groupby(["nodeid", "bbl"])["observation_id"].transform("size") == 1]
    out = out.merge(one[["nodeid", "bbl", "observation_id"]].rename(
        columns={"observation_id": "selected_observation_id"}), on=["nodeid", "bbl"], how="left")
    out["ambiguous"] = out["n_candidates"] > 1
    out = out.rename(columns={"nodeid": "node_id", "registrationid": "registration_id"})
    alt = has[has.set_index(["nodeid", "bbl"]).index.isin(
        out.loc[out["ambiguous"]].set_index(["node_id", "bbl"]).index)]
    alt = (alt.drop_duplicates(["nodeid", "bbl", "observation_id"])
              [["nodeid", "bbl", "observation_id"]].rename(columns={"nodeid": "node_id"}))
    return out, alt.reset_index(drop=True)


def node_cluster_tables(votes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """From the (name, bbl) matches to ``node_cluster`` and the alternatives of straddling nodes."""
    cnt = votes.groupby(["nodeid", "cluster_id"]).size().rename("votes").reset_index()
    top = cnt.groupby("nodeid")["votes"].transform("max")
    per = cnt.assign(is_top=cnt["votes"] == top).groupby("nodeid").agg(
        n_clusters=("cluster_id", "nunique"), n_top=("is_top", "sum")).reset_index()
    per["tied"] = per["n_top"] > 1
    sel = select_cluster(votes)
    nc = sel.merge(per[["nodeid", "n_clusters", "tied"]], on="nodeid")
    nc["cluster_id"] = nc["cluster_id"].astype(str)
    alt = cnt[cnt["nodeid"].isin(per.loc[per["n_clusters"] > 1, "nodeid"])].copy()
    alt["cluster_id"] = alt["cluster_id"].astype(str)
    alt = alt.merge(nc[["nodeid", "cluster_id"]].assign(selected=True), on=["nodeid", "cluster_id"], how="left")
    alt["selected"] = alt["selected"].fillna(False).astype(bool)
    return (nc.rename(columns={"nodeid": "node_id"}),
            alt.rename(columns={"nodeid": "node_id"}).reset_index(drop=True))


def build_mapping(conn, full: pd.DataFrame, clusters: pd.DataFrame) -> tuple[dict, dict]:
    """Build the mapping tables for one resolution (``full``, ``clusters`` from
    ``splink_bridge._resolve``). Returns ``(tables, report)``."""
    cand = pd.read_sql(_NODE_OBS_SQL, conn)
    node_obs, node_alt = node_observation_tables(cand)

    iobs = _with_obs_id(pd.read_sql(_IDENTITY_OBS_SQL, conn))
    want = full[["unique_id", "bbls"]].explode("bbls").rename(columns={"bbls": "bbl"}).dropna()
    ident_obs = want.merge(iobs[["unique_id", "bbl", "observation_id", "n_tied"]],
                           on=["unique_id", "bbl"], how="left", indicator=True)
    not_found = int((ident_obs["_merge"] == "left_only").sum())
    ident_obs = (ident_obs[ident_obs["_merge"] == "both"].drop(columns="_merge")
                 .rename(columns={"unique_id": "identity_id"}))
    ident_obs["tied_registration"] = ident_obs.pop("n_tied") > 1
    ident_obs = ident_obs.drop_duplicates(["identity_id", "bbl", "observation_id"]).reset_index(drop=True)

    votes = node_cluster_votes(conn, full, clusters)
    node_cl, node_cl_alt = node_cluster_tables(votes)
    matches = (votes[["nodeid", "unique_id", "bbl"]].drop_duplicates()
               .rename(columns={"nodeid": "node_id", "unique_id": "identity_id"}).reset_index(drop=True))
    ident_cl = clusters[["unique_id", "cluster_id"]].rename(columns={"unique_id": "identity_id"}).copy()
    ident_cl["cluster_id"] = ident_cl["cluster_id"].astype(str)

    ids = pd.concat([node_obs["selected_observation_id"].dropna(), node_alt["observation_id"],
                     ident_obs["observation_id"]]).drop_duplicates()
    observations = pd.DataFrame({"observation_id": ids.to_numpy()})
    parts = observations["observation_id"].str.split(":", expand=True).astype(int)
    observations["registration_id"], observations["registration_contact_id"], observations["k"] = (
        parts[0], parts[1], parts[2])
    observations = observations.sort_values("observation_id").reset_index(drop=True)

    n_nodes = int(node_cl["node_id"].nunique())
    all_nodes = int(pd.read_sql("SELECT count(*) AS n FROM landlords_with_connections", conn)["n"][0])
    per_node_ids = matches.groupby("node_id")["identity_id"].nunique()
    report = {
        "lwc_nodes": all_nodes,
        "node_bbl_rows": len(node_obs),
        "node_bbls_without_candidate": int((node_obs["n_candidates"] == 0).sum()),
        "node_bbls_unique_contact": int((node_obs["n_candidates"] == 1).sum()),
        "node_bbls_ambiguous_contact": int(node_obs["ambiguous"].sum()),
        "nodes_matched_to_an_identity": n_nodes,
        "nodes_unmatched": all_nodes - n_nodes,
        "nodes_with_2plus_identities": int((per_node_ids >= 2).sum()),
        "nodes_straddling_2plus_clusters": int((node_cl["n_clusters"] >= 2).sum()),
        "straddling_nodes_tied": int(((node_cl["n_clusters"] >= 2) & node_cl["tied"]).sum()),
        "identities": int(full["unique_id"].nunique()),
        "identity_bbl_pairs": len(want),
        "identity_bbl_pairs_without_observation": not_found,
        "identity_bbl_pairs_on_tied_registration": int(ident_obs.loc[ident_obs["tied_registration"],
                                                                     ["identity_id", "bbl"]].drop_duplicates().shape[0]),
        "identities_without_node": int(len(set(full["unique_id"]) - set(matches["identity_id"]))),
        "observations": len(observations),
    }
    tables = {
        "observations": observations,
        "node_observations": node_obs,
        "node_observation_alternatives": node_alt,
        "identity_observations": ident_obs,
        "node_identity_matches": matches,
        "node_cluster": node_cl,
        "node_cluster_alternatives": node_cl_alt,
        "identity_clusters": ident_cl,
    }
    return tables, report


def write_mapping(tables: dict, report: dict, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(os.path.join(out_dir, f"{name}.csv"), index=False)
    with open(os.path.join(out_dir, "mapping_report.json"), "w") as f:
        json.dump(report, f, indent=2)


def main() -> None:  # pragma: no cover - needs the database and a Splink fit (~5 min)
    import argparse

    from bor.db import pg_conn
    from bor.splink_bridge import DEFAULT_THRESHOLD, _resolve

    ap = argparse.ArgumentParser(description="Build the node/identity -> HPD contact mapping tables.")
    ap.add_argument("out_dir")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()
    conn = pg_conn()
    try:
        full, clusters = _resolve(conn, args.threshold)
        tables, report = build_mapping(conn, full, clusters)
    finally:
        conn.close()
    write_mapping(tables, report, args.out_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
