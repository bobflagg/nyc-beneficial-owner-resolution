"""The name tables (contract 0.2.0): who the ids stand for, as filed, for reading and never for joining.

No database: the synthetic fixture carries made-up names ("FIXTURE" is every surname and company), and the pure
helpers are checked directly. The real build is checked against Postgres in test_integration.py."""
import copy
import os

import pandas as pd
import pytest

from bor import explain as ex
from bor import names
from bor.excerpt import excerpt_release, write_excerpt
from bor.release_schema import TABLES
from bor.release_validate import read_release, validate_release

SYN = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic_release")
NAME_TABLES = ("observation_contacts", "identity_names", "node_names", "deed_documents", "deed_parties", "lot_addresses")


@pytest.fixture(scope="module")
def parent():
    return read_release(SYN)


def _errors(tables, manifest):
    return [v for v in validate_release(tables, manifest) if v.severity == "error"]


def test_the_contract_lists_the_name_tables_and_they_are_in_the_fixture(parent):
    tables, manifest = parent
    assert set(NAME_TABLES) <= set(TABLES) and set(NAME_TABLES) <= set(tables)
    assert manifest["schema_version"] == "0.2.0"
    assert _errors(tables, manifest) == []


def test_every_id_has_a_name(parent):
    t, _ = parent
    assert set(t["observations"]["observation_id"]) == set(t["observation_contacts"]["observation_id"])
    assert set(t["identity_clusters"]["identity_id"]) <= set(t["identity_names"]["identity_id"])
    assert set(t["node_observations"]["node_id"].astype(str)) == set(t["node_names"]["node_id"].astype(str))
    assert set(names.cited_documents(t)) == set(t["deed_documents"]["document_id"])
    assert set(names.named_lots(t)) == set(t["lot_addresses"]["bbl"])


@pytest.mark.parametrize("table,key", [("observation_contacts", "observation_id"), ("identity_names", "identity_id"),
                                       ("node_names", "node_id"), ("deed_documents", "document_id")])
def test_a_missing_name_row_is_an_error(parent, table, key):
    t, m = parent
    t = copy.copy(t)
    t[table] = t[table].iloc[1:]
    found = [v for v in validate_release(t, m) if v.check == "names_cover"]
    assert found and found[0].table == table and found[0].severity == "error"


def test_a_lot_pluto_does_not_list_is_only_a_warning(parent):
    t, m = parent
    t = copy.copy(t)
    t["lot_addresses"] = t["lot_addresses"].iloc[1:]
    found = [v for v in validate_release(t, m) if v.check == "names_cover"]
    assert found and all(v.severity == "warning" for v in found)


def test_a_release_without_name_tables_still_validates(parent):
    t, m = parent
    bare = {k: v for k, v in t.items() if k not in NAME_TABLES}
    assert _errors(bare, m) == []


def test_the_fixture_names_are_made_up_and_a_corporation_has_no_person_fields(parent):
    t, _ = parent
    oc = t["observation_contacts"]
    corp = oc[oc["contact_type"] == "CorporateOwner"]
    assert len(corp) and corp["first_name"].isna().all() and corp["corporation_name"].notna().all()
    people = oc[oc["contact_type"] == "IndividualOwner"]
    assert people["last_name"].str.startswith("FIXTURE").all()
    assert t["deed_parties"]["name"].str.startswith("FIXTURE").all()


def test_deed_parties_are_numbered_within_a_document_and_side(parent):
    p = parent[0]["deed_parties"]
    assert set(p["party_type"]) == {"grantor", "grantee"}
    assert not p.duplicated(["document_id", "party_type", "party_index"]).any()


def test_an_excerpt_carries_exactly_the_names_of_what_it_keeps(parent, tmp_path):
    t, m = parent
    out, m2 = excerpt_release(t, m, ["OP-9010"])
    assert set(NAME_TABLES) <= set(out)
    assert set(out["observation_contacts"]["observation_id"]) == set(out["observations"]["observation_id"])
    assert set(out["node_names"]["node_id"].astype(str)) == set(out["node_observations"]["node_id"].astype(str))
    assert set(out["deed_documents"]["document_id"]) == set(names.cited_documents(out))
    assert set(out["deed_parties"]["document_id"]) <= set(out["deed_documents"]["document_id"])
    assert len(out["identity_names"]) < len(t["identity_names"])
    path = write_excerpt(out, m2, tmp_path / "x")
    t2, m3 = read_release(str(path))
    assert [v for v in validate_release(t2, m3, path=str(path)) if v.severity == "error"] == []


def test_explain_names_the_nodes_the_deeds_and_the_lots(parent):
    rel = ex.Release(*parent)
    text = ex.explain_group(rel, "OP-9010").render()
    assert "PAT9010 FIXTUREB (node 9010)" in text
    lot = ex.explain_lot(rel, "9000200001", "owner_portfolio").render()
    assert "2-1 FIXTURE AVENUE" in lot and "PAT9010 FIXTUREB" in lot
    pair = ex.explain_pair(rel, "9000200001", "9000200003").render()
    assert "FIXTURE GRANTOR LLC to FIXTURE GRANTEE LLC" in pair


def test_explain_without_name_tables_is_as_before(parent):
    t, m = parent
    bare = ex.Release({k: v for k, v in t.items() if k not in NAME_TABLES}, m)
    text = ex.explain_group(bare, "OP-9010").render()
    assert "PAT9010" not in text and "Its nodes:" not in text
    assert "ACRIS deed" in ex.explain_pair(bare, "9000200001", "9000200003").render()


def test_helpers_collect_what_the_tables_cite():
    T = {"evidence_items": pd.DataFrame({"document_id": ["D1"]}),
         "evidence_members": pd.DataFrame({"original_document_id": ["D1"], "latest_document_id": ["D2"], "bbl": ["3000010001"]}),
         "decision_support": pd.DataFrame({"support_type": ["document", "bbl"], "support_id": ["D3", "3000010002"]}),
         "decision_events": pd.DataFrame({"subject_type": ["deed_document", "parcel"], "subject_id": ["D4", "3000010003"],
                                          "counterpart_type": [None, None], "counterpart_id": [None, None]}),
         "group_bbls": pd.DataFrame({"bbl": ["3000010004"]}), "node_observations": pd.DataFrame({"bbl": ["3000010005"]})}
    assert names.cited_documents(T) == ["D1", "D2", "D3", "D4"]
    assert names.named_lots(T) == ["3000010001", "3000010003", "3000010004", "3000010005"]
