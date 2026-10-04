"""Unit tests for the WoW graph-structure analysis — pure, no DB."""
import json

from bor.eval.wow_structure import MID_HUB_DEGREE, analyze_graph, format_report, parse_graph, summarize


def owner(i, addr="1 MAIN ST, NEW YORK NY"):
    return {"id": i, "type": "owner", "name": f"O{i}", "bizAddr": addr, "bbls": [f"100000000{i}"]}


def edge(a, b, typ="bizaddr"):
    return {"source": a, "target": b, "type": typ, "weight": 1.0}


def test_single_owner_is_not_multi_owner():
    s = analyze_graph(1, {"nodes": [{"id": "addr", "type": "bizAddr"}, owner(1)], "edges": []}, 3)
    assert s.n_owners == 1 and not s.multi_owner and not s.address_dependent and s.n_bbls == 3


def test_two_owners_linked_only_by_address_are_address_dependent():
    s = analyze_graph(2, {"nodes": [owner(1), owner(2)], "edges": [edge(1, 2)]}, 2)
    assert s.multi_owner and s.address_dependent
    assert s.max_address_degree == 2 and s.edge_types == {"bizaddr": 1}


def test_a_name_edge_makes_the_portfolio_independent_of_address():
    s = analyze_graph(3, {"nodes": [owner(1), owner(2)], "edges": [edge(1, 2), edge(1, 2, "name")]}, 2)
    assert s.multi_owner and not s.address_dependent


def test_mixed_chain_is_address_dependent():
    # 1-2 joined by name, 2-3 only by address: dropping address edges leaves {1,2} and {3}
    g = {"nodes": [owner(1), owner(2, "2 OAK AVE"), owner(3, "2 OAK AVE")],
         "edges": [edge(1, 2, "name"), edge(2, 3)]}
    s = analyze_graph(4, g, 3)
    assert s.address_dependent and s.max_address_degree == 2


def test_address_degree_counts_identical_strings_only():
    g = {"nodes": [owner(1, "5 ELM ST"), owner(2, "5 ELM ST"), owner(3, "5 ELM STREET")],
         "edges": [edge(1, 2), edge(2, 3)]}
    assert analyze_graph(5, g, 3).max_address_degree == 2


def test_graph_may_arrive_as_json_text_or_be_missing():
    g = {"nodes": [owner(1), owner(2)], "edges": [edge(1, 2)]}
    assert analyze_graph(6, json.dumps(g), 2).address_dependent
    assert parse_graph(None) == {"nodes": [], "edges": []}
    assert not analyze_graph(7, None, 0).multi_owner


def test_edges_to_unknown_nodes_are_ignored():
    g = {"nodes": [owner(1), owner(2)], "edges": [edge(1, 99, "name"), edge(1, 2)]}
    assert analyze_graph(8, g, 2).address_dependent


def test_summarize_counts_and_shares():
    hub = {"nodes": [owner(i, "HUB, NY") for i in range(1, 26)],
           "edges": [edge(i, i + 1) for i in range(1, 25)]}
    stats = [
        analyze_graph("a", {"nodes": [owner(1)], "edges": []}, 1),
        analyze_graph("b", {"nodes": [owner(1), owner(2)], "edges": [edge(1, 2)]}, 2),
        analyze_graph("c", {"nodes": [owner(1), owner(2)], "edges": [edge(1, 2, "name")]}, 4),
        analyze_graph("d", hub, 10),
    ]
    m = summarize(stats, hub_degree=25)
    assert m["portfolios"] == 4 and m["buildings"] == 17
    assert m["edges"]["by_type"] == {"bizaddr": 25, "name": 1} and m["edges"]["total"] == 26
    assert m["multi_owner"]["portfolios"] == 3 and m["multi_owner"]["buildings"] == 16
    assert m["address_dependent"]["portfolios"] == 2          # b and the hub; c has a name edge
    assert m["address_dependent"]["buildings"] == 12
    assert m["address_dependent"][f"with_address_degree_ge_{MID_HUB_DEGREE}"] == 1
    assert m["address_dependent"]["with_address_degree_ge_25"] == 1
    assert m["hub_addresses"]["portfolios"] == 1 and m["hub_addresses"]["buildings"] == 10
    assert m["address_only"]["portfolios"] == 2 and m["address_only"]["buildings"] == 12   # b and the hub
    assert abs(m["address_only"]["share_of_multi_owner_portfolios"] - 2 / 3) < 1e-9
    assert m["multi_owner"]["median_owner_nodes"] == 2 and m["multi_owner"]["max_owner_nodes"] == 25


def test_summarize_empty_and_report_render():
    m = summarize([])
    assert m["portfolios"] == 0 and m["multi_owner"]["median_owner_nodes"] == 0
    assert "descriptive, not accuracy" in format_report(m)


def test_address_dependent_is_not_address_only():
    # 1-2 by name, 2-3 only by address: needs the address edge to stay connected, but has a name edge
    g = {"nodes": [owner(1), owner(2, "2 OAK AVE"), owner(3, "2 OAK AVE")],
         "edges": [edge(1, 2, "name"), edge(2, 3)]}
    m = summarize([analyze_graph("x", g, 3)])
    assert m["address_dependent"]["portfolios"] == 1
    assert m["address_only"]["portfolios"] == 0
