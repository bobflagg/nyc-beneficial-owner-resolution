"""Identity-layer release tables from an nlr :class:`~nlr.Resolution` run with ``capture=True``.

nlr records the decisions behind its clusters in its own vocabulary (``trace``); this module
translates them into the release contract (docs/release-contract.md): ``decision_events`` and
``decision_support`` for the identity layer, ``identity_clusters`` with both cluster levels, and
``identity_observations`` straight from the contacts nlr actually used. See docs/w2-design.md.

Mapping of nlr records to events:

=========================================  ====================================================
accepted pair                              ``identity.splink_base``, rule ``splink_model``, with
                                           score and threshold, on the final cluster
first-name / common-name veto              rejected, rule and reason of the same name, with the
                                           score (above the threshold: the gate overruled it)
address evidence masked                    ``masked``, ``address_evidence_masked``
curated exclusion                          ``excluded``, ``curated_exclusion``
accepted shared-corporation merge          ``identity.splink_feedback``, between two *base
                                           clusters*, no pair score, on the final cluster
rejected shared-corporation merge          rejected, ``shared_company_*`` reason, rule
                                           ``shared_company_guard``
=========================================  ====================================================

Identity-endpoint events cite their contacts through ``identity_observations``; only the
shared-corporation events carry ``decision_support`` rows (the contacts that carry the
corporation), since those contacts are not any identity's own.
"""
from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version

import pandas as pd

FEEDBACK_REASONS = {
    "name_not_rare": "shared_company_name_not_rare",
    "first_name_conflict": "shared_company_first_name_conflict",
    "degree_cap": "shared_company_degree_cap",
    "degree_unknown": "shared_company_degree_unknown",
}

EVENT_COLUMNS = ["decision_id", "layer", "stage", "subject_type", "subject_id", "counterpart_type",
                 "counterpart_id", "outcome", "reason_code", "rule", "rule_version", "score", "threshold",
                 "cluster_id", "detail"]
SUPPORT_COLUMNS = ["decision_id", "support_type", "support_id", "role"]


def nlr_rule_version() -> str:
    try:
        return f"nlr-{version('nyc-landlord-resolution')}"
    except PackageNotFoundError:  # pragma: no cover
        return "nlr-unknown"


def cluster_ids(clusters: pd.DataFrame, prefix: str) -> dict:
    """Run-local opaque ids for a clustering: ``{label: prefix + 7 digits}``, numbered by each
    cluster's smallest member identity. Splink's label is a union-find root that varies from run to
    run even when the partition is identical, so numbering by label would not be reproducible."""
    smallest = clusters.assign(_cid=clusters["cluster_id"].astype(str)).groupby("_cid")["unique_id"].min()
    return {c: f"{prefix}{i:07d}" for i, c in enumerate(smallest.sort_values().index, 1)}


def identity_ids(identities: pd.DataFrame, excluded: pd.DataFrame | None = None) -> dict:
    """``{unique_id: 'I0000001'}`` over the resolved identities and those a curated list removed,
    in sorted ``unique_id`` order."""
    ids = set(identities["unique_id"]) | (set(excluded["unique_id"]) if excluded is not None else set())
    return {u: f"I{i:07d}" for i, u in enumerate(sorted(ids), 1)}


def parse_sources(identities: pd.DataFrame) -> pd.DataFrame:
    """``(unique_id, bbl, registrationid, registrationcontactid)`` from the ``sources`` column."""
    s = identities[["unique_id", "sources"]].explode("sources").dropna(subset=["sources"])
    parts = s["sources"].str.split(":", expand=True)
    out = pd.DataFrame({"unique_id": s["unique_id"].to_numpy(), "bbl": parts[0].to_numpy(),
                        "registrationid": parts[1].astype("int64").to_numpy(),
                        "registrationcontactid": parts[2].astype("int64").to_numpy()})
    return out.drop_duplicates().reset_index(drop=True)


def observation_id(registrationid, registrationcontactid, k) -> str:
    return f"{int(registrationid)}:{int(registrationcontactid)}:{int(k)}"


def with_observation_ids(contacts: pd.DataFrame, keys: pd.DataFrame) -> pd.DataFrame:
    """Attach ``observation_id`` to rows with ``registrationid`` and ``registrationcontactid``.

    ``keys`` lists every ``k`` of each (registration, contact id) pair. Following the contract, a
    pair with several contents is ambiguous and the row is attached to every one of them."""
    m = contacts.merge(keys, on=["registrationid", "registrationcontactid"], how="left")
    m = m.dropna(subset=["k"])
    m["observation_id"] = [observation_id(r, c, k) for r, c, k in
                           zip(m["registrationid"], m["registrationcontactid"], m["k"])]
    return m


def identity_observations(res_identities: pd.DataFrame, excluded: pd.DataFrame, imap: dict,
                          keys: pd.DataFrame, tied_bbls: set) -> pd.DataFrame:
    """Which HPD contacts, per BBL, each identity aggregates (including curated exclusions)."""
    both = pd.concat([res_identities, excluded], ignore_index=True)
    src = with_observation_ids(parse_sources(both), keys)
    out = pd.DataFrame({
        "identity_id": src["unique_id"].map(imap).to_numpy(), "bbl": src["bbl"].to_numpy(),
        "observation_id": src["observation_id"].to_numpy(),
        "tied_registration": src["bbl"].isin(tied_bbls).to_numpy()})
    return out.drop_duplicates().reset_index(drop=True)


def identity_clusters(res_clusters: pd.DataFrame, res_base: pd.DataFrame, imap: dict, cmap: dict,
                      bmap: dict) -> pd.DataFrame:
    m = res_clusters[["unique_id", "cluster_id"]].merge(
        res_base[["unique_id", "cluster_id"]].rename(columns={"cluster_id": "base"}), on="unique_id")
    return pd.DataFrame({
        "identity_id": m["unique_id"].map(imap).to_numpy(),
        "cluster_id": m["cluster_id"].astype(str).map(cmap).to_numpy(),
        "base_cluster_id": m["base"].astype(str).map(bmap).to_numpy()})


def _detail(**kv) -> str | None:
    kv = {k: v for k, v in kv.items() if v is not None and not (isinstance(v, float) and pd.isna(v))}
    return json.dumps(kv, sort_keys=True) if kv else None


def decision_tables(trace: dict, excluded: pd.DataFrame, res_clusters: pd.DataFrame,
                    res_base: pd.DataFrame, threshold: float, imap: dict, cmap: dict, bmap: dict,
                    keys: pd.DataFrame, nlr_version: str, bor_version: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(decision_events, decision_support)`` for the identity layer."""
    final_of = dict(zip(res_clusters["unique_id"], res_clusters["cluster_id"].astype(str)))
    base_final = {}
    for u, b in zip(res_base["unique_id"], res_base["cluster_id"].astype(str)):
        base_final.setdefault(b, final_of[u])

    def blank(**kw):
        row = dict.fromkeys(EVENT_COLUMNS)
        row.update(layer="identity", **kw)
        return row

    rows = []
    for r in trace["pairs"].itertuples():
        accepted = r.outcome == "accepted"
        rule = "splink_model" if accepted else r.reason
        extra = _detail(name_rarity=getattr(r, "name_rarity", None), same_address=getattr(r, "same_address", None)) \
            if r.reason == "common_name_veto" else None
        rows.append(blank(stage="identity.splink_base", subject_type="identity", subject_id=imap[r.unique_id_l],
                          counterpart_type="identity", counterpart_id=imap[r.unique_id_r], outcome=r.outcome,
                          reason_code=None if accepted else r.reason, rule=rule, rule_version=nlr_version,
                          score=float(r.match_probability), threshold=threshold,
                          cluster_id=cmap[final_of[r.unique_id_l]] if accepted else None, detail=extra))
    for r in trace["address_masked"].itertuples():
        rows.append(blank(stage="identity.splink_base", subject_type="identity", subject_id=imap[r.unique_id],
                          outcome="masked", reason_code="address_evidence_masked",
                          rule="splink_address_evidence_mask", rule_version=nlr_version,
                          detail=_detail(addr_degree=int(r.addr_degree))))
    for u in excluded["unique_id"]:
        rows.append(blank(stage="identity.curated", subject_type="identity", subject_id=imap[u],
                          outcome="excluded", reason_code="curated_exclusion", rule="curated_owner_list",
                          rule_version=bor_version))
    for r in trace["feedback"].itertuples():
        accepted = r.outcome == "accepted"
        rows.append(blank(stage="identity.splink_feedback", subject_type="base_cluster",
                          subject_id=bmap[r.base_cluster_l], counterpart_type="base_cluster",
                          counterpart_id=bmap[r.base_cluster_r], outcome=r.outcome,
                          reason_code=None if accepted else FEEDBACK_REASONS[r.reason],
                          rule="shared_company_feedback" if accepted else "shared_company_guard",
                          rule_version=nlr_version,
                          cluster_id=cmap[base_final[r.base_cluster_l]] if accepted else None,
                          detail=_detail(n_shared_corporations=len(r.shared_corps))))

    events = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    # Deterministic numbering: the opaque ids are functions of the partition, so are these.
    order = events.sort_values(["stage", "outcome", "subject_id", "counterpart_id", "rule"],
                               na_position="first", kind="stable").index
    events = events.loc[order].reset_index(drop=True)
    events["decision_id"] = [f"D{i:07d}" for i in range(1, len(events) + 1)]

    # Shared-corporation events cite the contacts that carry the corporation.
    fb = events[events["stage"] == "identity.splink_feedback"].copy()
    fb["_pair"] = list(zip(fb["subject_id"], fb["counterpart_id"]))
    pair_to_decision = {}
    for d, a, b in zip(fb["decision_id"], fb["subject_id"], fb["counterpart_id"]):
        pair_to_decision[tuple(sorted((a, b)))] = d
    src = trace["feedback_sources"]
    support = pd.DataFrame(columns=SUPPORT_COLUMNS)
    if len(src):
        s = with_observation_ids(src.rename(columns={}), keys)
        s["decision_id"] = [pair_to_decision[tuple(sorted((bmap[a], bmap[b])))]
                            for a, b in zip(s["base_cluster_l"], s["base_cluster_r"])]
        support = pd.DataFrame({"decision_id": s["decision_id"].to_numpy(), "support_type": "observation",
                                "support_id": s["observation_id"].to_numpy(), "role": "shared_company"})
        support = support.drop_duplicates().sort_values(SUPPORT_COLUMNS).reset_index(drop=True)
    return events, support
