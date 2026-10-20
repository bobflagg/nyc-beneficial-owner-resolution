# W0 findings: node, contact and identity mappings

2026-10-20. Read-only spike against the local `justfixwow` dump (`wow_landlords` 171,347 rows, `landlords_with_connections` 118,493 nodes). Nothing was changed in the database. The mapping tables built from these findings are in `bor.lineage` on branch `w0-mapping-tables` (section 6); where its final figures differ from the first measurement, the table-based figure is given and the change is noted. These numbers describe this dump and one Splink run (EM is unseeded, so cluster-level counts will move slightly between runs).

## Summary

1. **Node → registration lineage is exact and needs no change to `build_lwc`.** `wow_landlords` has one row per BBL, and every BBL appears in exactly one node. So `node_observations(node, bbl, registrationid)` is `lwc.bbls` joined to `wow_landlords`.
2. **The source contact is recoverable for 99.63% of nodes' BBLs** using WoW's own selection rule; 642 rows (0.37%) are ambiguous (the first measurement, with a coarser digest, found 629; 250 of those spanned more than one nlr identity, not re-measured).
3. **HPD contact ids are not unique keys.** An observation id needs a disambiguator: the rank `k` of the row's content among the distinct contents sharing a (registration, contact id) pair. The content digest only numbers the rows; it is not exported.
4. **The node → identity join (name, bbl) works for 99.90% of nodes but is not exact:** 4.6% of nodes match several identities, 0.63% straddle several clusters, and 85% of those straddlers are tied and resolved by an arbitrary rule.
5. **nlr and WoW choose different registrations for 1,249 BBLs**, because nlr's tie-break is unspecified.

## 1. Source tables

| Measure | Value |
|---|---|
| `hpd_contacts` rows / distinct `registrationcontactid` | 782,024 / 733,038 |
| (registration, contact id) pairs that repeat | 1,028 (412 identical content, 616 differing content) |
| Contact ids that span registrations | 0 |
| `wow_landlords` rows = distinct BBLs = distinct (bbl, registration) | 171,347 |
| `lwc` nodes = groups on the six-field tuple | 118,493 (match exactly) |
| BBLs appearing in more than one node | 0 (171,347 BBL slots, all distinct) |
| (name, bizaddr) pairs shared by two nodes | 47 pairs, 94 nodes (0.08%) |

**Consequences.**
- The earlier concern that one BBL could sit in several groups does not arise here. Groups partition nodes, and nodes partition BBLs, so each BBL is in at most one group per layer. This is a property of this construction, so the validator should check it rather than assume it.
- (name, bizaddr) is nearly but not exactly a node key; do not use it.
- `landlords_grouped` is a TEMP table and its `row_number()` is unordered, so lineage cannot be rebuilt from the six-field tuple after the fact. It does not need to be: the BBL join is exact.

## 2. How WoW picks the contact (read from `who-owns-what`)

`portfoliograph/sql/landlords_to_standardize.sql`: per BBL, take the registration with the latest `registrationenddate DESC`, then `lastregistrationdate DESC NULLS LAST`. Within it, take one contact, ordered by role (`IndividualOwner`, `HeadOfficer`, `JointOwner`, `CorporateOwner`), then by name. Only contacts with a first or last name qualify. The address is geocoded with Geosupport and cannot be reproduced here.

Applying that rule to the dump:

| | Rows |
|---|---|
| `wow_landlords` rows | 171,347 |
| Matched to an owner-role person contact in the same registration, by name | 171,347 (100%) |
| Selected role: HeadOfficer / IndividualOwner / JointOwner (first measurement) | 106,254 / 46,712 / 18,381 |
| Exactly one candidate contact | 170,705 (99.63%) |
| More than one candidate contact (same role and name, different content) | 642 (0.37%): 627 with two candidates, 15 with three |
| of which candidates carry different nlr identities | 250 in the first measurement (629 rows); not re-measured |

WoW's own tie-break among those 642 is undefined (it orders by role and name only), so the choice is arbitrary in the source. The release should report them as ambiguous and list the candidates, not pick one silently.

## 3. nlr and WoW disagree on the registration for some BBLs

nlr's extraction takes `DISTINCT ON (bbl)` ordered by end date then last-registration date, and nothing else. WoW applies the same two orderings, then breaks ties by contact role and name.

| | BBLs |
|---|---|
| BBLs with a most-recent registration (nlr) | 181,863 |
| BBLs in `wow_landlords` | 171,347 |
| BBLs with a registration but no `wow_landlords` row (no qualifying person contact) | 10,516 |
| BBLs where the two pick different registrations | 1,249 |
| of which have the same `registrationenddate` | 1,235 |

So the mismatch is a tie. nlr's choice among tied registrations is unspecified, so it can vary between runs or plans. I did not check `lastregistrationdate` for those 1,249. A deterministic nlr tie-break would be a small change, but it moves results and needs evaluating; it belongs with W2.

## 4. Node → identity → cluster mapping, as bor does it today

bor joins lwc nodes to nlr identities on (normalized name, bbl) and takes the most common cluster per node. One Splink run, threshold 0.999, feedback on.

| Measure | Value |
|---|---|
| nlr person identities | 145,388 over 171,005 BBLs (all in lwc) |
| lwc BBLs not in the extraction | 342 |
| Nodes matched to at least one identity | 118,380 (99.90%) |
| Nodes unmatched | 113 (67 have a BBL present in the extraction but under another name; 46 have none) |
| Nodes matching exactly one identity | 112,943 |
| Nodes matching 2 or more identities (max 10) | 5,437 (4.6%) |
| Nodes in exactly one cluster | 117,629 |
| Nodes straddling 2 or more clusters | 751 (0.63%) |
| of which the plurality vote is tied | 639 (85%) |
| Identities with no node | 21,405 (14.7%) |
| Identities mapped to 2 or more nodes | 470 |

Reading these:
- A node is a (name, standardized address) group; the several identities it matches are mostly spelling variants of one address, which nlr keeps separate.
- A tied straddler is assigned by `mode().iloc[0]`, which takes the smallest cluster label. That is deterministic for a fixed run but meaningless, and the labels change between fits. This adds nondeterminism beyond Splink's own jitter. The release should flag these nodes and list the alternative clusters.
- 14.7% of identities have no node because lwc keeps one contact per BBL while nlr keeps every qualifying person contact in its registration. Evidence that involves those identities cannot be expressed at node level; the identity-level tables exist for that.

## 5. Decisions this supports

1. **Observation id:** `registrationid:registrationcontactid:k`, where `k` is the 0-based rank of the row's content digest among the distinct contents sharing that (registration, contact id) pair. Identical duplicate rows collapse to one observation; differing rows with the same ids get different `k`; `k` is 0 for the 99.9% of pairs that are unique. The digest (an md5 over role, name and address fields, `bor.lineage.DIGEST_SQL`) is used to number and is not exported, so ids reveal nothing about the contact.
2. **`node_observations`** derives from `lwc.bbls ⋈ wow_landlords` (exact), with a `selected_contact` where WoW's rule gives one candidate and an `ambiguous` flag plus candidate list otherwise.
3. **`identity_node_map`** exports the current (name, bbl) mapping as it is, with `tied` and alternatives for straddlers, and records the tie rule. Replacing the join with an exact mapping from the selected contact would change the clusters and needs its own evaluation; defer it.
4. **Absence reasons from this data:** no `wow_landlords` row for a BBL that has a registration (10,516), no usable owner contact, unmatched node (113), and the registration mismatch (1,249) are all observable without further work.
5. **Validator invariants:** each BBL in exactly one node and at most one group per layer; every node has at least one observation.

## 6. Mapping tables built

`python -m bor.lineage <dir>` writes eight CSVs (observations, node and identity lineage, node-to-cluster) and `mapping_report.json`. On this dump it reproduces the section 4 figures exactly (113 unmatched nodes, 5,437 multi-identity nodes, 751 straddling, 639 of those tied, 21,405 identities with no node) and adds:

| Measure | Value |
|---|---|
| (node, BBL) rows | 171,347, none without a candidate contact |
| (identity, BBL) pairs | 196,710, all traceable to an HPD contact (0 without) |
| BBLs with more than one registration tied for first under nlr's ordering | 2,231 |
| (identity, BBL) pairs on such a tied registration | 2,247 |
| Distinct observations referenced | 202,840 |

The 2,231 tied BBLs are a wider set than the 1,249 where nlr and WoW pick different registrations: ties exist whether or not the two choices happen to agree. The identity-to-contact SQL mirrors nlr's extraction and is temporary; W2 captures the lineage inside nlr.

## Not done

- The tables are not wired into `export()` or the release manifest, and base-cluster membership (before the feedback pass) waits on W2.
- Cluster-level counts come from one run.
- WoW's rule was read from the source in `~/git-alt/who-owns-what`; I did not check that the dump was built from that exact revision.
- The measurement script is in the session scratchpad, not the repo.
