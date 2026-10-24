"""nyc-beneficial-owner-resolution (``bor``)

Reliability-typed beneficial-ownership resolution over NYC public records.

Builds on the standalone record-linkage engine ``nlr`` (false-split resolution) and adds:
  * the name-free deed veil-pierce (ACRIS co-conveyance + linked-successor guard),
  * Owner Portfolios (connected components over CONNECTED_BY_SPLINK ∪ CONNECTED_BY_DEED,
    computed off-graph — no Neo4j),
  * reliability typing (directly-sourced vs. inferred),
  * a paired evaluation protocol against JustFix's Who Owns What.

The operational-network layer (aggregator-masked WCC + Louvain) arrives in v1.1.

Planned public API (v1):
    resolve_owner_portfolios(conn) -> {landlord_key: owner_portfolio_id}
    deed_edges(conn)           -> co-conveyance edges (name-free veil-pierce)
    bor.eval.divergence        -> paired head-to-head report vs. wow.wow_portfolios
"""

__version__ = "0.2.0"

from bor.owner_portfolios import (
    resolve_owner_portfolios,
    assignments,
    bbl_assignments,
    OwnerPortfolio,
)
from bor.operational_network import (
    resolve_operational_networks,
    OperationalNetwork,
)

__all__ = [
    "resolve_owner_portfolios", "assignments", "bbl_assignments", "OwnerPortfolio",
    "resolve_operational_networks", "OperationalNetwork",
]
