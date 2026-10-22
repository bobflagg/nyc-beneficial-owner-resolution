"""bor.eval.score — join the blind annotations with the private key + the dump's WoW portfolios and
produce the headline numbers.

Reads:
  * blinding_key.jsonl  — pair_id, stratum, signal, the system's decision, bbls, nodeids (from sample.py)
  * annotations.jsonl   — pair_id, annotator_id, label (SAME/DIFFERENT/INDETERMINATE), evidence_tiers

Fills the WoW decision per pair from `wow.wow_portfolios` (two entities are WoW-SAME iff any bbls
share a WoW portfolio). Emits per-stratum precision (strict C1-only + inclusive C1+C2), coverage,
C2 share (Wilson CIs), Cohen's κ, and a paired McNemar vs WoW. Read-only on Postgres; no Neo4j.

    uv run python -m bor.eval.score --key eval_out/blinding_key.jsonl \
        --annotations eval_out/annotations.jsonl --out eval_out
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

DEED_SIGNALS = {"acris-deed", "acris-deed-linked-successor"}
ADJUDICATOR = "adjudicator"          # annotator_id whose label is gold when annotators disagree


# ---- pure stats helpers ------------------------------------------------------------------------
def wilson(k: int, n: int) -> tuple[float, float, float]:
    """Point estimate + 95% Wilson interval for k/n. (0,0,0) when n==0."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    z = 1.959963984540054
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's κ over (labelA, labelB) for items both annotators labeled. None if <2 items."""
    n = len(pairs)
    if n < 2:
        return None
    labels = sorted({x for ab in pairs for x in ab})
    po = sum(1 for a, b in pairs if a == b) / n
    pe = sum((sum(1 for a, _ in pairs if a == L) / n) * (sum(1 for _, b in pairs if b == L) / n)
             for L in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def mcnemar(b: int, c: int) -> float:
    """Two-sided McNemar p (chi-square, continuity correction). b,c = discordant counts."""
    if b + c == 0:
        return 1.0
    chi = (abs(b - c) - 1) ** 2 / (b + c)
    return math.erfc(math.sqrt(chi / 2))


def gold_label(anns: list[dict]) -> tuple[str, list[str]]:
    """Gold label + evidence tiers: adjudicator wins; else unanimous agreement; else UNRESOLVED."""
    adj = [a for a in anns if a["annotator_id"] == ADJUDICATOR]
    if adj:
        g = adj[-1]
        return g["label"], list(g.get("evidence_tiers") or [])
    prim = [a for a in anns if a["annotator_id"] != ADJUDICATOR]
    labels = {a["label"] for a in prim}
    if len(labels) == 1 and prim:
        tiers = sorted({t for a in prim for t in (a.get("evidence_tiers") or [])})
        return prim[0]["label"], tiers
    return "UNRESOLVED", []


def corroboration_class(signal: str, gold: str, tiers: list[str]) -> str | None:
    """C1 cross-source / C2 same-source-verified, for a gold SAME. None if not a SAME."""
    if gold != "SAME":
        return None
    if signal in DEED_SIGNALS and set(tiers) == {"T1"}:
        return "C2"
    return "C1"


# ---- WoW decision from the dump ----------------------------------------------------------------
def _bbl_to_wow_portfolio(conn) -> dict[str, str]:
    cur = conn.cursor()
    cur.execute("SELECT orig_id, bbls FROM wow.wow_portfolios WHERE bbls IS NOT NULL")
    out: dict[str, str] = {}
    for orig_id, bbls in cur.fetchall():
        for b in (bbls or []):
            out[str(b).strip()] = str(orig_id)
    return out


def _wow_decision(a_bbls, b_bbls, bbl2pf) -> str:
    pa = {bbl2pf[str(b).strip()] for b in a_bbls if str(b).strip() in bbl2pf}
    pb = {bbl2pf[str(b).strip()] for b in b_bbls if str(b).strip() in bbl2pf}
    return "SAME" if (pa & pb) else "DIFFERENT"


def _load_jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def score(key_path: str, ann_path: str, out_dir: Path) -> dict:
    from bor.db import pg_conn
    key = {k["pair_id"]: k for k in _load_jsonl(key_path)}
    anns_by_pair: dict[str, list[dict]] = defaultdict(list)
    for a in _load_jsonl(ann_path):
        anns_by_pair[a["pair_id"]].append(a)

    conn = pg_conn()
    try:
        bbl2pf = _bbl_to_wow_portfolio(conn)
    finally:
        conn.close()

    recs, kappa_pairs = [], []
    for pid, k in key.items():
        anns = anns_by_pair.get(pid, [])
        gold, tiers = gold_label(anns)
        wow = _wow_decision(k["a_bbls"], k["b_bbls"], bbl2pf)
        recs.append({"pair_id": pid, "stratum": k["stratum"], "signal": k["signal"],
                     "watchline": k["watchline"], "wow": wow, "gold": gold,
                     "cclass": corroboration_class(k["signal"], gold, tiers)})
        prim = [a for a in anns if a["annotator_id"] != ADJUDICATOR]
        if len(prim) >= 2:
            kappa_pairs.append((prim[0]["label"], prim[1]["label"]))

    strata = sorted({r["stratum"] for r in recs})
    report: dict = {"kappa": cohens_kappa(kappa_pairs), "n_pairs": len(recs), "strata": {},
                    # who produced the gold, as recorded in the annotation file (not who they were)
                    "gold": {"annotators": sorted({a["annotator_id"] for v in anns_by_pair.values() for a in v}),
                             "adjudicator_rows": sum(1 for v in anns_by_pair.values() for a in v
                                                     if a["annotator_id"] == ADJUDICATOR)}}
    for st in strata:
        rs = [r for r in recs if r["stratum"] == st]
        watchline = rs[0]["watchline"] if rs else "SAME"
        adjud = [r for r in rs if r["gold"] in ("SAME", "DIFFERENT")]   # exclude INDET/UNRESOLVED
        m = {"n": len(rs), "adjudicable": len(adjud),
             "coverage": round(len(adjud) / len(rs), 3) if rs else 0}
        if watchline == "SAME":
            c1 = sum(1 for r in adjud if r["cclass"] == "C1")
            c2 = sum(1 for r in adjud if r["cclass"] == "C2")
            diff = sum(1 for r in adjud if r["gold"] == "DIFFERENT")
            m["strict_precision"] = wilson(c1, c1 + diff)
            m["inclusive_precision"] = wilson(c1 + c2, c1 + c2 + diff)
            m["c2_share"] = round(c2 / (c1 + c2), 3) if (c1 + c2) else 0
            m["counts"] = {"c1": c1, "c2": c2, "different": diff}      # the integers behind the proportions
        else:                                                           # DIFFERENT stratum
            good = sum(1 for r in adjud if r["gold"] == "DIFFERENT")
            m["split_precision"] = wilson(good, len(adjud))
            m["counts"] = {"good": good, "adjudicable": len(adjud)}
        report["strata"][st] = m

    disc = [r for r in recs if r["gold"] in ("SAME", "DIFFERENT") and r["watchline"] != r["wow"]]
    b = sum(1 for r in disc if r["watchline"] == r["gold"])
    c = sum(1 for r in disc if r["wow"] == r["gold"])
    report["head_to_head"] = {"discordant": len(disc), "watchline_right_wow_wrong": b,
                              "wow_right_watchline_wrong": c, "mcnemar_p": round(mcnemar(b, c), 5)}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "disagreements.jsonl").write_text(
        "\n".join(json.dumps(r) for r in disc) + "\n")
    (out_dir / "errors.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs
                  if r["gold"] in ("SAME", "DIFFERENT") and r["gold"] != r["watchline"]) + "\n")
    (out_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def gate_mode(out_dir: Path, *, og_ids: list[str] | None = None) -> dict:
    """The WoW veil-pierce gate over candidate deed Owner Portfolios (off-graph): which are genuine WoW
    false-splits the deed uniquely recovers (PASS) vs over-lumps WoW already groups on a shared
    aggregator address (FAIL)? Default population = deed-only groups (composition == 'deed_only')."""
    import warnings; warnings.filterwarnings("ignore")
    import logging; logging.getLogger("splink").setLevel(logging.ERROR)
    from bor.db import pg_conn
    from bor.eval.gate import gate_bbls
    from bor.owner_portfolios import resolve_owner_portfolios

    conn = pg_conn()
    try:
        groups = resolve_owner_portfolios(conn)
        if og_ids:
            cand = [g for g in groups if g.owner_portfolio_id in set(og_ids)]
        else:
            cand = [g for g in groups if g.composition == "deed_only"]
        results = []
        for g in cand:
            res = gate_bbls(conn, g.total_bbls)
            results.append({"owner_portfolio": g.owner_portfolio_id, "buildings": len(g.total_bbls),
                            "passed": res.passed, "reasons": res.reasons})
    finally:
        conn.close()

    results.sort(key=lambda x: (x["passed"], -x["buildings"]))
    n_pass = sum(1 for x in results if x["passed"])
    out = {"population": "specified" if og_ids else "deed-only",
           "n_candidates": len(results), "n_pass": n_pass, "n_fail": len(results) - n_pass,
           "results": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "wow_gate.json").write_text(json.dumps(out, indent=2))
    return out


def _fmt(w):
    return f"{w[0]:.2f} [{w[1]:.2f},{w[2]:.2f}]" if w else "-"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--annotations")
    ap.add_argument("--out", default="eval_out")
    ap.add_argument("--gate", action="store_true", help="WoW veil-pierce gate over deed-only Owner Portfolios")
    ap.add_argument("--owner-portfolio", dest="owner_portfolios", action="append", default=[], metavar="OP-ID")
    a = ap.parse_args()

    if a.gate:
        rep = gate_mode(Path(a.out), og_ids=a.owner_portfolios or None)
        print(f"WoW veil-pierce gate [{rep['population']}]: {rep['n_pass']}/{rep['n_candidates']} PASS · "
              f"{rep['n_fail']} over-lumps  ->  {Path(a.out) / 'wow_gate.json'}")
        for r in rep["results"]:
            tag = "PASS" if r["passed"] else "FAIL"
            reason = "" if r["passed"] else (f"  — {r['reasons'][0]}" if r["reasons"] else "")
            print(f"  {tag}  {r['owner_portfolio']:<14} {r['buildings']:>4} bldgs{reason}")
    else:
        if not (a.key and a.annotations):
            ap.error("--key and --annotations are required (or use --gate)")
        rep = score(a.key, a.annotations, Path(a.out))
        print(f"pairs {rep['n_pairs']}  κ={rep['kappa']}")
        for st, m in rep["strata"].items():
            if "strict_precision" in m:
                print(f"  {st:<28} precision strict {_fmt(m['strict_precision'])} · "
                      f"inclusive {_fmt(m['inclusive_precision'])} · C2 {m['c2_share']} · cov {m['coverage']}")
            else:
                print(f"  {st:<28} split-precision {_fmt(m['split_precision'])} · cov {m['coverage']}")
        h = rep["head_to_head"]
        print(f"  vs WoW: discordant {h['discordant']} · watchline✓/wow✗ {h['watchline_right_wow_wrong']} · "
              f"wow✓/watchline✗ {h['wow_right_watchline_wrong']} · McNemar p={h['mcnemar_p']}")
