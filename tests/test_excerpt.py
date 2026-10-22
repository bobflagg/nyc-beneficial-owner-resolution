"""bor.excerpt: a few Owner Portfolios of a release, everything they cite, still a valid release that
answers the same questions as its parent."""
import copy
import os

import pytest

from bor import explain as ex
from bor.excerpt import excerpt_release, write_excerpt
from bor.release_validate import read_release, validate_release

SYN = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic_release")
OP_GROUPS = ["OP-9001", "OP-9010", "OP-9030", "OP-9032", "OP-9050", "OP-9060", "OP-9070", "OP-9080", "OP-9082"]


@pytest.fixture(scope="module")
def parent():
    return read_release(SYN)


def _errors(tables, manifest, path=None):
    return [v for v in validate_release(tables, manifest, path=path) if v.severity == "error"]


@pytest.mark.parametrize("gid", OP_GROUPS)
def test_every_owner_portfolio_excerpts_to_a_valid_release(parent, gid, tmp_path):
    tables, manifest = parent
    out, m = excerpt_release(tables, manifest, [gid])
    path = write_excerpt(out, m, tmp_path / gid)
    t2, m2 = read_release(str(path))
    assert _errors(t2, m2, str(path)) == []
    # the same run and snapshot, and the excerpt says what it is
    assert m2["run_id"] == manifest["run_id"] and m2["snapshot_id"] == manifest["snapshot_id"]
    assert m2["excerpt"]["of_run_id"] == manifest["run_id"] and m2["excerpt"]["seed_groups"] == [gid]
    # the group's own rows are all there, and nothing of any other group
    for name in ("groups", "group_members", "group_bbls", "group_witness"):
        assert set(t2[name]["group_id"]) == {gid}, name
        assert len(t2[name]) == len(tables[name][tables[name]["group_id"] == gid]), name


@pytest.mark.parametrize("gid", OP_GROUPS)
def test_an_excerpt_answers_the_same_as_its_parent(parent, gid, tmp_path):
    tables, manifest = parent
    out, m = excerpt_release(tables, manifest, [gid])
    full, part = ex.Release(tables, manifest), ex.Release(out, m)
    assert ex.explain_group(part, gid).render() == ex.explain_group(full, gid).render()
    members = tables["group_members"]
    nodes = sorted(members.loc[members["group_id"] == gid, "node_id"].astype(str), key=int)
    lots = lambda n: full.lots_of(n)[0]
    if len(nodes) > 1:
        a, b = lots(nodes[0]), lots(nodes[-1])
        assert ex.explain_pair(part, a, b).render() == ex.explain_pair(full, a, b).render()
    for lot in tables["group_bbls"].loc[tables["group_bbls"]["group_id"] == gid, "bbl"]:
        assert ex.explain_lot(part, lot, "owner_portfolio").render() == ex.explain_lot(full, lot, "owner_portfolio").render()


def test_a_deed_parcel_left_out_by_the_hub_cap_comes_along_as_a_bystander(parent):
    """OP-9032 cites a deed that also covers the hub node 9030's parcel. The deed keeps all its
    parcels, so 9030's lot is in the excerpt, but nothing about 9030's identity or group."""
    tables, manifest = parent
    out, _ = excerpt_release(tables, manifest, ["OP-9032"])
    assert set(out["evidence_members"]["node_id"]) == {"9030", "9032", "9033"}
    assert "9030" in set(out["node_observations"]["node_id"].astype(str))
    assert "9030" not in set(out["group_members"]["node_id"]) and "9030" not in set(out["node_cluster"]["node_id"])
    assert out["evidence_items"]["parcel_count"].astype(int).tolist() == [3]
    # the event about the hub is kept: its subject is in the excerpt
    assert "deed_hub_capped" in set(out["decision_events"]["reason_code"].dropna())


def test_events_that_point_outside_are_left_out_and_counted(parent):
    tables, manifest = parent
    out, m = excerpt_release(tables, manifest, ["OP-9001"])
    ev = out["decision_events"]
    ids = set(out["identity_clusters"]["identity_id"])
    for side in ("subject", "counterpart"):
        typed = ev[ev[f"{side}_type"] == "identity"][f"{side}_id"]
        assert set(typed) <= ids
    assert m["excerpt"]["events_omitted"] == len(tables["decision_events"]) - len(ev) > 0


def test_a_lot_summary_row_survives_with_the_parents_reason(parent):
    tables, manifest = parent
    out, _ = excerpt_release(tables, manifest, ["OP-9001"])
    s = out["bbl_status"].set_index(["layer", "bbl"])
    assert s.loc[("owner_portfolio", "9000100005"), "reason_code"] == "coop_condo_excluded"
    assert s.loc[("owner_portfolio", "9000100005"), "status"] == "excluded_from_footprint"
    # a lot's row in a group that was not kept is not kept
    assert set(out["bbl_status"]["group_id"].dropna()) <= {"OP-9001"}


def test_masked_address_degree_stays_the_parents_in_an_excerpt():
    """An excerpt lists only the nodes it kept, so degree is at least the rows, not equal to them."""
    t, m = read_release(SYN)
    out, mm = excerpt_release(t, m, ["OP-9060"])
    assert out["masked_addresses"]["degree"].astype(int).tolist() == [4]
    assert out["masked_address_nodes"]["node_id"].tolist() == ["9061"]    # the only node of OP-9060 at the address
    rows = lambda manifest: {(v.table, v.check) for v in _errors(out, manifest) if v.table != "manifest"}
    assert rows(mm) == set()
    # the same tables presented as a whole release are wrong: degree != rows
    whole = copy.deepcopy(mm)
    whole.pop("excerpt")
    assert rows(whole) == {("masked_addresses", "degree")}


def test_only_owner_portfolios_of_the_release_can_be_seeds(parent):
    tables, manifest = parent
    with pytest.raises(ValueError, match="operational networks are not supported"):
        excerpt_release(tables, manifest, ["ON-9060"])
    with pytest.raises(ValueError, match="not an Owner Portfolio of this release"):
        excerpt_release(tables, manifest, ["OP-1"])
    with pytest.raises(ValueError):
        excerpt_release(tables, manifest, [])


def test_the_manifest_does_not_record_where_it_was_built(parent):
    """A path on the builder's disk is not provenance; the tree hash and revision are."""
    from bor.manifest import code_state
    state = code_state()
    assert all("checkout" not in pkg for pkg in state.values())
