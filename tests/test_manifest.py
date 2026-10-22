"""The release manifest and the pinned deed cut-off."""
import json
from datetime import date

import pytest

from bor import deed_edges as de
from bor import manifest as mf
from bor.release_schema import MANIFEST_REQUIRED
from bor.release_validate import check_manifest


class _FakeConn:
    """Answers every fingerprint query with the same (row_count, sum)."""
    def cursor(self):
        return self

    def execute(self, sql):
        self.sql = sql

    def fetchone(self):
        return (3, 12345)


# --- fingerprints and hashes -------------------------------------------------------------------

def test_fingerprint_is_an_order_independent_aggregate_over_row_text():
    sql = mf.fingerprint_sql("hpd_contacts")
    assert "FROM hpd_contacts t" in sql and "md5(t::text)" in sql and sql.count("sum(") == 1
    assert "ORDER BY" not in sql


def test_source_tables_records_count_fingerprint_and_method():
    out = mf.source_tables(_FakeConn(), ("hpd_contacts",))
    assert out == {"hpd_contacts": {"row_count": 3, "fingerprint": "12345",
                                    "fingerprint_method": mf.FINGERPRINT_METHOD}}


def test_tree_hash_follows_code_content_and_ignores_the_rest(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql" / "q.sql").write_text("select 1")
    base = mf.tree_hash(tmp_path)
    assert base == mf.tree_hash(tmp_path)                                     # deterministic
    (tmp_path / "notes.md").write_text("ignored")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.cpython-313.pyc.py").write_text("junk")
    assert mf.tree_hash(tmp_path) == base
    (tmp_path / "a.py").write_text("x = 2\n")                                  # a code change moves it
    assert mf.tree_hash(tmp_path) != base


def test_checksums_cover_every_file_but_the_manifest(tmp_path):
    (tmp_path / "t.csv").write_text("a\n1\n")
    (tmp_path / "manifest.json").write_text("{}")
    assert set(mf.file_checksums(tmp_path)) == {"t.csv"}


# --- the manifest ------------------------------------------------------------------------------

def _manifest(**kw):
    return mf.build_manifest(_FakeConn(), snapshot_id="snap-1", as_of=date(2026, 10, 21),
                             resolution_params={"threshold": 0.999, "seed": 42},
                             tables=("hpd_contacts",), **kw)


def test_manifest_has_every_required_field_but_the_checksums():
    m = _manifest()
    assert set(MANIFEST_REQUIRED) - {"output_checksums"} <= set(m)
    assert m["snapshot_id"] == "snap-1" and m["pluto_snapshot_id"] == "snap-1"
    assert m["effective_date"] == "2026-10-21" and m["parameters"]["deed"]["as_of"] == "2026-10-21"
    assert m["threshold"] == 0.999
    assert m["deed_selection_rule"]["rule"] == de.DEED_DOCTYPE_RULE


def test_the_code_that_ran_is_identified_by_content():
    m = _manifest()
    assert len(m["source_tree_hash"]) == 64 and m["code"]["bor"]["tree_hash"] and m["code"]["nlr"]["tree_hash"]
    assert m["source_tree_hash"] == mf.combined_tree_hash(m["code"])
    assert m["environment"]["splink"] == "4.0.16"


def test_run_id_defaults_to_the_date_and_a_nonce_and_can_be_set():
    a, b = _manifest(), _manifest()
    assert a["run_id"].startswith("2026-10-21-") and a["run_id"] != b["run_id"]
    assert _manifest(run_id="fixed")["run_id"] == "fixed"


def test_written_manifest_checksums_the_files_and_passes_the_contract_check(tmp_path):
    (tmp_path / "observations.csv").write_text("observation_id\n1:2:0\n")
    m = _manifest(artifacts={"observations": "complete"})
    path = mf.write_manifest(tmp_path, m)
    written = json.loads(path.read_text())
    assert list(written["output_checksums"]) == ["observations.csv"]
    assert check_manifest(written, str(tmp_path)) == []
    (tmp_path / "observations.csv").write_text("tampered\n")
    assert [v.check for v in check_manifest(written, str(tmp_path))] == ["checksum"]


# --- the deed cut-off is a recorded date, not CURRENT_DATE --------------------------------------

def test_no_deed_query_uses_current_date():
    d = date(2026, 10, 21)
    assert "CURRENT_DATE" not in de._deed_sql(25, d)
    assert "CURRENT_DATE" not in de._JOINT_SQL.format(max_parcels=25, as_of=de._as_of_sql(d))
    assert "CURRENT_DATE" not in de._LATEST_SQL.replace("__AS_OF__", de._as_of_sql(d))
    assert "CURRENT_DATE" not in de._LATEST_TIES_SQL.replace("__AS_OF__", de._as_of_sql(d))


def test_the_given_date_reaches_every_query():
    d = date(2026, 10, 21)
    assert "DATE '2026-10-21'" in de._deed_sql(25, d)
    assert "DATE '2026-10-21'" in de._JOINT_SQL.format(max_parcels=25, as_of=de._as_of_sql(d))
    assert "DATE '2026-10-21'" in de._LATEST_SQL.replace("__AS_OF__", de._as_of_sql(d))
    assert de._as_of_sql(None) == f"DATE '{date.today().isoformat()}'"


def test_as_of_must_be_a_date():
    with pytest.raises(TypeError):
        de._as_of_sql("2026-10-21")


def test_the_recorded_doctype_rule_is_the_one_the_queries_apply():
    needle = de.DEED_DOCTYPE_RULE.replace("doctype", "m.doctype").replace("%", "%%")
    assert needle in de._LATEST_SQL and needle in de._deed_sql(25) and needle in de._JOINT_SQL


# --- a real release (needs the database) -------------------------------------------------------

def test_a_real_release_directory_is_valid_and_checksummed(release_build):
    _, r = release_build
    errors = [v for v in r["violations"] if v.severity == "error"]
    assert errors == [], errors
    m = r["manifest"]
    assert m["source_tables"]["landlords_with_connections"]["row_count"] == 118_493
    assert m["source_tables"]["wow_landlords"]["row_count"] == 171_347
    assert set(m["source_tables"]) == set(mf.SOURCE_TABLES)
    assert m["effective_date"] == "2026-10-21" and isinstance(m["diagnostics"]["latest_deed_ties"], int)
    assert set(m["output_checksums"]) == {f"{n}.csv" for n in m["artifacts"]} | {"DATA.md"}   # DATA.md is covered too
