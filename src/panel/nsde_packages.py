"""NSDE packages linked to drug units, with the dates each package was on the market.

Shared by build_unit_year_panel.py (which units are on the market each year) and add_features.py
(supply and exit features), so both read market presence the same way.
"""

import json
from pathlib import Path

import pandas as pd

NSDE_PATHS = sorted((Path(__file__).resolve().parents[2] / "data" / "raw")
                    .glob("other-nsde-*-of-*.json"))


def parse_nsde_date(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, format="%Y%m%d", errors="coerce")


def load_unit_packages(application_units: pd.DataFrame) -> pd.DataFrame:
    """Every NSDE package linked to a unit: ndc11, application, labeler, unit_id, start, end.

    A missing end means the package is still marketed.
    """
    rows = []
    for path in NSDE_PATHS:
        with open(path) as file:
            rows.extend(json.load(file)["results"])
    packages = pd.DataFrame(rows).dropna(subset=["package_ndc11"]).drop_duplicates("package_ndc11")

    marketing_end = parse_nsde_date(packages["marketing_end_date"])
    inactivated = parse_nsde_date(packages["inactivation_date"])
    reactivated = parse_nsde_date(packages["reactivation_date"])
    # Many packages leave the market without a marketing end date ever being recorded; NSDE only
    # marks them inactivated. NSDE keeps just a package's latest inactivation, so one reactivated
    # since then is treated as on the market throughout (its gap off the market is not visible).
    # Inactivation dates look administrative: most fall on a few days a year, largely late January,
    # consistent with FDA inactivating listings not renewed the year before. They likely place an
    # exit near when FDA removed the listing, not when the product left the market.
    still_inactive = inactivated.notna() & (reactivated.isna() | (reactivated < inactivated))
    end = marketing_end.where(
        ~still_inactive, pd.concat([marketing_end, inactivated], axis=1).min(axis=1))

    packages = pd.DataFrame({
        "ndc11": packages["package_ndc11"],
        "application": packages["application_number_or_citation"],
        "start": parse_nsde_date(packages["marketing_start_date"]),
        "end": end,
    })
    packages["labeler"] = packages["ndc11"].str[:5]
    return packages.merge(application_units, on="application")


def is_active_on(packages: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    return (packages["start"] <= date) & (packages["end"].isna() | (packages["end"] >= date))
