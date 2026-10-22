"""One export, one identity resolution: no database."""
import pandas as pd

from bor import export as export_mod


def test_export_fits_splink_once_and_gives_both_layers_the_same_partition(monkeypatch, tmp_path):
    frame = pd.DataFrame({"nodeid": [1, 2, 3], "cluster_id": ["C1", "C1", "C2"]})
    fits, seen = [], {}

    def fake_fit(conn, *, threshold):
        fits.append(threshold)
        return frame

    monkeypatch.setattr(export_mod, "node_clusters", fake_fit)
    monkeypatch.setattr(export_mod, "resolve_owner_portfolios",
                        lambda conn, **kw: seen.setdefault("portfolios", kw["node_cluster_frame"]) is None or [])
    monkeypatch.setattr(export_mod, "resolve_operational_networks",
                        lambda conn, **kw: seen.setdefault("networks", kw["node_cluster_frame"]) is None or [])

    export_mod.export(None, str(tmp_path), threshold=0.998)

    assert fits == [0.998]                                      # one fit, at the threshold asked for
    assert seen["portfolios"] is frame and seen["networks"] is frame


def test_a_resolver_given_a_partition_does_not_fit(monkeypatch):
    """The mechanism both layers rely on: with a frame in hand, splink_edges never calls Splink."""
    from bor import splink_bridge

    def boom(*a, **k):
        raise AssertionError("refit")

    monkeypatch.setattr(splink_bridge, "node_clusters", boom)
    frame = pd.DataFrame({"nodeid": [1, 2, 3], "cluster_id": ["C1", "C1", "C2"]})
    edges = splink_bridge.splink_edges(None, node_cluster_frame=frame)
    assert list(zip(edges["src"], edges["dst"])) == [(1, 2)]


def test_the_real_export_fits_splink_once_and_stays_person_free(pg, tmp_path, monkeypatch):
    """On the reference dump (needs Postgres): one fit for both layers, and no names in the files."""
    from bor import splink_bridge
    real, fits = splink_bridge._resolve, []
    monkeypatch.setattr(splink_bridge, "_resolve", lambda *a, **k: (fits.append(1), real(*a, **k))[1])
    export_mod.export(pg, str(tmp_path))
    assert len(fits) == 1
    assert sorted(f.name for f in tmp_path.iterdir()) == [
        "DATA.md", "operational_network_bbls.csv", "operational_networks.csv",
        "owner_portfolio_bbls.csv", "owner_portfolios.csv"]
    header = (tmp_path / "owner_portfolios.csv").read_text().splitlines()[0]
    assert "name" not in header.split(",") and "contains **no owner names**" in (tmp_path / "DATA.md").read_text()
