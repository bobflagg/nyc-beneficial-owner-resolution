# NYC Beneficial Owner Resolution

Knowing who actually *owns* a building — the person or group that profits and answers for it,
not the single-purpose LLC on the deed or the managing agent on the registration — is what lets
housing accountability reach the right party. But ownership in New York is deliberately obscured:
buildings are deeded to their own LLCs, blocks are re-deeded into `$0` shells, and registrations
run through agents and law offices shared by dozens of unrelated owners. Guess wrong one way and a
real owner hides behind the shells; guess wrong the other and you over-attribute someone else's
buildings to an agent or a namesake. This project resolves beneficial ownership from the public
record and **says how sure it is** — every link typed as *directly-sourced* or *inferred*, a lead
to verify, never a legal verdict.

## Who Owns What

JustFix's **[Who Owns What](https://github.com/JustFixNYC/who-owns-what)** (WoW) is the gold
standard for grouping NYC landlords: it links registration contacts by shared names and business
addresses, then clusters that graph (WCC + Louvain) into portfolios — the backbone of countless
tenant tools and news investigations. Read for what it is, a WoW portfolio is an **operational
network**: the buildings run through the same people, offices, and managing hands. That is
exactly the right answer for an organizer finding neighbors under the same landlord operation.

Two things can go wrong around it, and they differ in kind:

- **Noise in the signal (false splits).** One operation recorded under typo'd addresses and
  variant names fragments into several portfolios. The question is still *who operates this?* —
  the measurement is just noisy. This is fixed by the sibling project
  **[NYC Landlord Resolution](https://github.com/bobflagg/nyc-landlord-resolution)** (`nlr`),
  which reunites the fragments with probabilistic record linkage and feeds WoW a single
  high-confidence `CONNECTED_BY_SPLINK` edge — merging only, never splitting.
- **A signal asked a second question.** A shared business address is strong evidence that two
  buildings are *operated* together and weak evidence that they are *owned* by the same party:
  one registered agent, management company, or law firm serves dozens of unrelated owners. The
  portfolio isn't wrong — but read as an ownership claim it attributes buildings to a party who
  doesn't own them, a wrongful-targeting and defamation risk.

**Don't ask one signal two questions.** That is this project's design rule. Each signal answers
one question and no other: a shared office or managing agent speaks to *operation*; a shared
conveyance deed or a resolved owner identity speaks to *ownership*; a disclosed agent speaks to
*management*. BOR keeps these as separate, separately typed layers — it preserves WoW's
operational network and adds the ownership layer alongside it, resolved from ownership signals
only.

## Ownership gets its own question

Ownership is resolved from **ownership signals only**: who a deed conveys to, and which
registration identities are genuinely the same person. A shared business address — the signal
WoW's portfolios are built on — says two buildings are *operated* together; it says little about
who *owns* them, so it never joins an owner group. Two buildings join the same **beneficial owner
group** when a shared conveyance deed (`CONNECTED_BY_DEED`) or a resolved shared owner identity
(`CONNECTED_BY_SPLINK`, from `nlr`) ties them — a registered-agent office they happen to share
never does. WoW's operational network isn't discarded: it stays as its own layer (below), where
a shared office is exactly the right evidence.

The signature move is a **deed veil-pierce**: a *name-free* link from a shared ACRIS deed. Its
**linked-successor guard** reaches the hardest case — owners who buy a block together and then
re-deed each building into its own `$0` single-purpose shell, a common-control structure no name-
or address-based method can see. Precision hygiene keeps management artifacts out:
**aggregator-address masking** (a hub office used by many unrelated owners is never an ownership
signal) and **co-op/condo exclusion** (those buildings are owned by their shareholders, not a
landlord).

Ownership is only one of several claims, and the project keeps them **separate and separately
typed** — each as *directly-sourced* or *inferred* — so a reader always knows the evidentiary
weight behind a link:

| Layer | Question | Signals | Status |
|---|---|---|---|
| **Beneficial owner group** | Who *owns* it? | `CONNECTED_BY_SPLINK` ∪ `CONNECTED_BY_DEED` | **v1** |
| **Deed veil-pierce** | co-owned by conveyance? | ACRIS multi-parcel deed + linked-successor guard | **v1** |
| **Operational network** | What does it *operate through*? | name / address / splink, aggregator-masked (WCC + Louvain) | **v1.1** |
| **Management** | Who *runs* it? | `MANAGED_BY` (disclosed agent) | in WatchlineNYC |

Every derived link reads as an investigative **lead to verify, not a legal determination**, and
the merge-vs-split (precision-vs-recall) tradeoff is documented, not hidden.

## How it measures up

Two complementary evaluations, both paired against WoW's own output — the `wow.wow_portfolios`
table in the public `justfixwow` Postgres — so the baseline is literally what WoW produces, not a
reimplementation of its clustering.

First, a **divergence** measure: where, and in which direction, the owner-group partition differs
from WoW's portfolios. Some divergence is expected by design — portfolios answer *who operates*,
owner groups answer *who owns*. This is divergence, *not* accuracy — adjudication decides who is
right — but it sizes the difference:

```bash
uv run python -m bor.eval.divergence
# → 760 owners cross WoW portfolios; 616 WoW portfolios span >1 owner group
```

Accuracy is settled by **blind human adjudication** on a *preregistered, stratified* sample of 512
candidate pairs, each labeled SAME / DIFFERENT / INDETERMINATE against the primary record before
being unblinded and scored against WoW's decision. Pairs are labeled for *beneficial ownership*,
so the comparison reads a WoW portfolio as an ownership claim — a question it was not built to
answer, which is exactly the cost of asking one signal two questions. On the **259 pairs where
the two disagree about ownership, the ownership layer is right 236 times and WoW's portfolio,
read as ownership, 23** (McNemar p < 0.001; inter-annotator κ = 0.89).

![Head-to-head on the 259 pairs where the ownership layer and Who Owns What disagree about
ownership: the ownership layer is right 236 times and a WoW portfolio, read as an ownership claim,
23 — McNemar p < 0.001, annotator κ = 0.89, over 512 adjudicated pairs.](docs/measured-vs-wow.svg)

Per-stratum precision:

| Stratum | What it tests | Precision |
|---|---|---|
| **S1a — deed-held** | a shared conveyance deed → SAME owner | **97%** |
| **S1b — deed-linked successor** | the re-deed-into-`$0`-shells chain → SAME owner | **71%** |
| **S2 — model / splink** | a resolved shared identity → SAME owner | **97%** |
| **S3 — aggregator** | distinct owners at a shared hub → correctly kept SEPARATE | **98%** |
| **S4 — hard-negative surname** | same-surname but no ownership link → correctly kept SEPARATE | **89%** |

S1/S2 measure *merge* precision (when it joins, is it right?); S3/S4 measure *split* precision
(when it keeps owners apart, is it right?). The **deed-linked-successor** stratum (S1b, 71%) is the
honest weak spot — the hardest veil-pierce, and the one most in need of a stronger guard.

A library-level **WoW gate** answers the same question for a single group — does WoW genuinely
split its members into ≥2 non-aggregator portfolios (a real veil-pierce), or do the members merely
sit in an aggregator-hub portfolio — an operational network spanning many owners, not a
veil-pierce?

```python
from bor.eval.gate import gate_bbls
result = gate_bbls(conn, member_bbls)       # GateResult(passed, reasons, ...)
```

The full adjudication protocol (the INDETERMINATE class, a circularity control, and a data-vintage
control) and the packaged case studies (Croman, Escobar, Miller, Levitov, AXL, Citadel) ship with
the release — see the roadmap. Everything above is computed **off-graph from Postgres** and
reproduces the live knowledge graph's partition (owner groups 100% of nodes; operational network
99.9%, the tail being Louvain — [`docs/parity.md`](docs/parity.md)).

## Install

```bash
uv sync                     # installs nlr from its pinned git tag (public; HTTPS, no creds)
cp .env.example .env        # set PG* for the NYC public-record Postgres (see docs/data.md)
uv run python -m bor.build_lwc   # build landlords_with_connections from wow_landlords (~1-2 min)
```

BOR depends only on the *data* — a Postgres seeded from JustFix's public `justfixwow` dump — not on
any WatchlineNYC pipeline; it builds the one derived table (`landlords_with_connections`) itself.
See [`docs/data.md`](docs/data.md) for the required tables and where they come from.

## Use it

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

## How it relates to the other repos

```
nlr  (record linkage / false-split resolution)         ── standalone, gold-validated
  └── nyc-beneficial-owner-resolution  (this repo)      ── + deed, owner groups, benchmark  [KG-free]
        └── WatchlineNYC  (the deployed product)        ── materializes the export into Neo4j; UI + agent
```

BOR is **KG-free** — it runs over Postgres (v1) and never requires Neo4j. WatchlineNYC consumes
BOR's export and is where the Neo4j graph, the conversational agent, and the public site live.

## Responsible use

Grounded **entirely in already-public record** — it surfaces and organizes, it does not collect.
Every inferred claim is typed as inferred and carries a standardized caveat — *leads, not
verdicts*. The merge-vs-split (precision-vs-recall) tradeoff is documented, not hidden. The dataset-release policy for this repo is deliberately scoped to
match this stance (a Phase-3 decision — see the roadmap).

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

## Cite & release

Reproducibility is documented in [`docs/parity.md`](docs/parity.md). To cut a versioned, DOI'd release —
including the **person-free dataset export** (`bor.export`) — follow
[`docs/release.md`](docs/release.md). Citation metadata is in [`CITATION.cff`](CITATION.cff) (the
Zenodo DOI is filled in on the first release).

## License

MIT.
