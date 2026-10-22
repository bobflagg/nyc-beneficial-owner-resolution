"""The ``method_metrics`` table, from the evaluation (W7).

    uv run python -m bor.metrics <eval_dir> [--gold-status human_llm_provisional]

A release says how well each of its link-creating stages did on the evaluation sample, so a consumer can
show a published estimate beside a link without computing one. Nothing here is estimated: the table is a
transcription of ``metrics.json`` (``bor.eval.score``), with the counts behind each proportion, and the
numbers are stored exactly as the scorer published them.

What a row is:

* **Link precision** (``precision_strict``, ``precision_inclusive``) belongs to a stage. The sample is of
  node pairs the method linked, judged by a human reader to be the same owner or not. *Strict* counts
  only cross-source corroboration (C1); *inclusive* adds same-source-verified pairs (C2).
* **Split precision** (``split_precision``) belongs to a sampled population the method keeps apart (pairs at
  a masked aggregator address; hard negatives), not to a stage. It is the share judged to be different owners.
* **One row per stratum.** No pooled figure: strata are sampled at very different rates, and a pooled number
  would hide that the weakest evidence is also the least certain.
* **Every link-creating stage has a row.** A stage the evaluation did not draw has null estimates and a note
  saying why; a missing row would read as "fine".

A precision is *not a link probability*. It is the share of sampled pairs judged correct, in a stratum,
on this snapshot; a group's path chains several pairs, so no step's precision is the group's. Every row is
``provisional`` unless the gold behind it is a blind human adjudication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from bor.release_schema import ADJUDICATION_STATUSES, LINK_STAGES, TABLES, ReleaseInputError

COLUMNS = [c.name for c in TABLES["method_metrics"].columns]
CONFIDENCE = 0.95

STRATUM_STAGE = {"S1a_deed_held": "deed.held_since", "S1b_deed_linked_successor": "deed.linked_successor",
                 "S2_model": "identity.splink_base"}
STRATUM_SCOPE = {"S3_aggregator": "method.aggregator_splits", "S4_hard_neg": "method.hard_negatives"}

POPULATION = {
    "S1a_deed_held": "node pairs joined by one ACRIS deed that is still each parcel's latest",
    "S1b_deed_linked_successor": "node pairs joined by one ACRIS deed whose parcels were later re-titled by the "
                                 "same grantee into single-purpose LLCs",
    "S2_model": "node pairs inside one resolved identity cluster (scored base matches and shared-company "
                "merges together; the sample did not separate them)",
    "S3_aggregator": "node pairs that share a masked aggregator business address and that the method keeps in "
                     "different Owner Portfolios",
    "S4_hard_neg": "node pairs that share a surname, are linked by no signal, and are in different Owner "
                   "Portfolios",
}
STRATUM_NOTE = {
    "S2_model": "Pools pairs linked directly with pairs linked through a shared-company merge: no estimate for "
                "identity.splink_feedback alone.",
    "S3_aggregator": "Estimates how often a pair the method keeps apart at a masked address really is two owners "
                     "(the aggregator masks, rules aggregator_address_mask and splink_address_evidence_mask).",
    "S4_hard_neg": "1 minus this estimates how often a surname-sharing pair the method keeps apart is really the "
                   "same owner, on this hard population only; it is not recall overall.",
}
STATUS_TEXT = {
    "none": "no gold",
    "synthetic": "made-up values for a test fixture",
    "human_llm_provisional": "one human annotator, an LLM second reader and an LLM-run resolution of their "
                             "disagreements; blind human re-adjudication is pending",
    "blind_human": "blind human adjudication with human arbitration of disagreements",
}
UNEVALUATED = {
    "identity.splink_base": "No evaluation was supplied to this build.",
    "identity.splink_feedback": "Not evaluated on its own. The identity sample draws pairs from inside resolved "
                                "clusters, which include shared-company merges, so its estimate pools them; no "
                                "pair was drawn to isolate this stage. It is the weakest identity evidence.",
    "identity.curated": "Not evaluated: a hand-verified owner list, not a scored match.",
    "identity.registered_llc": "Not evaluated: no stratum was drawn for links through a shared registered owner entity.",
    "deed.held_since": "No evaluation was supplied to this build.",
    "deed.linked_successor": "No evaluation was supplied to this build.",
    "network.identity": "Not evaluated separately: an identity edge repeats a resolved-owner link, so the identity "
                        "and deed rows are its evidence.",
    "network.name": "Not evaluated. The evaluation asked whether a pair is the same owner; an Operational Network "
                    "claims operational linkage, which is a different question, and no evaluation of it exists.",
    "network.address": "Not evaluated, for the same reason as network.name.",
}
LINK_NOTE = ("A precision on a stratified sample of pairs, not the probability that any one link in this release "
             "is correct; a group's path chains several pairs.")


def load_evaluation(eval_dir) -> dict:
    """``metrics.json`` and ``frame_manifest.json`` of an evaluation directory, with the metrics file's hash."""
    d = Path(eval_dir)
    if not (d / "metrics.json").is_file():
        raise ReleaseInputError(f"no metrics.json in {d}: run `python -m bor.eval.score` first, or build without --eval-dir")
    raw = (d / "metrics.json").read_bytes()
    frame_file = d / "frame_manifest.json"
    return {"metrics": json.loads(raw), "frame": json.loads(frame_file.read_text()) if frame_file.exists() else {},
            "sha256": hashlib.sha256(raw).hexdigest()}


def _row(**kw) -> dict:
    row = dict.fromkeys(COLUMNS)
    row.update(kw)
    return row


def _unevaluated(stage: str, metric: str, note: str, status: str = "none") -> dict:
    return _row(stage=stage, metric=metric, unit="pair", adjudication_status=status, provisional=True, note=note)


def method_metrics_table(evaluation: dict | None, gold_status: str = "none") -> pd.DataFrame:
    """The table: a row for every link-creating stage and, when an evaluation is given, for every sampled
    stratum. ``gold_status`` says who produced the gold (a value of ``ADJUDICATION_STATUSES``)."""
    if gold_status not in ADJUDICATION_STATUSES:
        raise ReleaseInputError(f"gold_status must be one of {ADJUDICATION_STATUSES}")
    rows, covered = [], set()
    if evaluation:
        m, frame = evaluation["metrics"], evaluation.get("frame") or {}
        for st, s in m["strata"].items():
            stage = STRATUM_STAGE.get(st) or STRATUM_SCOPE.get(st)
            if stage is None:
                raise ValueError(f"unknown stratum {st!r}: add it to STRATUM_STAGE or STRATUM_SCOPE")
            if "counts" not in s:
                raise ReleaseInputError("metrics.json has no counts; rerun `python -m bor.eval.score` (it now records them)")
            size = (frame.get("strata") or {}).get(st, {}).get("frame")
            census = size is not None and s["n"] == size
            population = POPULATION[st] + (f" (frame {size:,}, sampled {s['n']})" if size else f" (sampled {s['n']})")
            common = dict(
                stage=stage, unit="pair", population=population, n=s["n"], confidence_level=CONFIDENCE,
                interval_method="Wilson score interval, z=1.96, treating the stratum as a simple random sample"
                                + ("; this stratum is a census (every frame pair was sampled), so the interval is "
                                   "conservative" if census else ""),
                strata_ref=f"{frame.get('frame', 'evaluation')}:{st}" + (f" (frame {size})" if size else ""),
                eval_artifact=f"bor.eval.score metrics.json sha256:{evaluation['sha256'][:16]}",
                eval_version=f"{frame.get('frame', 'evaluation')}@{frame.get('builder_commit', 'unknown')}"
                             f" built {frame.get('built_at', 'unknown')}",
                adjudication_status=gold_status, provisional=gold_status != "blind_human")
            cov = f"{s['adjudicable']} of {s['n']} pairs adjudicable (coverage {s['coverage']}); the rest are excluded."
            tail = " ".join(x for x in (STRATUM_NOTE.get(st), cov, f"Gold: {STATUS_TEXT[gold_status]}.", LINK_NOTE) if x)
            c = s["counts"]
            if "strict_precision" in s:
                for metric, (p, lo, hi), num, what in (
                        ("precision_strict", s["strict_precision"], c["c1"], "cross-source corroboration only (C1)"),
                        ("precision_inclusive", s["inclusive_precision"], c["c1"] + c["c2"],
                         "cross-source plus same-source-verified (C1 and C2)")):
                    rows.append(_row(**common, metric=metric, numerator=num, denominator=num + c["different"],
                                     precision=p, ci_lower=lo, ci_upper=hi,
                                     estimator=f"proportion of counted pairs judged the same owner on {what}; "
                                               "indeterminate pairs excluded; no weights",
                                     note=tail))
            else:
                p, lo, hi = s["split_precision"]
                rows.append(_row(**common, metric="split_precision", numerator=c["good"], denominator=c["adjudicable"],
                                 precision=p, ci_lower=lo, ci_upper=hi,
                                 estimator="proportion of counted pairs judged different owners; indeterminate "
                                           "pairs excluded; no weights",
                                 note=tail))
            covered.add(stage)
    for stage in LINK_STAGES:                                   # every link-creating stage says where it stands
        if stage in covered:
            continue
        note = UNEVALUATED[stage]
        for metric in ("precision_strict", "precision_inclusive"):
            rows.append(_unevaluated(stage, metric, note))
    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df.astype({c: "Int64" for c in ("n", "numerator", "denominator")})      # counts are integers, blank when null
    order = {s: i for i, s in enumerate((*LINK_STAGES, *STRATUM_SCOPE.values()))}
    df = df.assign(_o=df["stage"].map(order), _m=df["metric"]).sort_values(["_o", "_m"]).drop(columns=["_o", "_m"])
    return df.reset_index(drop=True)


def main() -> None:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("eval_dir")
    ap.add_argument("--gold-status", default="none", choices=ADJUDICATION_STATUSES)
    ap.add_argument("--out", help="write method_metrics.csv here")
    a = ap.parse_args()
    df = method_metrics_table(load_evaluation(a.eval_dir), a.gold_status)
    show = df[["stage", "metric", "n", "numerator", "denominator", "precision", "ci_lower", "ci_upper"]]
    print(show.to_string(index=False))
    if a.out:
        df.to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
