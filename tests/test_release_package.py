"""bor.release_package: publishing cannot be taken back, so only a clean, validated, whole release goes out."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from bor import manifest as mf
from bor.release_package import ALLOWED, package_release
from bor.release_schema import ReleaseInputError

SYN = Path(__file__).parent / "fixtures" / "synthetic_release"


def _release(tmp_path, *, synthetic=False, version="0.1.0", dirty=False, excerpt=None):
    """A copy of the synthetic fixture made to look like a clean, released build."""
    d = tmp_path / "rel"
    shutil.copytree(SYN, d)
    m = json.loads((d / "manifest.json").read_text())
    m.pop("output_checksums")
    if not synthetic:
        m.pop("synthetic")
    m["code"] = {"bor": {"version": version, "dirty": dirty}, "nlr": {"version": "0.2.0", "dirty": False}}
    if excerpt:
        m["excerpt"] = excerpt
    mf.write_manifest(d, m)
    return d


def test_a_clean_validated_release_is_zipped_with_a_checksum_and_notes(tmp_path):
    r = package_release(_release(tmp_path), tmp_path / "dist")
    assert r["zip"].name == "bor-v0.1.0-synthetic-2026-10-22.zip" and r["version"] == "0.1.0"
    with zipfile.ZipFile(r["zip"]) as z:
        names = z.namelist()
        assert names == sorted(names) and {n.split("/")[0] for n in names} == {"bor-v0.1.0-synthetic-2026-10-22"}
        assert {n.split("/")[1] for n in names} <= ALLOWED and "bor-v0.1.0-synthetic-2026-10-22/manifest.json" in names
        assert z.testzip() is None
    line = r["sha256"].read_text()
    assert line == f"{hashlib.sha256(r['zip'].read_bytes()).hexdigest()}  {r['zip'].name}\n"
    notes = " ".join(r["notes"].read_text().split())                     # the paragraphs are wrapped
    assert "No owner names" in notes and "synthetic-0001" in notes and "complete through 2026-10-22" in notes
    assert "shasum -a 256 -c bor-v0.1.0-synthetic-2026-10-22.zip.sha256" in notes and r["digest"] in notes
    assert "lead, not a determination of ownership" in notes


def test_the_same_release_always_gives_the_same_checksum(tmp_path):
    d = _release(tmp_path)
    a = package_release(d, tmp_path / "one")["digest"]
    shutil.rmtree(tmp_path / "one")
    assert package_release(d, tmp_path / "two")["digest"] == a


@pytest.mark.parametrize("bad, why", [
    (dict(synthetic=True), "synthetic"),
    (dict(excerpt={"of_run_id": "x"}), "excerpt"),
    (dict(dirty=True), "unclean"),
    (dict(version="0.1.0.dev0"), "development version"),
])
def test_what_should_not_be_published_is_refused(tmp_path, bad, why):
    with pytest.raises(ReleaseInputError, match=why):
        package_release(_release(tmp_path, **bad), tmp_path / "dist")
    assert not (tmp_path / "dist").exists() or not list((tmp_path / "dist").iterdir())


def test_a_file_that_is_not_part_of_a_release_is_refused_by_name(tmp_path):
    """The case that matters: an export left in the directory, with owner names in it."""
    d = _release(tmp_path)
    (d / "owner_groups.csv").write_text("owner_group_id,name\n1,SOMEONE\n")
    (d / "notes.txt").write_text("scratch")
    with pytest.raises(ReleaseInputError) as e:
        package_release(d, tmp_path / "dist")
    assert "owner_groups.csv" in str(e.value) and "notes.txt" in str(e.value) and "not part of a release" in str(e.value)
    assert not (tmp_path / "dist").exists()


def test_a_release_that_does_not_validate_or_lacks_its_pieces_is_refused(tmp_path):
    d = _release(tmp_path)
    (d / "groups.csv").write_text((d / "groups.csv").read_text() + "\n")           # checksum no longer holds
    with pytest.raises(ReleaseInputError, match="does not validate"):
        package_release(d, tmp_path / "dist")
    d2 = _release(tmp_path / "x")
    (d2 / "DATA.md").unlink()
    with pytest.raises(ReleaseInputError, match="needs DATA.md"):
        package_release(d2, tmp_path / "dist")
    with pytest.raises(ReleaseInputError, match="not a directory"):
        package_release(tmp_path / "nowhere", tmp_path / "dist")
    (tmp_path / "empty").mkdir()
    with pytest.raises(ReleaseInputError, match="no manifest.json"):
        package_release(tmp_path / "empty", tmp_path / "dist")


def test_every_table_file_a_release_may_hold_is_a_contract_table():
    from bor.release_schema import TABLES
    assert ALLOWED == {f"{t}.csv" for t in TABLES} | {"DATA.md", "manifest.json"}
