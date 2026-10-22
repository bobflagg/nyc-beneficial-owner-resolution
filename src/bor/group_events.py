"""Decision events for the Owner Portfolio's co-op/condo rule (W6a; stage ``owner_portfolio.footprint``).

The Owner Portfolio drops a group whose rental lots are fewer than half its lots, and keeps a group
but leaves its co-op/condo lots out of the rental footprint. Both are policy outcomes (rule
``group_footprint_rule`` / ``coop_condo_contact_rule``, the HPD contact-description share) that the
per-lot absence summary needs as events:

* a dropped group: one ``dropped`` event on the group, and one ``excluded`` event on each of its lots;
* a surviving group: one ``excluded`` event on each co-op/condo lot left out of its footprint.

A dropped group is never in ``groups``; its id is the one it would have had.
"""
from __future__ import annotations

import json

import pandas as pd

from bor.identity_events import EVENT_COLUMNS

LAYER = "owner_portfolio"
STAGE = "owner_portfolio.footprint"


def portfolio_events(portfolios, dropped: list, rule_version: str) -> pd.DataFrame:
    rows = []

    def add(**kw):
        row = dict.fromkeys(EVENT_COLUMNS)
        row.update(layer=LAYER, stage=STAGE, rule_version=rule_version, **kw)
        rows.append(row)

    for d in sorted(dropped, key=lambda d: d["group_id"]):
        add(subject_type="group", subject_id=d["group_id"], outcome="dropped", reason_code="coop_condo_dominated",
            rule="group_footprint_rule",
            detail=json.dumps({"lots": len(d["bbls"]), "rental_lots": len(d["rental"])}, sort_keys=True))
        for b in d["bbls"]:
            add(subject_type="bbl", subject_id=b, counterpart_type="group", counterpart_id=d["group_id"],
                outcome="excluded", reason_code="coop_condo_dominated", rule="group_footprint_rule")
    for p in sorted(portfolios, key=lambda p: p.owner_portfolio_id):
        rental = set(p.bbls)
        for b in p.total_bbls:
            if b not in rental:
                add(subject_type="bbl", subject_id=b, counterpart_type="group", counterpart_id=p.owner_portfolio_id,
                    outcome="excluded", reason_code="coop_condo_excluded", rule="coop_condo_contact_rule")
    ev = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    ev["decision_id"] = [f"G{i:07d}" for i in range(1, len(ev) + 1)]
    return ev
