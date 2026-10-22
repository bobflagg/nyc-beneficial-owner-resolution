"""`python -m bor.release build`: a caller's mistake is one line, not a traceback."""
import json
import sys
from datetime import date

import pytest

from bor import release
from bor.metrics import load_evaluation, method_metrics_table
from bor.release_schema import ReleaseInputError


class _Conn:
    """Answers the two 'newest date' queries (the dump's data ends 2026-05-29) and nothing else."""
    closed = False

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return (date(2026, 5, 29), 0)

    def close(self):
        self.closed = True


def _run(monkeypatch, *args):
    conn = _Conn()
    monkeypatch.setattr("bor.db.pg_conn", lambda: conn)
    monkeypatch.setattr(sys, "argv", ["bor.release", "build", "out", *args])
    with pytest.raises(SystemExit) as e:
        release.main()
    return e.value.code, conn


def test_an_id_with_the_build_day_instead_of_the_datas_date_is_one_line(monkeypatch):
    code, conn = _run(monkeypatch, "--snapshot-id", "justfixwow-2026-10-21")
    assert isinstance(code, str) and code.startswith("error: snapshot id 'justfixwow-2026-10-21' carries 2026-10-21")
    assert "complete through 2026-05-29" in code and "\n" not in code
    assert conn.closed                                          # the connection is closed on the way out


def test_an_id_of_the_wrong_form_is_one_line(monkeypatch):
    code, _ = _run(monkeypatch, "--snapshot-id", "JustFix_2026")
    assert code.startswith("error: snapshot id 'JustFix_2026' must look like <source>-<YYYY-MM-DD>")


def test_an_evaluation_without_its_gold_status_is_one_line(monkeypatch, tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"strata": {}}))
    code, _ = _run(monkeypatch, "--snapshot-id", "justfixwow-2026-05-29", "--eval-dir", str(tmp_path))
    assert code.startswith("error: say who produced the gold (--gold-status)")


def test_a_missing_evaluation_is_one_line(monkeypatch, tmp_path):
    code, _ = _run(monkeypatch, "--snapshot-id", "justfixwow-2026-05-29", "--eval-dir", str(tmp_path / "nope"))
    assert code.startswith("error: no metrics.json in") and "bor.eval.score" in code


def test_the_errors_are_a_kind_of_value_error_and_a_bug_is_not_swallowed(monkeypatch):
    assert issubclass(ReleaseInputError, ValueError)
    conn = _Conn()
    monkeypatch.setattr("bor.db.pg_conn", lambda: conn)
    monkeypatch.setattr(sys, "argv", ["bor.release", "build", "out", "--snapshot-id", "justfixwow-2026-05-29"])

    def boom(*a, **k):
        raise KeyError("a bug")
    monkeypatch.setattr(release, "build_release", boom)
    with pytest.raises(KeyError):                               # not turned into a tidy message
        release.main()
    assert conn.closed


def test_the_other_caller_mistakes_in_the_metrics_are_input_errors(tmp_path):
    with pytest.raises(ReleaseInputError):
        method_metrics_table(None, "blind human")
    (tmp_path / "metrics.json").write_text("{}")
    assert load_evaluation(tmp_path)["metrics"] == {}
