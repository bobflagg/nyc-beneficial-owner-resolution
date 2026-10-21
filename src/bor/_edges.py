"""Shared edge-construction kernel for the identity edge builders.

Every identity-edge source (record-linkage model, curated, registered-LLC, deed) emits, per
resolved group, either a full clique or a bounded hub-and-spoke star, as ``(src, dst, weight)``
rows over ``landlords_with_connections`` nodeids. ``weight`` is uniform — the Owner Portfolio layer
takes plain connected components, so edge weights carry no ranking, only presence.

These constants and helper are lifted verbatim from WatchlineNYC's ``portfolio`` pipeline so the
edges BOR builds are byte-identical to the ones that produced the live graph (parity is the
acceptance test). Kept in one place here rather than forked per-module.
"""
from __future__ import annotations

from itertools import combinations

SPLINK_WEIGHT = 100.0   # uniform weight on every identity edge (presence, not rank)
STAR_ABOVE = 150        # groups larger than this emit a hub-star, not a full clique (edge-count bound)


def _clique_rows(ids, star_above: int = STAR_ABOVE) -> list[tuple[int, int]]:
    """A full clique for a group, or a hub-and-spoke star above ``star_above`` to bound edges."""
    ids = sorted(ids)
    if len(ids) < 2:
        return []
    if len(ids) <= star_above:
        return list(combinations(ids, 2))
    return [(ids[0], d) for d in ids[1:]]
