"""The release contract (draft v0.1.0): table schemas and controlled vocabularies.

This is the machine-readable form of docs/release-contract.md. A release is a directory of CSVs
plus ``manifest.json``; :mod:`bor.release_validate` checks one against these specs.

Status marks what exists today:

* ``implemented`` — produced by bor now (the W0 lineage tables, :mod:`bor.lineage`).
* ``planned``     — specified here so the KG can review the shape; built by a later work package.

No table holds names. Keys are HPD ids, BBLs, ACRIS document ids, opaque run-local ids and nlr's
content-hash identity ids. ``run_id`` comes from the manifest and is not repeated per row.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = "0.1.0"

LAYERS = ("owner_portfolio", "operational_network")
DECISION_LAYERS = ("identity",) + LAYERS

# Stages that create links (versioned with SCHEMA_VERSION; extend, never repurpose).
STAGES = (
    "identity.splink_base", "identity.splink_feedback", "identity.curated", "identity.registered_llc",
    "deed.held_since", "deed.linked_successor",
    "network.name", "network.address",
)

SUBJECT_TYPES = ("identity", "base_cluster", "cluster", "node", "bbl", "address",
                 "deed_document", "parcel", "component", "group")
OUTCOMES = ("accepted", "rejected", "masked", "excluded", "dropped")

# The four top-level codes of the KG's absence contract, and the detailed codes under them.
TOP_LEVEL_REASONS = ("no_qualifying_linkage", "excluded_by_policy",
                     "below_eligibility_rule", "outside_source_coverage")
REASON_CODES = {
    "no_linkage": ("no_qualifying_linkage", "No accepted edge connected the node to another."),
    "coop_condo_dominated": ("excluded_by_policy",
                             "Group dropped: rental buildings are fewer than half its footprint."),
    "institutional_screen": ("excluded_by_policy", "Deed parties screened as institutional or public."),
    "deed_hub_capped": ("excluded_by_policy", "Node on more multi-parcel deeds than the hub cap."),
    "aggregator_address_masked": ("excluded_by_policy",
                                  "Address shared by more landlords than the aggregator threshold."),
    "curated_exclusion": ("excluded_by_policy", "Curated exclusion (for example a servicer officer)."),
    "deed_parcels_out_of_range": ("below_eligibility_rule", "Deed outside the 2-25 parcel range."),
    "successor_guard_failed": ("below_eligibility_rule", "Linked-successor guard not satisfied."),
    "group_below_min_size": ("below_eligibility_rule", "Component smaller than the minimum group size."),
    "no_registration": ("outside_source_coverage", "No HPD registration for the lot."),
    "no_owner_contact": ("outside_source_coverage",
                         "Registered, but no qualifying person owner contact (no wow_landlords row)."),
    "not_latest_registration": ("outside_source_coverage",
                                "The contact is on a registration the method did not use."),
    "unmatched_node": ("outside_source_coverage", "Node matched no resolved identity."),
}

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
        _c("k", "int")),
        description="HPD contact observations referenced elsewhere. id = registration:contact:k."),
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
        fks=(_fk("identity_id", "identity_clusters"), _fk("observation_id", "observations")),
        description="Which HPD contacts, per BBL, an nlr identity aggregates."),
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

    # ---- decisions and evidence (planned, W2/W3/W6a) --------------------------------------------
    Table("decision_events", "planned", ("decision_id",), (
        _c("decision_id"), _c("layer", enum=DECISION_LAYERS), _c("stage", enum=STAGES),
        _c("subject_type", enum=SUBJECT_TYPES), _c("subject_id"),
        _c("counterpart_type", nullable=True, enum=SUBJECT_TYPES), _c("counterpart_id", nullable=True),
        _c("outcome", enum=OUTCOMES), _c("reason_code", nullable=True, enum=tuple(REASON_CODES)),
        _c("rule"), _c("rule_version"), _c("score", "float", nullable=True),
        _c("threshold", "float", nullable=True), _c("cluster_id", nullable=True),
        _c("detail", nullable=True)),
        description="One row per decision at the grain where a rule ran: accepted links and "
                    "policy outcomes alike. Absence of an event means the rule did not run."),
    Table("decision_support", "planned", ("decision_id", "support_type", "support_id", "role"), (
        _c("decision_id"), _c("support_type", enum=("observation", "bbl", "document")),
        _c("support_id"), _c("role")),
        fks=(_fk("decision_id", "decision_events"),),
        description="The source records a decision rests on."),
    Table("evidence_items", "planned", ("evidence_id",), (
        _c("evidence_id"), _c("stage", enum=("deed.held_since", "deed.linked_successor")),
        _c("document_id"), _c("parcel_count", "int"), _c("rule_version")),
        description="Multi-member assertions: a qualifying deed bundle."),
    Table("evidence_members", "planned", ("evidence_id", "bbl"), (
        _c("evidence_id"), _c("bbl"), _c("node_id", "int"), _c("role", enum=EVIDENCE_ROLES),
        _c("original_document_id"), _c("latest_document_id", nullable=True),
        _c("latest_amount", "float", nullable=True)),
        fks=(_fk("evidence_id", "evidence_items"),),
        description="Per parcel: held under the joint deed, or transferred onward."),

    # ---- groups and paths (planned, W4/W5) ------------------------------------------------------
    Table("groups", "planned", ("layer", "group_id"), (
        _c("layer", enum=LAYERS), _c("group_id"), _c("assertion_key"),
        _c("composition", nullable=True, enum=("identity", "deed_only", "deed_bridged")),
        _c("split", nullable=True, enum=("wcc", "louvain")),
        _c("building_count", "int"), _c("total_building_count", "int")),
        description="Owner Portfolio groups and Operational Network portfolios."),
    Table("group_members", "planned", ("layer", "node_id"), (
        _c("layer", enum=LAYERS), _c("group_id"), _c("node_id", "int"), _c("assertion_key")),
        fks=(_fk(("layer", "group_id"), "groups"),),
        description="Node partition: a node is in at most one group per layer."),
    Table("group_bbls", "planned", ("layer", "bbl"), (
        _c("layer", enum=LAYERS), _c("group_id"), _c("bbl"), _c("rental", "bool")),
        fks=(_fk(("layer", "group_id"), "groups"),),
        description="BBL listing; rental=false marks co-op/condo lots outside the published footprint."),
    Table("group_witness", "planned", ("layer", "group_id", "step"), (
        _c("layer", enum=LAYERS), _c("group_id"), _c("step", "int"), _c("node_a", "int"),
        _c("node_b", "int"), _c("stage", enum=STAGES),
        _c("basis_type", enum=("identity_cluster", "evidence_item", "network_edge")),
        _c("basis_id"), _c("assertion_key")),
        fks=(_fk(("layer", "group_id"), "groups"),),
        description="A representative spanning tree per group (not unique, strongest or shortest)."),

    # ---- operational network (planned, W5) ------------------------------------------------------
    Table("network_edges", "planned", ("edge_id",), (
        _c("edge_id"), _c("component_id"), _c("node_a", "int"), _c("node_b", "int"),
        _c("name_weight", "float"), _c("address_weight", "float"), _c("identity_weight", "float"),
        _c("weight", "float")),
        description="Accepted pre-split graph; weight is the exact Louvain input."),
    Table("network_membership", "planned", ("node_id",), (
        _c("node_id", "int"), _c("component_id"), _c("community_id", nullable=True),
        _c("portfolio_id")),
        description="Node -> original WCC -> final community."),
    Table("split_attempts", "planned", ("split_id",), (
        _c("split_id"), _c("component_id"), _c("parent_community_id", nullable=True),
        _c("level", "int"), _c("outcome", enum=("split", "no_split"))),
        description="Recursive Louvain splits, including unsuccessful ones."),

    # ---- absence, masking, metrics (planned, W6b/W7) --------------------------------------------
    Table("bbl_status", "planned", ("layer", "bbl"), (
        _c("layer", enum=LAYERS), _c("bbl"), _c("status", enum=("in_group", "not_in_group")),
        _c("group_id", nullable=True), _c("reason_code", nullable=True, enum=tuple(REASON_CODES)),
        _c("top_level_reason", nullable=True, enum=TOP_LEVEL_REASONS)),
        description="Summary over the PLUTO-snapshot lot universe; a missing row means nothing."),
    Table("masked_addresses", "planned", ("address_id",), (
        _c("address_id"), _c("method"), _c("normalizer_version"), _c("degree", "int"),
        _c("degree_unit"), _c("threshold", "int"), _c("decision", enum=("masked",))),
        description="Aggregator addresses masked from the network layer."),
    Table("masked_address_nodes", "planned", ("address_id", "node_id"), (
        _c("address_id"), _c("node_id", "int")),
        fks=(_fk("address_id", "masked_addresses"),),
        description="Crosswalk from a masked address to the nodes (and so HPD observations) using it."),
    Table("method_metrics", "planned", ("stage", "metric"), (
        _c("stage", enum=STAGES), _c("metric"), _c("unit"), _c("population", nullable=True),
        _c("n", "int", nullable=True), _c("numerator", "int", nullable=True),
        _c("denominator", "int", nullable=True), _c("precision", "float", nullable=True),
        _c("ci_lower", "float", nullable=True), _c("ci_upper", "float", nullable=True),
        _c("confidence_level", "float", nullable=True), _c("interval_method", nullable=True),
        _c("estimator", nullable=True), _c("strata_ref", nullable=True),
        _c("eval_artifact", nullable=True), _c("eval_version", nullable=True),
        _c("adjudication_status"), _c("provisional", "bool"), _c("note", nullable=True)),
        description="Method precision (not a link probability). Null with a note when unevaluated."),
]

TABLES = {t.name: t for t in _TABLES}

MANIFEST_REQUIRED = (
    "schema_version", "run_id", "snapshot_id", "effective_date", "bor_revision", "nlr_revision",
    "source_tree_hash", "dependency_lock_digest", "threshold", "parameters", "artifacts",
    "stage_vocabulary_version", "reason_vocabulary_version", "output_checksums",
)
