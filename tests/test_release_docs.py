"""DATA.md is generated from the contract and the release, so it cannot drift from either."""
import hashlib
import os

import pytest

from bor.release_docs import render_data_md, write_data_md
from bor.release_schema import ADJUDICATION_STATUSES, PRECEDENCE, REASON_CODES, STAGES, TABLES
from bor.release_validate import read_release

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
SYN, CIT = os.path.join(FIX, "synthetic_release"), os.path.join(FIX, "citadel_excerpt")


@pytest.fixture(scope="module")
def syn():
    tables, manifest = read_release(SYN)
    return manifest, tables, render_data_md(manifest, tables)


def test_every_table_column_and_vocabulary_term_is_documented(syn):
    _, tables, text = syn
    for name, t in TABLES.items():
        if name in tables:
            assert f"### `{name}`" in text and f"`{name}.csv`" in text
            assert all(f"| `{c.name}` |" in text for c in t.columns)
        else:
            assert f"### `{name}`" not in text
    assert all(f"`{s}`" in text for s in (*STAGES, *REASON_CODES, *PRECEDENCE, *ADJUDICATION_STATUSES))


def test_it_says_what_the_release_is_and_what_it_is_not(syn):
    manifest, _, text = syn
    text = " ".join(text.split())                                   # the intro is wrapped
    assert "synthetic** release of made-up lots" in text and "contains no owner names" in text
    assert "leads, not verdicts" in text and "not* the probability that a given link is right" in text
    assert "missing row in `bbl_status` means nothing" in text
    assert f"`{manifest['run_id']}`" in text and f"`{manifest['snapshot_id']}`" in text
    assert "`synthetic`" in text                                    # the gold status of its metrics


def test_row_counts_come_from_the_tables(syn):
    _, tables, text = syn
    assert f"| `groups.csv` | {len(tables['groups']):,} |" in text
    assert f"| `bbl_status.csv` | {len(tables['bbl_status']):,} |" in text


def test_an_excerpt_says_whose_it_is_and_lists_only_the_tables_it_has():
    tables, manifest = read_release(CIT)
    text = render_data_md(manifest, tables)
    assert f"an **excerpt** of run {manifest['run_id']}" in text and "### `network_edges`" not in text
    dirty = any(c.get("dirty") for c in manifest["code"].values())
    assert ("Built from an uncommitted tree" in text) == dirty      # said when true, absent when not
    assert "hpd_contacts" in text and "synthetic" not in text.lower().split("provenance")[0]


def test_rendering_again_from_a_finished_release_gives_the_same_bytes_so_the_checksums_hold(tmp_path):
    """DATA.md is checksummed in the manifest, so it must not depend on the checksums."""
    import shutil
    work = tmp_path / "rel"
    shutil.copytree(SYN, work)
    tables, manifest = read_release(str(work))
    before = (work / "manifest.json").read_text()
    path = write_data_md(work, manifest, tables)
    again = path.read_bytes()
    assert render_data_md({k: v for k, v in manifest.items() if k != "output_checksums"}, tables).encode() == again
    assert hashlib.sha256(again).hexdigest() == manifest["output_checksums"]["DATA.md"]
    assert (work / "manifest.json").read_text() == before
