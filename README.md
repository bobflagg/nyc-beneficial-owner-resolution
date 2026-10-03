# NYC Beneficial Owner Resolution

**Reliability-typed beneficial-ownership resolution over NYC public records.** Given the
city's public registration and deed record, it decides *who is behind a building* — and,
unlike registration clustering, it separates three claims of different evidentiary weight
(**operation**, **management**, **ownership**) and types each as **directly-sourced** or
**inferred**. Every derived link reads as an investigative lead, not a legal determination.

This is the software + data + benchmark artifact for the paper *"Leads, Not Verdicts:
Reliability-Typed Beneficial-Ownership Resolution for Housing Accountability."* It builds on
JustFix's [Who Owns What](https://github.com/JustFixNYC/who-owns-what) (WoW) — crediting and
benchmarking against it, not replacing it — and on the standalone record-linkage engine
[`nyc-landlord-resolution`](https://github.com/bobflagg/nyc-landlord-resolution) (`nlr`).

> **Status: v1 + v1.1 built & validated.** All three layers — beneficial owner group, deed
> veil-pierce, and operational network — plus the paired WoW benchmark run off-graph and reproduce
> the live knowledge graph's partition (owner groups 100% of nodes; operational network 99.9% of
> portfolios, the tail being Louvain — see [`docs/parity.md`](docs/parity.md)). See the roadmap.

## What it resolves

Registration clustering fails in two opposite, *asymmetrically harmful* directions:

- **False split** — one owner, fragmented across differently-named LLCs and typo'd offices,
  reads as many owners → a real owner evades accountability (harm borne by tenants).
  **Fixed** by probabilistic record linkage (`nlr`) → `CONNECTED_BY_SPLINK`.
- **False merge** — separate owners sharing a registration office read as one → buildings are
  over-attributed to a party (wrongful-targeting / defamation risk). **Fixed** by resolving
  ownership as its own community from ownership signals only, never a shared address.

### The layers (each separately typed)

| Layer | Question | Signals | Status |
|---|---|---|---|
| **Beneficial owner group** | Who *owns* it? | `CONNECTED_BY_SPLINK` ∪ `CONNECTED_BY_DEED` | **v1** |
| **Deed veil-pierce** | co-owned by conveyance? | ACRIS multi-parcel deed + linked-successor guard | **v1** |
| **Operational network** | What does it *operate through*? | name / address / splink, aggregator-masked (WCC + Louvain) | **v1.1 ✓** |
| **Management** | Who *runs* it? | `MANAGED_BY` (disclosed agent) | (in WatchlineNYC) |

The **deed veil-pierce** is the signature move: a name-free link from a shared ACRIS deed,
with a *linked-successor guard* that reaches owners who bought a block together and re-deeded
each building into its own `$0` single-purpose shell — the case no name/address method can see.
Precision hygiene: **aggregator-address masking** and **co-op/condo exclusion** (co-ops/condos
are owned by shareholders, not a landlord) remove management artifacts a naive inference mints.

## Install

```bash
uv sync                     # installs nlr from its pinned git tag (public; HTTPS, no creds)
cp .env.example .env        # set PG* for the NYC public-record Postgres (see docs/data.md)
uv run python -m bor.build_lwc   # build landlords_with_connections from wow_landlords (~1-2 min)
```

BOR depends only on the *data* — a Postgres seeded from JustFix's public `justfixwow` dump — not on
any WatchlineNYC pipeline; it builds the one derived table (`landlords_with_connections`) itself.
See [`docs/data.md`](docs/data.md) for the required tables and where they come from.

## Use

```python
from bor import resolve_owner_groups, bbl_assignments
from bor.db import pg_conn

with pg_conn() as conn:
    groups = resolve_owner_groups(conn)     # list[OwnerGroup], computed off-graph (no Neo4j)

by_bbl = bbl_assignments(groups)            # {bbl: owner_group_id} — the person-free export key
biggest = max(groups, key=lambda g: g.building_count)
print(biggest.owner_group_id, biggest.name, biggest.building_count, biggest.composition)
```

Each `OwnerGroup` carries its `members` (landlord identities), attributed rental `bbls`, the full
`total_bbls` footprint, a `composition` (`identity` / `deed_only` / `deed_bridged`), and a person
anchor `name`. The deed layer on its own is `bor.deed_edges.deed_edges(conn)`.

The **operational network** (the WoW-baseline "what it operates through" layer) is a separate call:

```python
from bor import resolve_operational_networks

with pg_conn() as conn:
    nets = resolve_operational_networks(conn)   # list[OperationalNetwork]; WCC + Louvain, off-graph
# each carries members, bbls, building_count, and split ('wcc' = exact | 'louvain' = oversized tail)
```

## Evaluate — the paired benchmark against Who Owns What

A paired head-to-head against `wow.wow_portfolios`: where, and in which direction, the owner-group
partition diverges from WoW's registration clustering (a *divergence* measure, not accuracy —
adjudication decides who is right). On the current graph:

```bash
uv run python -m bor.eval.divergence
# → 760 owners cross WoW portfolios (WoW split them); 616 WoW portfolios hide >1 owner (WoW merged them)
```

The **WoW gate** is a library check — does WoW genuinely split a group's members into ≥2
non-aggregator portfolios (a real veil-pierce), or over-lump them on a shared aggregator address?

```python
from bor.eval.gate import gate_bbls
result = gate_bbls(conn, member_bbls)       # GateResult(passed, reasons, ...)
```

The full adjudication protocol (an **INDETERMINATE** class, a **circularity control**, and a
**data-vintage control**) and the worked case studies (Croman, Escobar, Miller, Levitov, AXL,
Citadel) are tracked for the release phase — see the roadmap.

## How it relates to the other repos

```
nlr  (record linkage / false-split resolution)         ── standalone, gold-validated
  └── nyc-beneficial-owner-resolution  (this repo)      ── + deed, owner groups, benchmark  [KG-free]
        └── WatchlineNYC  (the deployed product)        ── materializes the export into Neo4j; UI + agent
```

BOR is **KG-free** — it runs over Postgres (v1) and never requires Neo4j. WatchlineNYC consumes
BOR's export and is where the Neo4j graph, the conversational agent, and the public site live.

## Roadmap

- **v1 (built & validated)** — beneficial owner group + deed veil-pierce + the paired WoW
  divergence + the WoW gate, computed off-graph from Postgres and reproducing the live-graph
  partition ([`docs/parity.md`](docs/parity.md)). *Remaining for v1:* the full stratified
  adjudication protocol and the packaged case studies.
- **v1.1 (built)** — the operational-network layer (aggregator-masked WCC + Louvain), off-graph.
  WCC reproduces the KG exactly; the >300-BBL Louvain tail (~a few dozen large operators) is
  approximate — GDS Louvain is not byte-reproducible ([`docs/parity.md`](docs/parity.md)).
- **v2 (artifact review)** — DuckDB-native over the public HPD / ACRIS / PLUTO CSVs, so the whole
  thing reproduces with no private database (mirrors `nlr`'s public-CSV roadmap).

## Responsible use

Grounded **entirely in already-public record**; it surfaces and organizes, it does not collect.
Every inferred claim is typed as inferred and carries a standardized caveat — *leads, not
verdicts*. The merge-vs-split (precision-vs-recall) tradeoff is documented, not hidden. See the
paper's dual-use reflection; the dataset-release policy for this repo is deliberately scoped to
match it (a Phase-3 decision — see the roadmap).

## Cite & release

The repo maps to the paper's contributions in [`docs/paper-mapping.md`](docs/paper-mapping.md);
reproducibility is in [`docs/parity.md`](docs/parity.md). To cut a versioned, DOI'd release —
including the **person-free dataset export** (`bor.export`) — follow
[`docs/release.md`](docs/release.md). Citation metadata is in [`CITATION.cff`](CITATION.cff) (the
Zenodo DOI is filled in on the first release).

## License

MIT.
