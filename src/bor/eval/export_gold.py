"""bor.eval.export_gold — freeze the adjudicated frame into a portable gold fixture.

Joins the blinded frame (blinding_key + review_queue + frame_manifest) with the handed-back
pairwise annotations, resolves a human gold label per pair, fills the WoW baseline decision from
`wow.wow_portfolios`, and writes `frame_gold.jsonl` (+ a provenance manifest). This is the ONE
place that touches the private key, the DB and the raw annotations; `nlr.eval.frame_impact` then
scores the fixture alone — no DB, no key, no annotations — so the false-split-impact numbers are
reproducible from a repo that never sees the frame.

    uv run python -m bor.eval.export_gold --out eval_out --gold-annotator bob

Gold rule (design doc §1.1): keep only human annotators (drop any `agent-*` and the adjudicator
agent); with one human, gold is that row's label; with ≥2, require unanimity (disagreements are
reported, never silently majority-voted). INDETERMINATE is carried through as a first-class label.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bor.eval.score import _bbl_to_wow_portfolio, _wow_decision, _load_jsonl

AGENT_PREFIX = "agent-"
ADJUDICATOR = "adjudicator"


def _git_commit(repo: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def _human_rows(rows: list[dict], gold_annotator: str | None) -> list[dict]:
    """Human annotations only: drop the agent and the adjudicator agent; optionally pin to one id."""
    hum = [r for r in rows if not r["annotator_id"].startswith(AGENT_PREFIX)
           and r["annotator_id"] != ADJUDICATOR]
    if gold_annotator:
        hum = [r for r in hum if r["annotator_id"] == gold_annotator]
    return hum


def _resolve_gold(rows: list[dict]) -> tuple[str | None, list[str], bool]:
    """(label, annotator_ids, unanimous) for a pair's human rows, or (None, …) if none / split."""
    if not rows:
        return None, [], True
    ids = sorted({r["annotator_id"] for r in rows})
    labels = {r["label"] for r in rows}
    if len(labels) == 1:
        return rows[0]["label"], ids, True
    return None, ids, False            # genuine disagreement — excluded, reported below


def export_gold(out_dir: Path, *, gold_annotator: str | None = None,
                key_path: str | None = None, queue_path: str | None = None,
                ann_path: str | None = None, manifest_path: str | None = None) -> dict:
    from bor.db import pg_conn

    key_path = key_path or str(out_dir / "blinding_key.jsonl")
    queue_path = queue_path or str(out_dir / "review_queue.jsonl")
    ann_path = ann_path or str(out_dir / "annotations.jsonl")
    manifest_path = manifest_path or str(out_dir / "frame_manifest.json")

    key = {k["pair_id"]: k for k in _load_jsonl(key_path)}
    queue = {q["pair_id"]: q for q in _load_jsonl(queue_path)}
    manifest = json.loads(Path(manifest_path).read_text())
    frame_size = {st: m["frame"] for st, m in manifest["strata"].items()}

    anns_by_pair: dict[str, list[dict]] = defaultdict(list)
    for a in _load_jsonl(ann_path):
        anns_by_pair[a["pair_id"]].append(a)

    conn = pg_conn()
    try:
        bbl2pf = _bbl_to_wow_portfolio(conn)
    finally:
        conn.close()

    rows, disagreements, per_stratum = [], [], defaultdict(lambda: {"frame_size": 0, "n_adjudicated": 0})
    gold_annotators: set[str] = set()
    for pid, k in key.items():
        hum = _human_rows(anns_by_pair.get(pid, []), gold_annotator)
        label, ids, unanimous = _resolve_gold(hum)
        if not unanimous:
            disagreements.append({"pair_id": pid, "annotators": ids,
                                  "labels": [r["label"] for r in hum]})
            continue
        if label is None:
            continue                                   # never adjudicated — simply absent
        gold_annotators.update(ids)
        q = queue.get(pid, {})
        st = k["stratum"]
        per_stratum[st]["frame_size"] = frame_size.get(st, 0)
        per_stratum[st]["n_adjudicated"] += 1
        rows.append({
            "pair_id": pid, "stratum": st, "signal": k["signal"], "label": label,
            "a_name": (q.get("a") or {}).get("name"), "a_bbls": k["a_bbls"],
            "b_name": (q.get("b") or {}).get("name"), "b_bbls": k["b_bbls"],
            "frame_size": frame_size.get(st, 0),
            "wow": _wow_decision(k["a_bbls"], k["b_bbls"], bbl2pf),
            "a_nodeid": k.get("a_nodeid"), "b_nodeid": k.get("b_nodeid"),
            "annotator_id": ids[0] if len(ids) == 1 else "+".join(ids),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "frame_gold.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    prov = {
        "frame": manifest.get("frame"), "built_at": manifest.get("built_at"),
        "builder_commit": manifest.get("builder_commit"),
        "bor_commit": _git_commit("."),
        "owner_review_commit": _git_commit("../owner-review"),
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gold_annotators": sorted(gold_annotators),
        "gold_rule": ("single-human" if gold_annotator else "human-unanimous"),
        "n_pairs": len(rows), "n_disagreements": len(disagreements),
        "wow_source": "wow.wow_portfolios (shared portfolio ⇒ SAME)",
        "per_stratum": {st: dict(v) for st, v in sorted(per_stratum.items())},
    }
    (out_dir / "frame_gold.manifest.json").write_text(json.dumps(prov, indent=2) + "\n")
    if disagreements:
        (out_dir / "frame_gold.disagreements.jsonl").write_text(
            "".join(json.dumps(d) + "\n" for d in disagreements))
    return prov


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval_out")
    ap.add_argument("--gold-annotator", default=None,
                    help="pin gold to one human annotator_id (e.g. bob); omit to require human unanimity")
    a = ap.parse_args()
    prov = export_gold(Path(a.out), gold_annotator=a.gold_annotator)
    print(f"frame_gold.jsonl — {prov['n_pairs']} pairs "
          f"({prov['gold_rule']}, annotators={prov['gold_annotators']}), "
          f"{prov['n_disagreements']} disagreements  ->  {Path(a.out) / 'frame_gold.jsonl'}")
    for st, v in prov["per_stratum"].items():
        print(f"  {st:<28} n_adjudicated={v['n_adjudicated']:>3}  frame={v['frame_size']}")
