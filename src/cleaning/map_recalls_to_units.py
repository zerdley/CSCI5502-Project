"""Link FDA drug recall records to the study's drug units.

A recall record names products in free text, much like a shortage record, and only some carry
FDA's structured identifiers. Each record is linked two ways, and either is enough:
    package codes (NDCs) in its text  --NSDE-->  application number  --> unit
    application numbers in openfda                                   --> unit
Most records that link to no unit are compounded, OTC, or unapproved products, which are outside
the study's scope (approved, non-biologic prescription drugs).

Input:  data/raw/drug-enforcement-0001-of-0001.json, data/raw/other-nsde-*.json,
        data/interim/application_units.parquet (from map_episodes_to_units.py)
Output: data/interim/recall_units.parquet  one row per (recall record, unit) link

Usage: uv run python src/cleaning/map_recalls_to_units.py
"""

import json

import pandas as pd

from clean_shortage_episodes import extract_ndcs
from map_episodes_to_units import INTERIM_DATA_DIR, RAW_DATA_DIR, load_nsde

RECALLS_PATH = RAW_DATA_DIR / "drug-enforcement-0001-of-0001.json"
APPLICATION_UNITS_PATH = INTERIM_DATA_DIR / "application_units.parquet"
RECALL_UNITS_PATH = INTERIM_DATA_DIR / "recall_units.parquet"


def load_recalls() -> pd.DataFrame:
    with open(RECALLS_PATH) as file:
        records = pd.DataFrame(json.load(file)["results"])
    return pd.DataFrame({
        "recall_number": records["recall_number"],
        "event_id": records["event_id"],
        "classification": records["classification"],
        "initiated": pd.to_datetime(records["recall_initiation_date"], format="%Y%m%d",
                                    errors="coerce"),
        "reported": pd.to_datetime(records["report_date"], format="%Y%m%d", errors="coerce"),
        "text": records["product_description"].fillna("") + " " + records["code_info"].fillna(""),
        "openfda_applications": records["openfda"].map(
            lambda openfda: (openfda or {}).get("application_number") or []),
    })


def recall_applications(recalls: pd.DataFrame, nsde: pd.DataFrame) -> pd.DataFrame:
    """Every (recall record, application number) the record can be traced to."""
    from_text = [
        (recall_number, ndc["ndc11"])
        for recall_number, text in zip(recalls["recall_number"], recalls["text"])
        for ndc in extract_ndcs(text)
        if ndc["ndc11"]
    ]
    via_ndc = (pd.DataFrame(from_text, columns=["recall_number", "ndc11"])
               .merge(nsde, on="ndc11")[["recall_number", "application"]])
    via_openfda = (recalls[["recall_number", "openfda_applications"]]
                   .explode("openfda_applications").dropna()
                   .rename(columns={"openfda_applications": "application"}))
    return pd.concat([via_ndc, via_openfda]).drop_duplicates()


def print_summary(recalls: pd.DataFrame, recall_units: pd.DataFrame) -> None:
    linked = recalls["recall_number"].isin(recall_units["recall_number"])
    print(f"recall records: {len(recalls):,}  "
          f"linked to a unit: {linked.sum():,} ({linked.mean():.1%})")
    print(f"recall events: {recalls['event_id'].nunique():,}  linked: "
          f"{recalls.loc[linked, 'event_id'].nunique():,}")
    print(f"distinct units with a recall: {recall_units['unit_id'].nunique():,}")
    linked_by_year = recalls.loc[linked, "reported"].dt.year.value_counts().sort_index()
    print(f"linked records by report year: {linked_by_year.loc[2018:].to_dict()}")


def main():
    recalls = load_recalls()
    nsde = load_nsde()
    application_units = pd.read_parquet(APPLICATION_UNITS_PATH)

    recall_units = (recall_applications(recalls, nsde)
                    .merge(application_units, on="application")
                    .drop_duplicates(["recall_number", "unit_id"])
                    .merge(recalls[["recall_number", "event_id", "classification",
                                    "initiated", "reported"]], on="recall_number")
                    .drop(columns="application")
                    .sort_values(["reported", "recall_number", "unit_id"])
                    .reset_index(drop=True))

    recall_units.to_parquet(RECALL_UNITS_PATH, index=False)
    print_summary(recalls, recall_units)
    print(f"\nwrote {RECALL_UNITS_PATH}")


if __name__ == "__main__":
    main()
