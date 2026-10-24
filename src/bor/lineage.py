"""Mapping tables from resolution nodes to the HPD records behind them (W0 of the KG handoff).

bor's nodes are ``landlords_with_connections`` (lwc) rows and its identity edges come from nlr
identities (``unique_id`` = md5 of a person owner contact's kind, name and address). The KG needs
to get from either back to HPD contact records. This module builds the lookup tables and a report
of what does not map cleanly; see docs/w0-findings.md for the measurements behind the design.

Tables (HPD ids and BBLs only; the names they stand for are in :mod:`bor.names`):

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
* ``decision_events`` / ``decision_support`` — the identity-layer decisions (:mod:`bor.identity_events`).

**Opaque ids.** nlr's identity id (and the cluster ids Splink derives from it) is an md5 of a
person's name and address. The release uses run-local opaque ids instead (``I0000001`` for
identities, ``C0000001`` for clusters, ``BC0000001`` for base clusters), numbered by the identity
(or, for a cluster, its smallest member), so the same partition always gets the same ids; see
:mod:`bor.identity_events`. The KG derives its own identity key from the observations (KG notes
0006 and 0007).

**Observation id** ``"{registrationid}:{registrationcontactid}:{k}"``. HPD's contact id is not
unique (1,028 repeated pairs, 616 with differing content), so ``k`` is the 0-based rank of the
row's content digest among the distinct contents sharing the (registration, contact id) pair; it
is 0 for the 99.9% of pairs that are unique. The digest is :data:`DIGEST_SQL`; it is used only to
number, never exported, and is not normative: consumers join on (registration, contact id) and
treat a pair with ``pair_variants > 1`` as ambiguous, attaching evidence to every row of the pair.

**Identity side.** ``identity_observations`` comes from the ``sources`` nlr records for each identity
(``resolve(..., capture=True)``): the contacts the extraction actually used, including for BBLs
where several registrations tied. The decision tables are built by :mod:`bor.identity_events`.
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

# Every (registration, contact id, k): how a source contact maps to observation ids.
_CONTACT_KEYS_SQL = f"""
WITH {_CONTACT_OBS}
SELECT registrationid, registrationcontactid, k FROM contact_obs
"""

# BBLs where more than one registration is tied for most recent under nlr's ordering (its pick
# among them is arbitrary; nlr records the one it used, but a reader may want to know).
_TIED_SQL = """
SELECT bbl FROM (
  SELECT btrim(r.bbl) AS bbl,
         dense_rank() OVER (PARTITION BY btrim(r.bbl)
                            ORDER BY r.registrationenddate DESC NULLS LAST,
                                     r.lastregistrationdate DESC NULLS LAST) AS rk
  FROM hpd_registrations r WHERE r.bbl IS NOT NULL) t
WHERE rk = 1 GROUP BY bbl HAVING count(*) > 1
"""

# Contact ids that repeat with differing content, over every contact type.
_PAIR_VARIANTS_SQL = f"""
SELECT registrationid, registrationcontactid, count(*) AS pair_variants
FROM (SELECT DISTINCT registrationid, registrationcontactid, type, firstname, middleinitial, lastname,
             corporationname, businesshousenumber, businessstreetname, businessapartment, businesscity,
             businessstate, businesszip FROM hpd_contacts) d
GROUP BY 1, 2 HAVING count(*) > 1
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


def build_mapping(conn, res) -> tuple[dict, dict]:
    """Build the lineage and identity-layer tables for one resolution, an nlr ``Resolution`` from
    ``bor.splink_bridge.resolve(..., capture=True)``. Returns ``(tables, report)``."""
    if res.trace is None:
        raise ValueError("build_mapping needs a Resolution captured with capture=True")
    import bor
    from bor import identity_events as ie

    full, clusters = res.identities, res.clusters
    cand = pd.read_sql(_NODE_OBS_SQL, conn)
    node_obs, node_alt = node_observation_tables(cand)

    keys = pd.read_sql(_CONTACT_KEYS_SQL, conn)
    tied = set(pd.read_sql(_TIED_SQL, conn)["bbl"])
    imap = ie.identity_ids(full, res.excluded)
    cmap = ie.cluster_ids(clusters, "C")
    bmap = ie.cluster_ids(res.base_clusters, "BC")
    ident_obs = ie.identity_observations(full, res.excluded, imap, keys, tied)
    ident_cl = ie.identity_clusters(clusters, res.base_clusters, imap, cmap, bmap)
    events, support = ie.decision_tables(
        res.trace, res.excluded, clusters, res.base_clusters, res.params["threshold"], imap, cmap, bmap,
        keys, ie.nlr_rule_version(), f"bor-{bor.__version__}")

    want = full[["unique_id", "bbls"]].explode("bbls").dropna()
    want_keys = set(zip(want["unique_id"].map(imap), want["bbls"]))
    not_found = len(want_keys - set(zip(ident_obs["identity_id"], ident_obs["bbl"])))

    votes = node_cluster_votes(conn, full, clusters)
    node_cl, node_cl_alt = node_cluster_tables(votes)
    node_cl["cluster_id"] = node_cl["cluster_id"].map(cmap)
    node_cl_alt["cluster_id"] = node_cl_alt["cluster_id"].map(cmap)
    matches = (votes[["nodeid", "unique_id", "bbl"]].drop_duplicates()
               .rename(columns={"nodeid": "node_id", "unique_id": "identity_id"}).reset_index(drop=True))
    matches["identity_id"] = matches["identity_id"].map(imap)

    ids = pd.concat([node_obs["selected_observation_id"].dropna(), node_alt["observation_id"],
                     ident_obs["observation_id"], support["support_id"]]).drop_duplicates()
    observations = pd.DataFrame({"observation_id": ids.to_numpy()})
    parts = observations["observation_id"].str.split(":", expand=True).astype(int)
    observations["registration_id"], observations["registration_contact_id"], observations["k"] = (
        parts[0], parts[1], parts[2])
    pv = pd.read_sql(_PAIR_VARIANTS_SQL, conn).rename(columns={
        "registrationid": "registration_id", "registrationcontactid": "registration_contact_id"})
    observations = observations.merge(pv, on=["registration_id", "registration_contact_id"], how="left")
    observations["pair_variants"] = observations["pair_variants"].fillna(1).astype(int)
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
        "identities_excluded": int(len(res.excluded)),
        "identity_bbl_pairs": len(want_keys),
        "identity_bbl_pairs_without_observation": not_found,
        "identity_bbl_pairs_on_tied_registration": int(
            ident_obs.loc[ident_obs["tied_registration"], ["identity_id", "bbl"]].drop_duplicates().shape[0]),
        "identities_without_node": int(len(set(full["unique_id"].map(imap)) - set(matches["identity_id"]))),
        "decision_events": len(events),
        "decision_events_by_outcome": {f"{st}/{oc}": int(n) for (st, oc), n in
                                       events.groupby(["stage", "outcome"]).size().items()},
        "decision_support": len(support),
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
        "decision_events": events,
        "decision_support": support,
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
    from bor.splink_bridge import DEFAULT_THRESHOLD, resolve

    ap = argparse.ArgumentParser(description="Build the node/identity -> HPD contact mapping tables.")
    ap.add_argument("out_dir")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()
    conn = pg_conn()
    try:
        res = resolve(conn, args.threshold, capture=True)
        tables, report = build_mapping(conn, res)
    finally:
        conn.close()
    write_mapping(tables, report, args.out_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
