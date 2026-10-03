"""nyc-beneficial-owner-resolution (``bor``)

Reliability-typed beneficial-ownership resolution over NYC public records — the software
artifact behind "Leads, Not Verdicts: Reliability-Typed Beneficial-Ownership Resolution for
Housing Accountability."

Builds on the standalone record-linkage engine ``nlr`` (false-split resolution) and adds:
  * the name-free deed veil-pierce (ACRIS co-conveyance + linked-successor guard),
  * beneficial owner groups (connected components over CONNECTED_BY_SPLINK ∪ CONNECTED_BY_DEED,
    computed off-graph — no Neo4j),
  * reliability typing (directly-sourced vs. inferred),
  * a paired evaluation protocol against JustFix's Who Owns What.

The operational-network layer (aggregator-masked WCC + Louvain) arrives in v1.1.

Planned public API (v1):
    resolve_owner_groups(conn) -> {landlord_key: owner_group_id}
    deed_edges(conn)           -> co-conveyance edges (name-free veil-pierce)
    bor.eval.divergence        -> paired head-to-head report vs. wow.wow_portfolios
"""

__version__ = "0.1.0.dev0"

from bor.owner_groups import (
    resolve_owner_groups,
    assignments,
    bbl_assignments,
    OwnerGroup,
)
from bor.operational_network import (
    resolve_operational_networks,
    OperationalNetwork,
)

__all__ = [
    "resolve_owner_groups", "assignments", "bbl_assignments", "OwnerGroup",
    "resolve_operational_networks", "OperationalNetwork",
]
