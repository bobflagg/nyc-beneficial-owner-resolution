"""Build a release directory: the tables bor produces today, plus a manifest that checks them.

    uv run python -m bor.release build ./release --snapshot-id <id> [--as-of 2026-10-21] [--require-clean]
        [--eval-dir eval_out --gold-status human_llm_provisional]
    uv run python -m bor.release validate ./release

``build`` resolves identities with decision capture, writes the lineage and identity-layer tables,
then writes ``manifest.json`` (source fingerprints, code identity, parameters, checksums) and
validates the result against the contract. Group, evidence and network tables are added by later work
packages; until then a release is partial, and says so in ``diagnostics``.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date
from pathlib import Path

from bor import manifest as mf
from bor.metrics import load_evaluation
from bor.release_docs import write_data_md
from bor.release_schema import ADJUDICATION_STATUSES, ReleaseInputError
from bor.release_validate import read_release, validate_release


def build_release(conn, out_dir, *, snapshot_id: str,
                  as_of: date | None = None, run_id: str | None = None, threshold: float | None = None,
                  require_clean: bool = False, resolution=None, evaluation: dict | None = None,
                  gold_status: str = "none") -> dict:
    """Write the release into ``out_dir`` and return ``{"manifest", "violations"}``. Pass a
    ``resolution`` captured with ``splink_bridge.resolve(..., capture=True)`` to reuse one, and an
    ``evaluation`` (``bor.metrics.load_evaluation``) with the ``gold_status`` of its gold to publish the
    method metrics; without one, ``method_metrics`` says no stage was evaluated."""
    from bor.metrics import method_metrics_table
    from bor import deed_edges
    from bor.lineage import build_mapping
    from bor.splink_bridge import DEFAULT_THRESHOLD, resolve

    as_of = as_of or date.today()
    run_id = run_id or f"{as_of.isoformat()}-{uuid.uuid4().hex[:8]}"      # fixed first: assertion keys embed it
    if evaluation and gold_status == "none":
        raise ReleaseInputError("say who produced the gold (--gold-status) when supplying an evaluation (--eval-dir)")
    basis = mf.snapshot_basis(conn)                                       # refuse a wrong snapshot id now, not
    mf.check_snapshot_id(snapshot_id, mf.snapshot_date(basis))            # after ten minutes of work
    code = mf.code_state()
    if require_clean:
        dirty = [k for k, v in code.items() if v["dirty"] is not False]
        if dirty:
            raise ReleaseInputError(f"refusing to build a release from an unclean or unidentified tree: {dirty}")

    res = resolution or resolve(conn, DEFAULT_THRESHOLD if threshold is None else threshold, capture=True)
    tables, report = build_mapping(conn, res)
    tables, deed_report, deed_edge_frame = add_deed_layer(conn, tables, as_of)
    tables, portfolio_report = add_owner_portfolio_layer(conn, tables, deed_edge_frame, as_of, run_id)
    tables, network_report = add_operational_network_layer(conn, tables, run_id)
    tables, absence_report = add_absence_summary(conn, tables)
    tables, names_report = add_names(conn, tables, res)
    tables["method_metrics"] = method_metrics_table(evaluation, gold_status)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False)

    manifest = mf.build_manifest(
        conn, snapshot_id=snapshot_id, as_of=as_of, run_id=run_id, basis=basis,
        resolution_params=res.params,
        artifacts={name: ("representative" if name == "group_witness" else "complete") for name in tables},
        diagnostics={"partial": "lineage, identity layer, deed evidence, and both layers' groups with their "
                                "paths, the per-lot absence summary, the method metrics and the names",
                     "evaluation": None if not evaluation else {
                         "frame": (evaluation.get("frame") or {}).get("frame"),
                         "metrics_sha256": evaluation["sha256"], "gold_status": gold_status},
                     "latest_deed_ties": deed_edges.latest_deed_ties(conn, as_of),
                     "mapping": report, "deed": deed_report, "owner_portfolio": portfolio_report,
                     "operational_network": network_report, "absence": absence_report,
                     "names": names_report})
    write_data_md(out, manifest, tables)            # before the checksums, so DATA.md is covered by them
    mf.write_manifest(out, manifest)

    loaded, written = read_release(str(out))
    return {"manifest": written, "violations": validate_release(loaded, written, path=str(out))}


def add_deed_layer(conn, tables: dict, as_of: date | None) -> tuple[dict, dict, object]:
    """Run the deed layer with decision capture and add its evidence and decisions to ``tables``
    (the deed events join the identity events in ``decision_events``). Also returns the deed edges,
    so the Owner Portfolios reuse this run."""
    import pandas as pd

    import bor
    from bor import deed_edges, deed_events

    trace: dict = {}
    deed_edge_frame = deed_edges.deed_edges(conn, as_of=as_of, trace=trace)
    new, report = deed_events.deed_tables(conn, trace, f"bor-{bor.__version__}")
    out = dict(tables)
    out["evidence_items"], out["evidence_members"] = new["evidence_items"], new["evidence_members"]
    out["decision_events"] = pd.concat([tables["decision_events"], new["deed_events"]], ignore_index=True)
    out["decision_support"] = pd.concat([tables["decision_support"], new["deed_support"]], ignore_index=True)
    ids = pd.concat([out["decision_support"].loc[out["decision_support"]["support_type"] == "observation",
                                                "support_id"]])
    assert set(ids) <= set(out["observations"]["observation_id"])
    return out, report, deed_edge_frame


def add_owner_portfolio_layer(conn, tables: dict, deed_edge_frame, as_of: date | None, run_id: str
                              ) -> tuple[dict, dict]:
    """Owner Portfolios, lots and witness paths, built from the identity resolution and the deed
    edges already in ``tables`` (one Splink fit and one deed run per release)."""
    import pandas as pd

    import bor
    from bor import curated_owners, group_events, group_tables
    from bor.owner_portfolios import resolve_owner_portfolios

    nc = tables["node_cluster"].rename(columns={"node_id": "nodeid"})[["nodeid", "cluster_id"]]
    drop_trace: dict = {}
    portfolios = resolve_owner_portfolios(conn, as_of=as_of, node_cluster_frame=nc, deed_edge_frame=deed_edge_frame,
                                          trace=drop_trace)

    version = f"bor-{bor.__version__}"
    named = group_tables.named_link_sets(curated_owners.curated_node_groups(conn), group_tables.llc_sources(conn),
                                         version, version)
    link_sets = (group_tables.cluster_link_sets(tables["node_cluster"], tables["node_identity_matches"],
                                                tables["identity_clusters"])
                 + group_tables.deed_link_sets(tables["evidence_items"], tables["evidence_members"])
                 + named.link_sets)
    new, report = group_tables.owner_portfolio_tables(portfolios, link_sets, run_id)
    out = dict(tables)
    out.update(new)
    out["link_sets"], out["link_set_members"] = named.sets, named.members
    events = group_events.portfolio_events(portfolios, drop_trace.get("dropped", []), version)
    out["decision_events"] = pd.concat([tables["decision_events"], events], ignore_index=True)
    report.update({"groups_dropped_as_coop_dominated": len(drop_trace.get("dropped", [])),
                   "lots_left_out_of_a_footprint": int((events["reason_code"] == "coop_condo_excluded").sum())})
    report.update({"curated_sets": int((named.sets["stage"] == "identity.curated").sum()),
                   "registered_llc_sets": int((named.sets["stage"] == "identity.registered_llc").sum())})
    return out, report


def add_operational_network_layer(conn, tables: dict, run_id: str) -> tuple[dict, dict]:
    """The Operational Network: the complete weighted graph, its components and splits, the networks and
    a path inside each, plus the masked aggregator addresses. Built from the same identity resolution."""
    import pandas as pd

    from bor import manifest as mf
    from bor import network_tables, operational_network as on

    nc = tables["node_cluster"].rename(columns={"node_id": "nodeid"})[["nodeid", "cluster_id"]]
    trace: dict = {}
    networks = on.resolve_operational_networks(conn, node_cluster_frame=nc, trace=trace)
    new, report = network_tables.network_tables(networks, trace, run_id)
    masked, masked_nodes, mask_events = network_tables.masked_tables(
        on.aggregator_addresses(conn), mf.normalizer_versions()["business_address_mask"], on.MAX_ADDR_DEGREE)

    out = dict(tables)
    for name in ("groups", "group_members", "group_bbls", "group_witness"):
        out[name] = pd.concat([tables[name], new[name]], ignore_index=True)
    for name in ("network_edges", "network_membership", "split_attempts"):
        out[name] = new[name]
    out["masked_addresses"], out["masked_address_nodes"] = masked, masked_nodes
    out["decision_events"] = pd.concat([tables["decision_events"], mask_events], ignore_index=True)
    report["masked_addresses"] = len(masked)
    report["nodes_at_masked_addresses"] = len(masked_nodes)
    return out, report


def add_absence_summary(conn, tables: dict) -> tuple[dict, dict]:
    """``bbl_status``: for every lot in the PLUTO snapshot (and every lot that is in a node or a group),
    in each layer, whether it is in a group and, if not, the primary reason."""
    from bor import absence

    universe = [r[0] for r in _query(conn, "SELECT DISTINCT trim(bbl) FROM pluto_latest WHERE bbl IS NOT NULL")]
    registered = [r[0] for r in _query(conn, "SELECT DISTINCT trim(bbl) FROM hpd_registrations WHERE bbl IS NOT NULL")]
    status = absence.bbl_status_table(universe, registered, tables)
    out = dict(tables)
    out["bbl_status"] = status
    by = status.groupby(["layer", "status"]).size()
    reasons = status[status["status"] != "in_group"].groupby(["layer", "reason_code"]).size()
    return out, {"pluto_lots": len(universe), "lots_with_status": int(status["bbl"].nunique()),
                 "status": {f"{l}/{s}": int(n) for (l, s), n in by.items()},
                 "reasons": {f"{l}/{c}": int(n) for (l, c), n in reasons.items()}}


def add_names(conn, tables: dict, res) -> tuple[dict, dict]:
    """Add the name tables (:mod:`bor.names`): who the ids of the other tables stand for, as filed."""
    from bor import names

    new, report = names.name_tables(conn, tables, res)
    return {**tables, **new}, report


def _query(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    return cur.fetchall()


def main() -> None:  # pragma: no cover - needs the database
    ap = argparse.ArgumentParser(prog="bor.release")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("out_dir")
    b.add_argument("--snapshot-id", required=True,
                   help="<source>-<YYYY-MM-DD>[-rN]; the date must be the data's (the build checks it)")
    b.add_argument("--as-of", type=date.fromisoformat, help="deed cut-off, YYYY-MM-DD (default today)")
    b.add_argument("--run-id")
    b.add_argument("--threshold", type=float)
    b.add_argument("--require-clean", action="store_true",
                   help="refuse to build unless bor and nlr are clean git checkouts")
    b.add_argument("--eval-dir", help="directory with the evaluation's metrics.json (bor.eval.score) to publish")
    b.add_argument("--gold-status", default="none", choices=ADJUDICATION_STATUSES,
                   help="who produced the gold behind --eval-dir (required with it)")
    v = sub.add_parser("validate")
    v.add_argument("path")
    args = ap.parse_args()

    if args.cmd == "validate":
        tables, manifest = read_release(args.path)
        found = validate_release(tables, manifest, path=args.path)
    else:
        from bor.db import pg_conn
        conn = pg_conn()
        try:
            r = build_release(conn, args.out_dir, snapshot_id=args.snapshot_id,
                              as_of=args.as_of, run_id=args.run_id,
                              threshold=args.threshold, require_clean=args.require_clean,
                              evaluation=load_evaluation(args.eval_dir) if args.eval_dir else None,
                              gold_status=args.gold_status)
        except ReleaseInputError as e:                     # a caller mistake: one line, not a traceback
            sys.exit(f"error: {e}")
        finally:
            conn.close()
        found = r["violations"]
        m = r["manifest"]
        print(json.dumps({k: m[k] for k in ("run_id", "snapshot_id", "effective_date", "bor_revision",
                                            "nlr_revision", "source_tree_hash")}, indent=2))
    for x in found:
        print(x)
    errors = [x for x in found if x.severity == "error"]
    print(f"{len(errors)} errors, {len(found) - len(errors)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
