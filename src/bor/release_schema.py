"""The release contract (v0.1.0): table schemas and controlled vocabularies.

This is the machine-readable form of docs/release-contract.md. A release is a directory of CSVs
plus ``manifest.json``; :mod:`bor.release_validate` checks one against these specs.

Status marks what exists today:

* ``implemented`` — produced by bor now. As of W7 every table is.
* ``planned``     — specified here so the KG can review the shape; built by a later work package.

No table holds names. Keys are HPD ids, BBLs, ACRIS document ids, opaque run-local ids and nlr's
content-hash identity ids. ``run_id`` comes from the manifest and is not repeated per row.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = "0.1.0"

LAYERS = ("owner_portfolio", "operational_network")
DECISION_LAYERS = ("identity",) + LAYERS

# Stages (versioned with SCHEMA_VERSION; extend, never repurpose). The link-creating stages, and
# the group-level policy stages that have no link of their own.
STAGES = (
    "identity.splink_base", "identity.splink_feedback", "identity.curated", "identity.registered_llc",
    "deed.held_since", "deed.linked_successor", "deed.group",
    "network.identity", "network.name", "network.address",
    "owner_portfolio.group_size", "owner_portfolio.footprint",
)

# The rule that produced a decision (controlled; a consumer renders explanations from it).
# rule_version is a free string naming the version of that rule's definition.
RULES = (
    "splink_model", "first_name_veto", "common_name_veto", "shared_company_feedback",
    "shared_company_guard", "curated_owner_list", "registered_llc_owner_match",
    "deed_latest_rule", "deed_successor_guard", "deed_hub_cap", "deed_size_range",
    "institutional_screen", "coop_condo_contact_rule", "coop_condo_deed_rule",
    "aggregator_address_mask", "splink_address_evidence_mask", "group_min_size",
    "group_footprint_rule", "name_edge", "address_edge",
)

SUBJECT_TYPES = ("identity", "base_cluster", "cluster", "node", "bbl", "address",
                 "deed_document", "parcel", "component", "group")
OUTCOMES = ("accepted", "rejected", "masked", "excluded", "dropped")

# The top-level reasons a lot is absent, in precedence order: when several apply, the earliest
# stage that removed the lot is the primary reason. The KG's contract names the first four plus
# outside_method_input (KG design note 0007, accepted).
TOP_LEVEL_REASONS = ("outside_source_coverage", "outside_method_input", "excluded_by_policy",
                     "below_eligibility_rule", "no_qualifying_linkage")
PRECEDENCE = TOP_LEVEL_REASONS

REASON_CODES = {
    # outside source coverage: HPD holds no record
    "no_registration": ("outside_source_coverage", "No HPD registration for the lot."),
    # outside method input: the source holds the record but the method did not use it
    "no_owner_contact": ("outside_method_input",
                         "Registered, but no qualifying person owner contact (no wow_landlords row)."),
    "not_latest_registration": ("outside_method_input",
                                "The contact is on a registration the method did not use."),
    "unmatched_node": ("outside_method_input", "Node matched no resolved identity."),
    # excluded by policy
    "coop_condo_excluded": ("excluded_by_policy",
                            "Building is a co-op or condo, left out of a surviving group's rental footprint."),
    "coop_condo_dominated": ("excluded_by_policy",
                             "Dropped: co-op/condo lots are the majority (of a group's footprint, or of a deed's parcels)."),
    "institutional_screen": ("excluded_by_policy", "Deed parties screened as institutional or public."),
    "deed_hub_capped": ("excluded_by_policy", "Node on more multi-parcel deeds than the hub cap."),
    "aggregator_address_masked": ("excluded_by_policy",
                                  "Address-edge mask: address shared by more landlords than the threshold."),
    "address_evidence_masked": ("excluded_by_policy",
                                "Splink address-evidence mask: address shared by more landlords than the threshold."),
    "curated_exclusion": ("excluded_by_policy", "Curated exclusion (for example a servicer officer)."),
    # below an eligibility rule
    "deed_parcels_out_of_range": ("below_eligibility_rule", "Deed outside the 2-25 parcel range."),
    "deed_not_latest": ("below_eligibility_rule",
                        "Staleness guard: the joint deed is no longer the parcel's latest deed."),
    "successor_not_shell": ("below_eligibility_rule",
                            "Linked-successor guard: the successor holds more buildings than the shell cap."),
    "successor_transfer_not_nominal": ("below_eligibility_rule",
                                       "Linked-successor guard: the onward transfer is not at nominal consideration."),
    "first_name_veto": ("below_eligibility_rule", "Pair blocked by the first-name veto."),
    "common_name_veto": ("below_eligibility_rule", "Pair blocked by the common-name veto."),
    "shared_company_name_not_rare": ("below_eligibility_rule",
                                     "Shared-company pass: the name is not rare enough."),
    "shared_company_first_name_conflict": ("below_eligibility_rule",
                                           "Shared-company pass: first names are not compatible."),
    "shared_company_degree_cap": ("below_eligibility_rule",
                                  "Shared-company pass: too many contacts under the company."),
    "shared_company_degree_unknown": ("below_eligibility_rule",
                                      "Shared-company pass: the company has no degree record, so the pass leaves it out."),
    "group_below_min_size": ("below_eligibility_rule", "Component smaller than the minimum group size."),
    # no qualifying linkage
    "no_linkage": ("no_qualifying_linkage", "No accepted edge connected the node to another."),
    "pair_below_threshold": ("no_qualifying_linkage",
                             "A scored pair fell below the threshold (recorded only if a release opts in)."),
}

# method_metrics: a link precision belongs to a stage; a split precision (pairs the method keeps apart,
# judged to really be different owners) belongs to the sampled population, which no single stage owns.
METRIC_SCOPES = ("method.aggregator_splits", "method.hard_negatives")
METRIC_NAMES = ("precision_strict", "precision_inclusive", "split_precision")
# Who produced the gold the estimate rests on. `human_llm_provisional`: one human, an LLM second reader and
# LLM-resolved disagreements. `blind_human` is reserved for a gold with a second blind human and human arbitration.
ADJUDICATION_STATUSES = ("none", "synthetic", "human_llm_provisional", "blind_human")
# The stages that create a link, each of which a release's witness paths can cite: every one needs a metric row.
LINK_STAGES = ("identity.splink_base", "identity.splink_feedback", "identity.curated", "identity.registered_llc",
               "deed.held_since", "deed.linked_successor", "network.identity", "network.name", "network.address")

class ReleaseInputError(ValueError):
    """Something the caller supplied cannot be built into a release: a snapshot id of the wrong form or date,
    an evaluation without its gold status or counts. The command line reports it in one line; any other
    exception is a bug and keeps its traceback."""


EVIDENCE_ROLES = ("held_under_joint_deed", "transferred_onward")
ARTIFACT_KINDS = ("complete", "representative")


@dataclass(frozen=True)
class Column:
    name: str
    type: str                      # str | int | float | bool
    nullable: bool = False
    enum: tuple | None = None
    optional: bool = False         # column may be absent (a later work package adds it)


@dataclass(frozen=True)
class ForeignKey:
    cols: tuple[str, ...]
    table: str
    ref_cols: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    name: str
    status: str                    # implemented | planned
    key: tuple[str, ...]
    columns: tuple[Column, ...]
    fks: tuple[ForeignKey, ...] = ()
    description: str = ""


def _c(name, type="str", nullable=False, enum=None, optional=False):
    return Column(name, type, nullable, enum, optional)


def _fk(cols, table, ref_cols=None):
    cols = (cols,) if isinstance(cols, str) else tuple(cols)
    ref = cols if ref_cols is None else ((ref_cols,) if isinstance(ref_cols, str) else tuple(ref_cols))
    return ForeignKey(cols, table, ref)


_TABLES = [
    # ---- lineage: nodes and identities back to HPD records (implemented, bor.lineage) -----------
    Table("observations", "implemented", ("observation_id",), (
        _c("observation_id"), _c("registration_id", "int"), _c("registration_contact_id", "int"),
        _c("k", "int"), _c("pair_variants", "int")),
        description="HPD contact observations referenced elsewhere. id = registration:contact:k. "
                    "The join key is (registration_id, registration_contact_id); where pair_variants > 1 "
                    "the pair is ambiguous and evidence attaches to every row of the pair."),
    Table("node_observations", "implemented", ("node_id", "bbl"), (
        _c("node_id", "int"), _c("bbl"), _c("registration_id", "int"), _c("n_candidates", "int"),
        _c("selected_observation_id", nullable=True), _c("ambiguous", "bool")),
        fks=(_fk("selected_observation_id", "observations", "observation_id"),),
        description="The registration and contact WoW used for each (node, BBL)."),
    Table("node_observation_alternatives", "implemented", ("node_id", "bbl", "observation_id"), (
        _c("node_id", "int"), _c("bbl"), _c("observation_id")),
        fks=(_fk(("node_id", "bbl"), "node_observations"), _fk("observation_id", "observations")),
        description="The tied candidate contacts of ambiguous (node, BBL) rows."),
    Table("identity_clusters", "implemented", ("identity_id",), (
        _c("identity_id"), _c("cluster_id"), _c("base_cluster_id", nullable=True, optional=True)),
        description="nlr identity -> final cluster (and, from W2, its pre-feedback base cluster)."),
    Table("identity_observations", "implemented", ("identity_id", "bbl", "observation_id"), (
        _c("identity_id"), _c("bbl"), _c("observation_id"), _c("tied_registration", "bool")),
        fks=(_fk("observation_id", "observations"),),
        description="Which HPD contacts, per BBL, an identity aggregates: the contacts nlr used. "
                    "Also covers identities a curated list removed, which are in no cluster."),
    Table("node_identity_matches", "implemented", ("node_id", "identity_id", "bbl"), (
        _c("node_id", "int"), _c("identity_id"), _c("bbl")),
        fks=(_fk(("node_id", "bbl"), "node_observations"), _fk("identity_id", "identity_clusters")),
        description="The (name, bbl) matches that attach identities to nodes."),
    Table("node_cluster", "implemented", ("node_id",), (
        _c("node_id", "int"), _c("cluster_id"), _c("n_clusters", "int"), _c("tied", "bool")),
        fks=(_fk("cluster_id", "identity_clusters"),),
        description="The cluster each matched node is assigned. tied = plurality vote tied."),
    Table("node_cluster_alternatives", "implemented", ("node_id", "cluster_id"), (
        _c("node_id", "int"), _c("cluster_id"), _c("votes", "int"), _c("selected", "bool")),
        fks=(_fk("node_id", "node_cluster"), _fk("cluster_id", "identity_clusters")),
        description="Every cluster a straddling node matched, with votes and the selected one."),

    # ---- decisions and evidence (implemented) --------------------------------------------
    Table("decision_events", "implemented", ("decision_id",), (
        _c("decision_id"), _c("layer", enum=DECISION_LAYERS), _c("stage", enum=STAGES),
        _c("subject_type", enum=SUBJECT_TYPES), _c("subject_id"),
        _c("counterpart_type", nullable=True, enum=SUBJECT_TYPES), _c("counterpart_id", nullable=True),
        _c("outcome", enum=OUTCOMES), _c("reason_code", nullable=True, enum=tuple(REASON_CODES)),
        _c("rule", enum=RULES), _c("rule_version"), _c("score", "float", nullable=True),
        _c("threshold", "float", nullable=True), _c("cluster_id", nullable=True),
        _c("detail", nullable=True)),
        description="One row per decision at the grain where a rule ran: accepted links and "
                    "policy outcomes alike. Absence of an event means the rule did not run. "
                    "Identity, deed, group and network decisions are all recorded here."),
    Table("decision_support", "implemented", ("decision_id", "support_type", "support_id", "role"), (
        _c("decision_id"), _c("support_type", enum=("observation", "bbl", "document")),
        _c("support_id"), _c("role")),
        fks=(_fk("decision_id", "decision_events"),),
        description="The source records a decision rests on."),
    Table("evidence_items", "implemented", ("evidence_id",), (
        _c("evidence_id"), _c("stage", enum=("deed.held_since", "deed.linked_successor")),
        _c("document_id"), _c("parcel_count", "int"), _c("rule_version")),
        description="Multi-member assertions: a qualifying deed bundle."),
    Table("evidence_members", "implemented", ("evidence_id", "bbl"), (
        _c("evidence_id"), _c("bbl"), _c("node_id", "int"), _c("role", enum=EVIDENCE_ROLES),
        _c("original_document_id"), _c("latest_document_id", nullable=True),
        _c("latest_amount", "float", nullable=True),
        _c("excluded_reason", nullable=True, enum=tuple(REASON_CODES))),
        fks=(_fk("evidence_id", "evidence_items"),),
        description="Per parcel: held under the joint deed, or transferred onward. excluded_reason "
                    "marks a member whose node was left out of the deed's clique (deed_hub_capped)."),

    # ---- groups and paths (implemented) ------------------------------------------------------
    Table("link_sets", "implemented", ("set_id",), (
        _c("set_id"), _c("stage", enum=("identity.curated", "identity.registered_llc")),
        _c("rule", enum=RULES), _c("rule_version"), _c("size", "int")),
        description="Sets of nodes tied by a curated owner (CG...) or by one DOF owner-of-record entity "
                    "(LG...). Ids are opaque; the owner label and the entity name are not exported."),
    Table("link_set_members", "implemented", ("set_id", "node_id", "source_bbl"), (
        _c("set_id"), _c("node_id", "int"), _c("source_bbl", nullable=True)),
        fks=(_fk("set_id", "link_sets"),),
        description="The nodes of a link set. For a registered-LLC set, source_bbl is the PLUTO lot the "
                    "entity owns that puts the node in the set; null for a curated owner."),
    Table("groups", "implemented", ("layer", "group_id"), (
        _c("layer", enum=LAYERS), _c("group_id"), _c("assertion_key"),
        _c("composition", nullable=True, enum=("identity", "deed_only", "deed_bridged")),
        _c("split", nullable=True, enum=("wcc", "louvain")),
        _c("lot_count", "int"), _c("total_lot_count", "int"), _c("witness_pieces", "int")),
        description="Owner Portfolios (OP-<n>) and Operational Networks (ON-<n>), n = the "
                    "minimum node id (run-local). witness_pieces is the number of connected pieces the "
                    "group's path leaves: 1 (a spanning tree) unless its own edges cannot connect it. "
                    "Counting unit: tax lots (BBLs), not buildings. lot_count is the rental footprint, total_lot_count includes "
                    "co-op/condo lots."),
    Table("group_members", "implemented", ("layer", "node_id"), (
        _c("layer", enum=LAYERS), _c("group_id"), _c("node_id", "int"), _c("assertion_key")),
        fks=(_fk(("layer", "group_id"), "groups"),),
        description="Node partition: a node is in at most one group per layer."),
    Table("group_bbls", "implemented", ("layer", "bbl"), (
        _c("layer", enum=LAYERS), _c("group_id"), _c("bbl"), _c("rental", "bool")),
        fks=(_fk(("layer", "group_id"), "groups"),),
        description="BBL listing; rental=false marks co-op/condo lots outside the published footprint."),
    Table("group_witness", "implemented", ("layer", "group_id", "step"), (
        _c("layer", enum=LAYERS), _c("group_id"), _c("step", "int"), _c("node_a", "int"),
        _c("node_b", "int"), _c("stage", enum=STAGES),
        _c("basis_type", enum=("identity_cluster", "evidence_item", "link_set", "network_edge")),
        _c("basis_id"), _c("assertion_key")),
        fks=(_fk(("layer", "group_id"), "groups"),),
        description="A representative spanning tree per group (not unique, strongest or shortest). "
                    "Each step cites the set that joined its two nodes (basis)."),

    # ---- operational network (implemented) ------------------------------------------------------
    Table("network_edges", "implemented", ("edge_id",), (
        _c("edge_id"), _c("component_id"), _c("node_a", "int"), _c("node_b", "int"),
        _c("name_weight", "float"), _c("address_weight", "float"), _c("identity_weight", "float"),
        _c("weight", "float"), _c("crosses_networks", "bool")),
        description="The complete accepted graph before any split, one row per node pair (node_a < "
                    "node_b). weight is the exact input to Louvain: the sum of every contribution, "
                    "which is name_weight + address_weight + identity_weight. crosses_networks marks "
                    "an edge whose ends ended up in different Operational Networks, i.e. the boundary."),
    Table("network_membership", "implemented", ("node_id",), (
        _c("node_id", "int"), _c("component_id"), _c("community_id", nullable=True),
        _c("operational_network_id")),
        description="Node -> original weakly connected component -> final Operational Network. "
                    "community_id is the final Louvain community when the component was split, else null."),
    Table("split_attempts", "implemented", ("split_id",), (
        _c("split_id"), _c("component_id"), _c("parent_community_id", nullable=True),
        _c("level", "int"), _c("outcome", enum=("split", "no_split")), _c("communities", "int")),
        description="Every Louvain call on a component or community over the size cap, including "
                    "those that found no useful split (the piece is then kept whole)."),

    # ---- absence, masking, metrics (implemented) --------------------------------------------
    Table("bbl_status", "implemented", ("layer", "bbl"), (
        _c("layer", enum=LAYERS), _c("bbl"),
        _c("status", enum=("in_group", "not_in_group", "excluded_from_footprint")),
        _c("group_id", nullable=True), _c("reason_code", nullable=True, enum=tuple(REASON_CODES)),
        _c("top_level_reason", nullable=True, enum=TOP_LEVEL_REASONS)),
        description="Summary over the PLUTO-snapshot lot universe; a missing row means nothing. "
                    "excluded_from_footprint: in a published group but left out of its rental footprint "
                    "(group_bbls.rental = false); it keeps its group_id and carries a reason. "
                    "reason_code is the primary reason, by PRECEDENCE."),
    Table("masked_addresses", "implemented", ("address_id",), (
        _c("address_id"), _c("method"), _c("normalizer_version"), _c("degree", "int"),
        _c("degree_unit"), _c("threshold", "int"), _c("decision", enum=("masked",))),
        description="Aggregator addresses masked from the network layer."),
    Table("masked_address_nodes", "implemented", ("address_id", "node_id"), (
        _c("address_id"), _c("node_id", "int")),
        fks=(_fk("address_id", "masked_addresses"),),
        description="Crosswalk from a masked address to the nodes (and so HPD observations) using it."),
    Table("method_metrics", "implemented", ("stage", "metric"), (
        _c("stage", enum=STAGES + METRIC_SCOPES), _c("metric", enum=METRIC_NAMES), _c("unit"), _c("population", nullable=True),
        _c("n", "int", nullable=True), _c("numerator", "int", nullable=True),
        _c("denominator", "int", nullable=True), _c("precision", "float", nullable=True),
        _c("ci_lower", "float", nullable=True), _c("ci_upper", "float", nullable=True),
        _c("confidence_level", "float", nullable=True), _c("interval_method", nullable=True),
        _c("estimator", nullable=True), _c("strata_ref", nullable=True),
        _c("eval_artifact", nullable=True), _c("eval_version", nullable=True),
        _c("adjudication_status", enum=ADJUDICATION_STATUSES), _c("provisional", "bool"), _c("note", nullable=True)),
        description="Method precision (not a link probability). Null with a note when unevaluated."),
]

TABLES = {t.name: t for t in _TABLES}

MANIFEST_REQUIRED = (
    "schema_version", "run_id", "snapshot_id", "snapshot_date", "snapshot_date_basis", "effective_date",
    "bor_revision", "nlr_revision", "source_tree_hash", "dependency_lock_digest", "threshold", "parameters",
    "artifacts", "stage_vocabulary_version", "reason_vocabulary_version", "output_checksums", "source_tables",
    "deed_selection_rule", "normalizer_versions",
)

# The snapshot id (KG design note 0008): one source dump, `<source>-<YYYY-MM-DD>`, with `-rN` when the same date is
# extracted again with different content. The date is the data's: the earlier of the newest values of the columns in
# SNAPSHOT_DATE_COLUMNS, so the id means "complete through" it. PLUTO is part of the dump and has no id of its own.
SNAPSHOT_ID_RE = r"^[a-z][a-z0-9]*-(\d{4}-\d{2}-\d{2})(-r\d+)?$"
SNAPSHOT_ID_MAX = 40
SNAPSHOT_DATE_COLUMNS = (("real_property_master", "recordedfiled"), ("hpd_registrations", "lastregistrationdate"))

# Each entry of manifest["source_tables"] (table name -> object). The KG compares these with its
# own load and refuses a mismatch. snapshot_id takes the form the KG defines (KG tech-stack, open
# decision); the manifest repeats it exactly. The fingerprint method is fixed in W1.
SOURCE_TABLE_FIELDS = ("row_count", "fingerprint", "fingerprint_method")
DEED_RULE_FIELDS = ("rule", "version")
# `manifest.excerpt`, present only on an excerpt of a larger release (bor.excerpt)
EXCERPT_FIELDS = ("of_run_id", "seed_groups", "rule", "tables_omitted", "events_omitted", "evidence_omitted")
