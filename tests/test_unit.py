"""Unit tests for the pure logic — no database, run anywhere."""
from bor._edges import _clique_rows
from bor.deed_edges import _is_nominal
from bor.eval.gate import is_aggregator_portfolio
from bor.operational_network import _collapse, _components, _louvain_communities, _norm_bizaddr
from bor.owner_portfolios import _union_groups, classify_composition


# --- edge kernel -------------------------------------------------------------------------------

def test_clique_rows_full_clique():
    assert _clique_rows([3, 1, 2]) == [(1, 2), (1, 3), (2, 3)]


def test_clique_rows_singleton_is_empty():
    assert _clique_rows([7]) == []


def test_clique_rows_star_above_threshold():
    rows = _clique_rows([1, 2, 3, 4], star_above=3)   # 4 > 3 -> hub-and-spoke on the min id
    assert rows == [(1, 2), (1, 3), (1, 4)]


# --- Owner Portfolio union-find + composition ------------------------------------------------------

def test_union_groups_min_root_label():
    g = _union_groups([(3, 1), (1, 2), (10, 11)])
    assert g == {1: "OP-1", 2: "OP-1", 3: "OP-1", 10: "OP-10", 11: "OP-10"}


def test_union_groups_drops_below_min_size():
    assert _union_groups([(1, 2)], min_size=3) == {}


def test_composition_identity():
    assert classify_composition([(1, 2), (2, 3)], []) == {"OP-1": "identity"}


def test_composition_deed_only():
    assert classify_composition([], [(5, 6)]) == {"OP-5": "deed_only"}


def test_composition_deed_bridged():
    # two identity entities {1,2} and {3,4}, fused into one group by a deed edge 2-3
    assert classify_composition([(1, 2), (3, 4)], [(2, 3)]) == {"OP-1": "deed_bridged"}


# --- operational-network helpers ---------------------------------------------------------------

def test_norm_bizaddr():
    assert _norm_bizaddr("  123 Main St , Brooklyn NY ") == "123 MAIN ST"
    assert _norm_bizaddr(None) == ""


def test_components():
    comps = {frozenset(c) for c in _components([(1, 2), (2, 3), (10, 11)])}
    assert comps == {frozenset({1, 2, 3}), frozenset({10, 11})}


def test_collapse_sums_parallel_edges():
    w = _collapse([(1, 2, 1.5), (2, 1, 1.0), (3, 4, 2.0)])   # (1,2) parallel; direction-agnostic
    assert w[(1, 2)] == 2.5 and w[(3, 4)] == 2.0


def test_louvain_splits_two_clusters():
    # two tight triangles joined by one weak edge -> two communities
    wedges = {(1, 2): 10, (1, 3): 10, (2, 3): 10,
              (4, 5): 10, (4, 6): 10, (5, 6): 10,
              (3, 4): 0.1}
    comms = {frozenset(c) for c in _louvain_communities([1, 2, 3, 4, 5, 6], wedges)}
    assert comms == {frozenset({1, 2, 3}), frozenset({4, 5, 6})}


# --- deed nominal-consideration guard ----------------------------------------------------------

def test_is_nominal():
    assert _is_nominal(0) is True
    assert _is_nominal("100") is True
    assert _is_nominal(101) is False
    assert _is_nominal(1_200_000) is False
    assert _is_nominal(None) is False       # missing price -> non-nominal (precision-safe)
    assert _is_nominal("not-a-number") is False


# --- WoW gate aggregator classifier ------------------------------------------------------------

def test_aggregator_hard_cutoff():
    assert is_aggregator_portfolio(n_buildings=1, n_landlords=26) is True     # >25 landlords
    assert is_aggregator_portfolio(n_buildings=1, n_landlords=25) is False    # not > 25, small


def test_aggregator_soft_cutoff():
    assert is_aggregator_portfolio(n_buildings=20, n_landlords=4) is True     # soft: >=20 & >=4
    assert is_aggregator_portfolio(n_buildings=19, n_landlords=4) is False    # too few buildings
    assert is_aggregator_portfolio(n_buildings=100, n_landlords=3) is False   # too few landlords
