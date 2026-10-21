"""bor.eval.sample — draw the FROZEN stratified pair sample for the ground-truth evaluation.

Off-graph (no Neo4j). Emits, into an output dir:
  * review_queue.jsonl  — the blinded annotation packet (pair_id + each entity's name/bbls only;
    A/B order randomized; strata interleaved). This is what the two blind annotators adjudicate.
  * blinding_key.jsonl  — PRIVATE: stratum, driving signal, the system's own decision, nodeids/bbls.
    Rejoined at scoring (bor.eval.score); never shown to annotators.
  * frame_manifest.json — preregistration: as-of date, git sha, seed, per-stratum frame size + n.

Strata (protocol §2, matching the reference sampler): S1a deed-held, S1b deed-linked-successor,
S2 model, S3 aggregator-splits, S4 hard-negatives. Deterministic given SEED.

The four edge frames are built once and reused; owner membership is the union-find over identity ∪
deed edges (so "same owner" excludes any already-merged pair from the split/negative strata).

    uv run python -m bor.eval.sample --out eval_out     # (PG* / .env set; ~12 min)
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from bor.curated_owners import curated_edges
from bor.deed_edges import MAX_PARCELS, _deed_sql, _groups_from, deed_edges
from bor.llc_edges import llc_edges
from bor.operational_network import MAX_ADDR_DEGREE, _norm_bizaddr
from bor.owner_portfolios import _union_groups
from bor.splink_bridge import DEFAULT_THRESHOLD, splink_edges

SEED = 42
STRATA_N = {"S1a_deed_held": 70, "S1b_deed_linked_successor": 70, "S2_model": 150,
            "S3_aggregator": 120, "S4_hard_neg": 120}
SIGNAL = {"S1a_deed_held": "acris-deed", "S1b_deed_linked_successor": "acris-deed-linked-successor",
          "S2_model": "splink-fellegi-sunter", "S3_aggregator": "aggregator-mask", "S4_hard_neg": "none"}
WATCHLINE = {"S1a_deed_held": "SAME", "S1b_deed_linked_successor": "SAME", "S2_model": "SAME",
             "S3_aggregator": "DIFFERENT", "S4_hard_neg": "DIFFERENT"}

_LWC_SQL = "SELECT nodeid, name, bbls::text[] AS bbls, bizaddr FROM landlords_with_connections"


def _pk(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=Path(__file__).parent, text=True).strip()
    except Exception:
        return "unknown"


def _held_membership(conn) -> dict[int, set[int]]:
    """nodeid -> held-group indices, from held-latest multi-parcel deeds only (deed branch A). A deed
    pair is 'held' iff its nodes share a held group; else it is a linked-successor recovery."""
    held = pd.read_sql(_deed_sql(MAX_PARCELS), conn)
    lwc = pd.read_sql("SELECT nodeid, bbls::text[] AS bbls FROM landlords_with_connections", conn)
    node2g: dict[int, set[int]] = defaultdict(set)
    for gi, ids in enumerate(_groups_from(held, lwc).values()):
        for n in ids:
            node2g[n].add(gi)
    return node2g


def _pairs_from_edges(frame, info) -> list[dict]:
    """[(src,dst,weight)] frame -> pair dicts with name/bbls from the lwc `info` map."""
    out = []
    for s, d in zip(frame["src"].astype(int), frame["dst"].astype(int)):
        a, b = info.get(s), info.get(d)
        if a and b:
            out.append({"a": {"nodeid": s, **a}, "b": {"nodeid": d, **b}})
    return out


def _group_pairs(groups, connected: set, owner_of: dict, *, require_diff_owner: bool,
                 per_group_cap: int, rng: random.Random) -> list[dict]:
    """Unconnected candidate pairs within attribute groups (shared address / surname)."""
    pool: list[dict] = []
    for members in groups:
        ms = list(members)
        rng.shuffle(ms)
        made = 0
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                a, b = ms[i], ms[j]
                if _pk(a["nodeid"], b["nodeid"]) in connected:
                    continue
                if require_diff_owner:
                    oa, ob = owner_of.get(a["nodeid"]), owner_of.get(b["nodeid"])
                    if oa is not None and oa == ob:
                        continue
                pool.append({"a": a, "b": b})
                made += 1
                if made >= per_group_cap:
                    break
            if made >= per_group_cap:
                break
    return pool


def build(conn, out_dir: Path, *, threshold: float = DEFAULT_THRESHOLD) -> dict:
    rng = random.Random(SEED)

    lwc = pd.read_sql(_LWC_SQL, conn)
    info = {int(r.nodeid): {"name": r.name, "bbls": [str(x) for x in (r.bbls or [])]}
            for r in lwc.itertuples()}

    # four edge frames, built once
    model = splink_edges(conn, threshold=threshold)
    curated = curated_edges(conn)
    llc = llc_edges(conn)
    deed = deed_edges(conn)

    connected: set = set()
    for f in (model, curated, llc, deed):
        connected |= {_pk(int(s), int(d)) for s, d in zip(f["src"], f["dst"])}
    # owner membership = union-find over identity ∪ deed (same-owner => already merged)
    all_pairs = [(_pk(int(s), int(d))) for f in (model, curated, llc, deed)
                 for s, d in zip(f["src"], f["dst"])]
    owner_of = _union_groups(all_pairs, min_size=2)

    node2held = _held_membership(conn)

    def held(pair) -> bool:
        return bool(node2held.get(pair["a"]["nodeid"], set()) & node2held.get(pair["b"]["nodeid"], set()))

    deed_pairs = _pairs_from_edges(deed, info)

    # attribute groups: shared aggregator address / shared surname
    by_addr: dict[str, list[dict]] = defaultdict(list)
    by_surname: dict[str, list[dict]] = defaultdict(list)
    for r in lwc.itertuples():
        nid = int(r.nodeid)
        member = {"nodeid": nid, "name": r.name, "bbls": [str(x) for x in (r.bbls or [])]}
        a = _norm_bizaddr(r.bizaddr)
        if a:
            by_addr[a].append(member)
        if isinstance(r.name, str) and " " in r.name:
            by_surname[r.name.strip().upper().split(" ")[-1]].append(member)
    agg_groups = [ms[:40] for ms in by_addr.values() if len(ms) > MAX_ADDR_DEGREE]
    surname_groups = [ms[:8] for ms in by_surname.values() if 2 <= len(ms) <= 20][:3000]

    frames = {
        "S1a_deed_held": [p for p in deed_pairs if held(p)],
        "S1b_deed_linked_successor": [p for p in deed_pairs if not held(p)],
        "S2_model": _pairs_from_edges(model, info),
        "S3_aggregator": _group_pairs(agg_groups, connected, owner_of,
                                      require_diff_owner=True, per_group_cap=6, rng=rng),
        "S4_hard_neg": _group_pairs(surname_groups, connected, owner_of,
                                    require_diff_owner=True, per_group_cap=3, rng=rng),
    }

    queue, key, manifest = [], [], {}
    seq = 0
    for stratum, n in STRATA_N.items():
        frame = frames[stratum]
        take = rng.sample(frame, min(n, len(frame)))
        manifest[stratum] = {"frame": len(frame), "n": len(take)}
        for pair in take:
            seq += 1
            pid = f"P{seq:04d}"
            a, b = pair["a"], pair["b"]
            if rng.random() < 0.5:          # randomize A/B so order encodes nothing
                a, b = b, a
            queue.append({"pair_id": pid,
                          "a": {"ref": "A", "name": a["name"], "bbls": a["bbls"]},
                          "b": {"ref": "B", "name": b["name"], "bbls": b["bbls"]}})
            key.append({"pair_id": pid, "stratum": stratum, "signal": SIGNAL[stratum],
                        "watchline": WATCHLINE[stratum], "wow": None,
                        "a_nodeid": a["nodeid"], "b_nodeid": b["nodeid"],
                        "a_bbls": a["bbls"], "b_bbls": b["bbls"]})

    rng.shuffle(queue)                       # present strata interleaved, not blocked
    qorder = {p["pair_id"]: i for i, p in enumerate(queue)}
    key.sort(key=lambda k: qorder[k["pair_id"]])

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "review_queue.jsonl").write_text("\n".join(json.dumps(p) for p in queue) + "\n")
    (out_dir / "blinding_key.jsonl").write_text("\n".join(json.dumps(k) for k in key) + "\n")
    fm = {
        "frame": "accuracy-eval-4-strata",
        "built_at": date.today().isoformat(),
        "builder": "bor.eval.sample",
        "builder_commit": _git_sha(),
        "seed": SEED,
        "aggregator_degree": MAX_ADDR_DEGREE,
        "note": ("Preregistration: freeze this + the codebook before adjudicating. Data snapshot is "
                 "the Postgres as of the build; splink-dependent strata jitter ~0.05% (docs/parity.md)."),
        "strata": manifest,
    }
    (out_dir / "frame_manifest.json").write_text(json.dumps(fm, indent=2) + "\n")
    return fm


if __name__ == "__main__":
    import warnings; warnings.filterwarnings("ignore")
    import logging; logging.getLogger("splink").setLevel(logging.ERROR)
    from bor.db import pg_conn
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval_out", help="output directory")
    args = ap.parse_args()
    conn = pg_conn()
    try:
        fm = build(conn, Path(args.out))
    finally:
        conn.close()
    print(f"wrote review_queue.jsonl + blinding_key.jsonl + frame_manifest.json to {args.out}/")
    for st, m in fm["strata"].items():
        print(f"  {st:<28} frame {m['frame']:>7}  sampled {m['n']}")
