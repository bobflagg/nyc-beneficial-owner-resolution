"""The docs link to each other and to files that exist."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]
# review files are the colleagues' working papers, kept as they were written
DOCS = [d for d in DOCS if not d.name.endswith("review.md") and d.name != "review-request-kg-handoff.md"]
LINK = re.compile(r"\]\(([^)\s]+)\)")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_relative_links_point_at_files_that_exist(doc):
    broken = []
    for target in LINK.findall(doc.read_text()):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue                                              # urls and in-page anchors
        if not (doc.parent / target.split("#")[0]).exists():
            broken.append(target)
    assert broken == []
