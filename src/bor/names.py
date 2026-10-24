"""The names of a release: who the contacts, identities, nodes and deed parties are, and where the lots are.

A release's evidence is ids: observations, identities, evidence items, documents. This module adds the tables that
say what those ids stand for, as HPD, ACRIS and PLUTO filed them, so a reader can follow the evidence without a
second database. It adds no decision and changes no other table.

Tables (see :mod:`bor.release_schema` for columns):

* ``observation_contacts`` -- the HPD contact behind each observation: role, name, business address.
* ``identity_names``       -- the name and business address that define each nlr identity.
* ``node_names``           -- the landlord name of each node.
* ``deed_documents``, ``deed_parties`` -- the ACRIS documents the release cites, and their grantors and grantees.
* ``lot_addresses``        -- PLUTO's street address of each lot the groups, evidence and decisions name.

**For reading, not joining.** Every key is still an id: observations join to HPD on (registration, contact id),
lots on BBL, documents on ACRIS document id. A name is not a key, and nothing here is evidence that two records are
one person; the evidence is the decisions. Blank and missing values are both null.

**Where a name comes from.** Contacts and parties are copied as filed, without cleaning, so a typo in the source is a
typo here. An observation's contact is found with the same ranking that numbers the observation (``k``,
:data:`bor.lineage.DIGEST_SQL`), so a pair HPD repeats with differing content has one row per variant. A document
that ACRIS lists more than once is described by its most recently recorded row.
"""
from __future__ import annotations

import pandas as pd

from bor import identity_events as ie
from bor.lineage import DIGEST_SQL

_BLANK = {"": None}

_CONTACTS_SQL = f"""
WITH d AS (
  SELECT DISTINCT registrationid, registrationcontactid, type, firstname, middleinitial, lastname, corporationname,
         businesshousenumber, businessstreetname, businessapartment, businesscity, businessstate, businesszip,
         {DIGEST_SQL} AS digest
  FROM hpd_contacts)
SELECT registrationid AS registration_id, registrationcontactid AS registration_contact_id,
       dense_rank() OVER (PARTITION BY registrationid, registrationcontactid ORDER BY digest) - 1 AS k,
       type AS contact_type, firstname AS first_name, middleinitial AS middle_initial, lastname AS last_name,
       corporationname AS corporation_name, businesshousenumber AS business_house,
       businessstreetname AS business_street, businessapartment AS business_apartment,
       businesscity AS business_city, businessstate AS business_state, businesszip AS business_zip
FROM d
"""

_NODE_NAMES_SQL = "SELECT nodeid AS node_id, name FROM landlords_with_connections"

_DOCS_SQL = """
SELECT DISTINCT ON (documentid) documentid AS document_id, doctype AS doc_type, docdate AS doc_date,
       recordedfiled AS recorded_filed, docamount AS doc_amount
FROM real_property_master WHERE documentid = ANY(%s)
ORDER BY documentid, recordedfiled DESC NULLS LAST, modifieddate DESC NULLS LAST
"""

_PARTIES_SQL = """
SELECT DISTINCT documentid AS document_id, partytype, name, address1, address2, city, state, zip
FROM real_property_parties WHERE documentid = ANY(%s) AND partytype IN (1, 2)
"""

_LOTS_SQL = """
SELECT btrim(bbl) AS bbl, borough, address, zipcode AS zip FROM pluto_latest WHERE btrim(bbl) = ANY(%s)
"""

PARTY_TYPES = {1: "grantor", 2: "grantee"}
CONTACT_COLUMNS = ["contact_type", "first_name", "middle_initial", "last_name", "corporation_name", "business_house",
                   "business_street", "business_apartment", "business_city", "business_state", "business_zip"]
ADDRESS_COLUMNS = ["business_house", "business_street", "business_apartment", "business_city", "business_state",
                   "business_zip"]


def _blank_to_null(df: pd.DataFrame, cols) -> pd.DataFrame:
    for c in cols:
        df[c] = df[c].astype("object").where(df[c].notna(), None)
        df[c] = df[c].map(lambda v: None if isinstance(v, str) and not v.strip() else v)
    return df


def observation_contacts(conn, observations: pd.DataFrame) -> pd.DataFrame:
    """One row per observation: the HPD contact it stands for."""
    src = pd.read_sql(_CONTACTS_SQL, conn)
    keys = ["registration_id", "registration_contact_id", "k"]
    m = observations[["observation_id"] + keys].merge(src, on=keys, how="left")
    out = _blank_to_null(m[["observation_id"] + CONTACT_COLUMNS].copy(), CONTACT_COLUMNS)
    return out.sort_values("observation_id").reset_index(drop=True)


def identity_names(res, imap: dict) -> pd.DataFrame:
    """One row per nlr identity, including the ones a curated list removed."""
    frames = [res.identities] + ([res.excluded] if len(res.excluded) else [])
    full = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({"identity_id": full["unique_id"].map(imap).to_numpy(), "name": full["name_full"].to_numpy(),
                        "business_house": full["biz_house"].to_numpy(), "business_street": full["biz_street"].to_numpy(),
                        "business_apartment": full["biz_apt"].to_numpy(), "business_city": full["biz_city"].to_numpy(),
                        "business_state": full["biz_state"].to_numpy(), "business_zip": full["biz_zip"].to_numpy()})
    out = _blank_to_null(out, ADDRESS_COLUMNS)
    return out.drop_duplicates("identity_id").sort_values("identity_id").reset_index(drop=True)


def node_names(conn, node_observations: pd.DataFrame) -> pd.DataFrame:
    src = pd.read_sql(_NODE_NAMES_SQL, conn)
    out = src[src["node_id"].isin(set(node_observations["node_id"]))]
    return out.sort_values("node_id").reset_index(drop=True)


def cited_documents(tables: dict) -> list[str]:
    """Every ACRIS document id a release table names, sorted."""
    ids: set[str] = set()
    ei, em = tables.get("evidence_items"), tables.get("evidence_members")
    if ei is not None:
        ids |= set(ei["document_id"].dropna().astype(str))
    if em is not None:
        ids |= set(em["original_document_id"].dropna().astype(str)) | set(em["latest_document_id"].dropna().astype(str))
    sup = tables.get("decision_support")
    if sup is not None:
        ids |= set(sup.loc[sup["support_type"] == "document", "support_id"].astype(str))
    de = tables.get("decision_events")
    if de is not None:
        for side in ("subject", "counterpart"):
            ids |= set(de.loc[de[f"{side}_type"] == "deed_document", f"{side}_id"].dropna().astype(str))
    return sorted(ids)


def deed_tables(conn, documents: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    docs = pd.read_sql(_DOCS_SQL, conn, params=(documents,))
    for c in ("doc_date", "recorded_filed"):
        docs[c] = pd.to_datetime(docs[c]).dt.strftime("%Y-%m-%d").where(docs[c].notna(), None)
    docs = _blank_to_null(docs, ["doc_type"])
    docs["doc_amount"] = docs["doc_amount"].astype("float64")
    parties = pd.read_sql(_PARTIES_SQL, conn, params=(documents,))
    parties["party_type"] = parties["partytype"].map(PARTY_TYPES)
    parties = parties.drop(columns="partytype")
    parties = _blank_to_null(parties, ["address1", "address2", "city", "state", "zip"])
    parties = parties[parties["name"].notna() & (parties["name"].astype(str).str.strip() != "")]
    parties = parties.sort_values(["document_id", "party_type", "name", "address1"], na_position="first")
    parties["party_index"] = parties.groupby(["document_id", "party_type"]).cumcount()
    parties = parties[["document_id", "party_type", "party_index", "name", "address1", "address2", "city", "state", "zip"]]
    return (docs.sort_values("document_id").reset_index(drop=True),
            parties.sort_values(["document_id", "party_type", "party_index"]).reset_index(drop=True))


def named_lots(tables: dict) -> list[str]:
    """The lots a release's groups, evidence, nodes and decisions name, sorted."""
    lots: set[str] = set()
    for name in ("group_bbls", "evidence_members", "node_observations"):
        if name in tables:
            lots |= set(tables[name]["bbl"].dropna().astype(str))
    de = tables.get("decision_events")
    if de is not None:
        for side in ("subject", "counterpart"):
            m = de[f"{side}_type"].isin(["bbl", "parcel"])
            lots |= set(de.loc[m, f"{side}_id"].dropna().astype(str))
    return sorted(lots)


def lot_addresses(conn, lots: list[str]) -> pd.DataFrame:
    out = pd.read_sql(_LOTS_SQL, conn, params=(lots,))
    out = _blank_to_null(out, ["borough", "address", "zip"])
    return out.sort_values("bbl").reset_index(drop=True)


def name_tables(conn, tables: dict, res) -> tuple[dict, dict]:
    """The six name tables for a release whose other tables are in ``tables``, and a report of coverage.

    ``res`` is the nlr ``Resolution`` the release was built from (its identities carry the names)."""
    imap = ie.identity_ids(res.identities, res.excluded)
    contacts = observation_contacts(conn, tables["observations"])
    idn = identity_names(res, imap)
    nn = node_names(conn, tables["node_observations"])
    documents = cited_documents(tables)
    docs, parties = deed_tables(conn, documents)
    lots = named_lots(tables)
    addr = lot_addresses(conn, lots)
    out = {"observation_contacts": contacts, "identity_names": idn, "node_names": nn, "deed_documents": docs,
           "deed_parties": parties, "lot_addresses": addr}
    report = {
        "observations_without_contact": int(contacts[["contact_type", "first_name", "last_name",
                                                      "corporation_name"]].isna().all(axis=1).sum()),
        "contacts_with_corporation_name": int(contacts["corporation_name"].notna().sum()),
        "identities_named": int(len(idn)),
        "nodes_named": int(len(nn)),
        "documents_cited": len(documents),
        "documents_described": int(len(docs)),
        "deed_parties": int(len(parties)),
        "documents_without_parties": int(len(set(docs["document_id"]) - set(parties["document_id"]))),
        "lots_named": len(lots),
        "lots_with_address": int(addr["address"].notna().sum()),
    }
    return out, report
