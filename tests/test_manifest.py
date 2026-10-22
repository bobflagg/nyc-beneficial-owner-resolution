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

BASIS = {"real_property_master.recordedfiled": {"newest": "2026-10-21", "future_dated_rows": 0},
         "hpd_registrations.lastregistrationdate": {"newest": "2026-10-21", "future_dated_rows": 0}}


def _manifest(**kw):
    kw.setdefault("basis", BASIS)
    return mf.build_manifest(_FakeConn(), snapshot_id="test-2026-10-21", as_of=date(2026, 10, 21),
                             resolution_params={"threshold": 0.999, "seed": 42},
                             tables=("hpd_contacts",), **kw)


def test_manifest_has_every_required_field_but_the_checksums():
    m = _manifest()
    assert set(MANIFEST_REQUIRED) - {"output_checksums"} <= set(m)
    assert m["snapshot_id"] == "test-2026-10-21" and m["snapshot_date"] == "2026-10-21"
    assert m["snapshot_date_basis"] == BASIS and "pluto_snapshot_id" not in m      # PLUTO is part of the dump
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


# --- a package installed from a git commit (the pinned nlr) -----------------------------------------------------

class _Dist:
    """pip's direct_url.json for a package installed from a git commit, or none."""
    version = "1.0"

    def __init__(self, text):
        self.text = text

    def read_text(self, name):
        return self.text


def _state(tmp_path, monkeypatch, direct_url):
    (tmp_path / "m.py").write_text("x = 1\n")
    monkeypatch.setattr(mf.md, "distribution", lambda name: _Dist(direct_url))
    return mf._package_state(tmp_path, "pandas", None)       # tmp_path is not in a git checkout


def test_a_package_installed_from_a_git_commit_is_identified_and_can_be_built_from(tmp_path, monkeypatch):
    """The pinned nlr is installed, not checked out: its commit comes from pip, and --require-clean must
    accept it (dirty=None means 'unidentified' and is refused)."""
    s = _state(tmp_path, monkeypatch, json.dumps({"url": "https://example.test/x.git",
                                                   "vcs_info": {"vcs": "git", "commit_id": "abc123"}}))
    assert s["revision"] == "abc123" and s["dirty"] is False and len(s["tree_hash"]) == 64


def test_an_installed_package_with_no_known_commit_stays_unidentified(tmp_path, monkeypatch):
    for text in (None, "{}", json.dumps({"url": "file:///wheel"})):
        s = _state(tmp_path, monkeypatch, text)
        assert s["revision"] is None and s["dirty"] is None


# --- the snapshot id and date (KG design note 0008) ---------------------------------------------------------------

class _DateConn:
    """Answers the two 'newest date' queries: (newest, rows dated after today)."""
    def __init__(self, *answers):
        self.answers, self.sql = list(answers), []

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        return self.answers.pop(0)


def test_the_newest_dates_are_read_from_the_two_columns_and_future_rows_are_counted_not_used():
    conn = _DateConn((date(2026, 5, 29), 0), (date(2026, 5, 29), 2))
    basis = mf.snapshot_basis(conn, today=date(2026, 10, 22))
    assert basis == {"real_property_master.recordedfiled": {"newest": "2026-05-29", "future_dated_rows": 0},
                     "hpd_registrations.lastregistrationdate": {"newest": "2026-05-29", "future_dated_rows": 2}}
    sql, params = conn.sql[0]
    assert "FROM real_property_master" in sql and "recordedfiled" in sql and "FILTER (WHERE" in sql
    assert params == (date(2026, 10, 22), date(2026, 10, 22))
    assert "hpd_registrations" in conn.sql[1][0] and "lastregistrationdate" in conn.sql[1][0]


def test_the_snapshot_date_is_the_earlier_of_the_newest_dates():
    basis = {"a.x": {"newest": "2026-07-02", "future_dated_rows": 0}, "b.y": {"newest": "2026-05-29", "future_dated_rows": 0}}
    assert mf.snapshot_date(basis) == date(2026, 5, 29)
    with pytest.raises(ValueError, match="cannot date the snapshot"):
        mf.snapshot_date({"a.x": {"newest": None, "future_dated_rows": 0}})


@pytest.mark.parametrize("good", ["justfixwow-2026-05-29", "justfixwow-2026-05-29-r2", "dos-2026-05-29-r12"])
def test_a_snapshot_id_of_the_agreed_form_with_the_datas_date_is_accepted(good):
    mf.check_snapshot_id(good, date(2026, 5, 29))


@pytest.mark.parametrize("bad, why", [
    ("justfixwow-2026-10-21", "build day"),                  # the date is not the data's
    ("JustFix-2026-05-29", "must look like"), ("justfixwow_2026-05-29", "must look like"),
    ("2026-05-29", "must look like"), ("justfixwow-20260529", "must look like"),
    ("just-fix-2026-05-29", "must look like"), ("justfixwow-2026-05-29-r", "must look like"),
    ("a" * 30 + "-2026-05-29", "at most 40"),
])
def test_a_snapshot_id_of_the_wrong_form_or_with_the_wrong_date_is_refused(bad, why):
    with pytest.raises(ValueError) as e:
        mf.check_snapshot_id(bad, date(2026, 5, 29))
    assert (why if why != "build day" else "not the snapshot date") in str(e.value)


def test_the_build_refuses_an_id_that_disagrees_with_the_data():
    with pytest.raises(ValueError, match="not the snapshot date"):
        mf.build_manifest(_FakeConn(), snapshot_id="test-2026-10-22", as_of=date(2026, 10, 22), basis=BASIS,
                          resolution_params={"threshold": 0.999}, tables=("hpd_contacts",))


def _violations(**changes):
    m = _manifest()
    m["output_checksums"] = {}
    m.update(changes)
    return {(v.check, v.message) for v in check_manifest(m) if v.table == "manifest"}


def test_the_validator_checks_the_snapshot_id_the_date_and_the_basis():
    assert not [c for c, _ in _violations() if c.startswith("snapshot")]
    assert any(c == "snapshot_id" for c, _ in _violations(snapshot_id="Test_2026-10-21"))
    assert any(c == "snapshot_date" and "carries 2026-10-21" in m for c, m in _violations(snapshot_date="2026-10-22"))
    assert any(c == "snapshot_date" and "not an ISO date" in m for c, m in _violations(snapshot_date="yesterday"))
    later = {k: dict(v, newest="2026-10-30") for k, v in BASIS.items()}
    assert any(c == "snapshot_date_basis" and "earlier of the newest" in m for c, m in _violations(snapshot_date_basis=later))
    gap = {"x.a": {"newest": None, "future_dated_rows": 0}}
    assert any(c == "snapshot_date_basis" for c, _ in _violations(snapshot_date_basis=gap))


def test_the_reference_dump_dates_itself_to_2026_05_29(pg):
    """Needs Postgres: both columns end on the same day, so the snapshot is justfixwow-2026-05-29."""
    basis = mf.snapshot_basis(pg)
    assert {e["newest"] for e in basis.values()} == {"2026-05-29"} and mf.snapshot_date(basis) == date(2026, 5, 29)
    assert all(e["future_dated_rows"] >= 0 for e in basis.values())
    mf.check_snapshot_id("justfixwow-2026-05-29", mf.snapshot_date(basis))
