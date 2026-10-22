"""explain(): plain-language answers from a release, on the mini fixture and then on the dump."""
import json
import os

import pandas as pd
import pytest

from bor import explain as ex

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mini_release")


@pytest.fixture(scope="module")
def mini():
    return ex.Release.from_dir(FIXTURE)


# --- a pair of lots ----------------------------------------------------------------------------

def test_a_pair_in_one_group_gets_the_path_between_their_nodes(mini):
    e = ex.explain_pair(mini, "3000010001", "3000010003")
    assert e.answer.startswith("Yes: both are in Owner Portfolio OP-1") and len(e.steps) == 2
    assert [s["stage"] for s in e.steps] == ["identity.splink_base", "identity.splink_feedback"]
    # each step names the two lots and what joined them
    assert "lot 3000010001" in e.steps[0]["text"] and "lot 3000010002" in e.steps[0]["text"]
    assert any("scores 0.9995 to 0.9997" in x for x in e.steps[0]["evidence"])


def test_the_weak_stage_a_path_needs_is_named_and_the_company_contacts_are_cited(mini):
    e = ex.explain_pair(mini, "3000010001", "3000010003")
    assert len(e.weakest) == 1 and "identity.splink_feedback" in e.weakest[0]
    ev = " ".join(e.steps[1]["evidence"])
    assert "101:10103:0" in ev and "103:10303:0" in ev and "no direct score" in ev


def test_a_path_that_needs_no_weak_evidence_says_nothing_about_it(mini):
    e = ex.explain_pair(mini, "3000010001", "3000010002")
    assert e.weakest == [] and len(e.steps) == 1 and e.steps[0]["stage"] == "identity.splink_base"


def test_the_path_runs_in_the_direction_asked(mini):
    fwd = ex.explain_pair(mini, "3000010001", "3000010005").steps
    back = ex.explain_pair(mini, "3000010005", "3000010001").steps
    assert [s["basis_id"] for s in fwd] == [s["basis_id"] for s in back][::-1] or len(fwd) == len(back) == 3
    assert fwd[0]["directed"][0] == "1" and back[0]["directed"][0] == "5"


def test_a_pair_in_different_groups_or_none_says_no_and_why(mini):
    e = ex.explain_pair(mini, "3000010001", "3000010004")
    assert e.answer.startswith("No:") and "3000010004 is in no Owner Portfolio" in e.answer and not e.steps
    n = ex.explain_pair(mini, "3000010001", "3000010999")
    assert "is in no node" in n.answer


# --- a single lot ------------------------------------------------------------------------------

def test_a_lot_blocked_by_a_gate_gets_the_event_that_did_it(mini):
    e = ex.explain_lot(mini, "3000010004", "owner_portfolio")
    text = e.render()
    assert "Primary reason: first_name_veto" in e.answer
    assert "rule first_name_veto rejected identity I0000004 against identity I0000003 (score 0.9996 vs threshold 0.999)" in text
    assert "never evidence that the owners differ" in text


def test_a_lot_left_out_of_a_footprint_and_a_dropped_lot(mini):
    assert "left out of its rental footprint" in ex.explain_lot(mini, "3000010005", "owner_portfolio").answer
    d = ex.explain_lot(mini, "3000010006", "owner_portfolio")
    assert "coop_condo_dominated" in d.answer and d.data["owner_portfolio"]["group_id"] is None


def test_a_grouped_lot_says_which_group_and_how_big(mini):
    e = ex.explain_lot(mini, "3000010002", "owner_portfolio")
    assert e.answer == "Owner Portfolio: in OP-1 (3 lots)." and "node 2" in " ".join(e.details)


def test_a_lot_the_release_does_not_know_is_said_to_be_unknown(mini):
    assert "no row for this lot" in ex.explain_lot(mini, "9999999999", "owner_portfolio").answer


# --- a group -----------------------------------------------------------------------------------

def test_a_group_summary_counts_nodes_lots_and_stages(mini):
    e = ex.explain_group(mini, "OP-1")
    assert e.answer == "4 nodes covering 4 lots (3 in the rental footprint)."
    assert e.data["stages"] == {"identity.splink_base": 2, "identity.splink_feedback": 1} and e.weakest
    assert "not in this release" in ex.explain_group(mini, "OP-999").answer.lower()


# --- the output --------------------------------------------------------------------------------

def test_every_explanation_carries_the_caveat_and_serializes(mini):
    for e in (ex.explain_pair(mini, "3000010001", "3000010003"), ex.explain_lot(mini, "3000010004"),
              ex.explain_group(mini, "OP-1")):
        assert "a lead, not a determination of ownership" in e.render()
        assert json.loads(json.dumps(e.to_dict()))["caveats"] == e.caveats


def test_the_command_line_prints_the_rendering(capsys):
    ex.main([FIXTURE, "pair", "3000010001", "3000010003"])
    out = capsys.readouterr().out
    assert "Yes: both are in Owner Portfolio OP-1" in out
    ex.main([FIXTURE, "lot", "3000010004", "--json"])
    assert json.loads(capsys.readouterr().out)["data"]["owner_portfolio"]["reason_code"] == "first_name_veto"


# --- the reference dump (needs the database to build the release) -------------------------------

@pytest.fixture(scope="module")
def dump(release_build):
    from bor.release_validate import read_release
    out, _ = release_build
    return ex.Release(*read_release(str(out)))


def _lot_of(rel, node):
    return rel.lots_of(str(node))[0]


def _first_step(rel, stage, layer="owner_portfolio"):
    w = rel.table("group_witness")
    return w[(w["layer"] == layer) & (w["stage"] == stage)].iloc[0]


def test_every_kind_of_step_is_explained_with_its_evidence(dump):
    seen = {}
    for stage in ("identity.splink_base", "identity.splink_feedback", "identity.registered_llc", "deed.held_since",
                  "deed.linked_successor"):
        s = _first_step(dump, stage)
        e = ex.explain_pair(dump, _lot_of(dump, s["node_a"]), _lot_of(dump, s["node_b"]))
        assert e.answer.startswith("Yes"), stage
        assert any(st["stage"] == stage for st in e.steps)
        seen[stage] = " ".join(x for st in e.steps if st["stage"] == stage for x in st["evidence"])
    assert "accepted match decision" in seen["identity.splink_base"]
    assert "shared-company merge" in seen["identity.splink_feedback"]
    assert "PLUTO lot" in seen["identity.registered_llc"]
    assert "ACRIS deed" in seen["deed.held_since"] and "conveyed on by deed" in seen["deed.linked_successor"]
    e = ex.explain_pair(dump, _lot_of(dump, _first_step(dump, "deed.linked_successor")["node_a"]),
                        _lot_of(dump, _first_step(dump, "deed.linked_successor")["node_b"]))
    assert e.weakest and "deed.linked_successor" in e.weakest[0]


def test_lots_that_are_absent_get_their_reasons(dump):
    s = dump.table("bbl_status")
    op = s[s["layer"] == "owner_portfolio"]
    for code, needle in (("no_registration", "no_registration"), ("coop_condo_dominated", "coop_condo_dominated"),
                         ("first_name_veto", "first_name_veto")):
        lot = op[op["reason_code"] == code].iloc[0]["bbl"]
        e = ex.explain_lot(dump, lot, "owner_portfolio")
        assert needle in e.answer and "not in a group" in e.answer


def test_two_lots_across_a_network_boundary_are_still_connected(dump):
    mem = dump.table("network_membership")
    per = mem.groupby("component_id")["operational_network_id"].nunique()
    comp = mem[mem["component_id"] == per[per > 1].index[0]]
    a = comp.iloc[0]
    b = comp[comp["operational_network_id"] != a["operational_network_id"]].iloc[0]
    e = ex.explain_pair(dump, _lot_of(dump, a["node_id"]), _lot_of(dump, b["node_id"]), "operational_network")
    assert e.answer.startswith("No:") and any("cross a network boundary" in d for d in e.details)


def test_a_group_of_the_dump_is_summarised(dump):
    g = dump.table("groups")
    gid = g[(g["layer"] == "owner_portfolio")].iloc[0]["group_id"]
    e = ex.explain_group(dump, gid)
    assert "nodes covering" in e.answer and e.data["layer"] == "owner_portfolio"
