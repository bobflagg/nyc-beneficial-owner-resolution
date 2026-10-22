"""The docs link to each other and to files that exist."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]
# review files are the colleagues' working papers, kept as they were written
DOCS = [d for d in DOCS if not d.name.endswith("review.md") and d.name != "review-request-kg-handoff.md"]
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _tracked():
    """The files git tracks, as paths relative to the repository root, or None outside a checkout.
    A link to a file that only exists in someone's working copy is dead in every clone."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return {p for p in out.decode().split("\0") if p}


def _exists(path: Path, tracked) -> bool:
    if tracked is None:
        return path.exists()
    rel = path.resolve().relative_to(ROOT).as_posix()
    return rel in tracked or any(t.startswith(rel.rstrip("/") + "/") for t in tracked)


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_relative_links_point_at_files_that_exist(doc):
    broken, tracked = [], _tracked()
    for target in LINK.findall(doc.read_text()):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue                                              # urls and in-page anchors
        if not _exists(doc.parent / target.split("#")[0], tracked):
            broken.append(target)
    assert broken == []
