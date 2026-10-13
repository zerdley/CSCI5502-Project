"""Add predictor columns to the unit x year panel.

Timing rule: for a row (unit, year t), every feature is measured as of December 31 of year t-1,
or over the calendar year t-1. Nothing from year t itself is used, so a model sees only what was
knowable before the year it predicts.

Features
    Supply structure (NSDE marketing and inactivation dates, via nsde_packages.py)
        active_packages               packages on the market at the end of t-1
        active_applications           distinct FDA approvals with an active package
        active_generic_applications   of those, generic approvals (ANDAs)
        active_labelers               distinct labeler codes (first 5 NDC digits) with an active
                                      package; repackagers have their own codes, so this counts
                                      distribution channels, not independent manufacturers
    Manufacturer exits (research question 3)
        package_exits_prior_year            packages whose marketing ended during t-1
        application_exits_prior_year        approvals with an active package at the end of t-2
                                            and none at the end of t-1
        discontinuation_notices_prior_year  episodes first listed as "To Be Discontinued" in t-1
    Product and market (Orange Book)
        route_group                   injectable, oral, ... (categorical)
        years_since_first_approval    from the unit's earliest approval to the end of t-1
        cumulative_applicants         distinct companies approved by the end of t-1; measures how
                                      commoditized a drug is, not supply redundancy
    History and quality
        had_prior_shortage            a shortage spell for the unit ended before year t
        recalls_prior_year            recall records for the unit reported during t-1
        serious_recalls_prior_year    of those, Class I

Known limits. Shortage history and discontinuation notices come from the archive, which starts
2019-10-20, so for 2020 rows they cover only late 2019. Packages under an approval that covers
several units count toward each of them. Exit timing is approximate: most exits come from NSDE
inactivation dates, which bunch on a few dates a year (mostly late January, consistent with FDA
inactivating listings not renewed the year before), so many exits that happened in one year are
likely recorded early the next. package_exits_prior_year and application_exits_prior_year
inherit that lag; whether to count inactivation-based exits is left to be tested when modeling.

Input:  data/processed/unit_year_panel.parquet, data/interim/{units, application_units,
        shortage_spells, shortage_episodes_clean, episode_units, recall_units}.parquet,
        data/raw/other-nsde-*.json, data/raw/products.txt (Orange Book)
Output: data/processed/unit_year_features.parquet  the panel plus the feature columns

Usage: uv run python src/panel/add_features.py
"""

from pathlib import Path

import pandas as pd

from nsde_packages import is_active_on, load_unit_packages

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

PANEL_PATH = PROCESSED_DATA_DIR / "unit_year_panel.parquet"
FEATURES_PATH = PROCESSED_DATA_DIR / "unit_year_features.parquet"
ORANGE_BOOK_PATH = RAW_DATA_DIR / "products.txt"

# The Orange Book gives approvals before 1982 only as "Approved Prior to Jan 1, 1982", so ages
# for those drugs are lower bounds.
PRE_1982_APPROVAL = pd.Timestamp("1982-01-01")


def end_of_year(year: int) -> pd.Timestamp:
    return pd.Timestamp(year=year, month=12, day=31)


# ---- Sources ------------------------------------------------------------------------------------

def load_unit_approvals(application_units: pd.DataFrame) -> pd.DataFrame:
    """Every Orange Book approval linked to a unit, with its applicant and approval date."""
    products = pd.read_csv(ORANGE_BOOK_PATH, sep="~", dtype=str)
    approved = pd.to_datetime(products["Approval_Date"], format="%b %d, %Y", errors="coerce")
    is_pre_1982 = products["Approval_Date"].str.startswith("Approved Prior to", na=False)
    approvals = pd.DataFrame({
        "application": products["Appl_Type"].map({"N": "NDA", "A": "ANDA"}) + products["Appl_No"],
        "applicant": products["Applicant"],
        "approved": approved.where(~is_pre_1982, PRE_1982_APPROVAL),
    })
    return approvals.merge(application_units, on="application")


# ---- Feature groups -----------------------------------------------------------------------------

def supply_and_exit_features(packages: pd.DataFrame, years: range) -> pd.DataFrame:
    rows = []
    for year in years:
        as_of, year_before = end_of_year(year - 1), end_of_year(year - 2)
        active = packages[is_active_on(packages, as_of)]
        active_a_year_earlier = packages[is_active_on(packages, year_before)]

        by_unit = active.groupby("unit_id")
        counts = pd.DataFrame({
            "active_packages": by_unit["ndc11"].nunique(),
            "active_applications": by_unit["application"].nunique(),
            "active_generic_applications": active[active["application"].str.startswith("ANDA")]
                                           .groupby("unit_id")["application"].nunique(),
            "active_labelers": by_unit["labeler"].nunique(),
        })

        ended_last_year = packages[packages["end"].dt.year == year - 1]
        counts["package_exits_prior_year"] = ended_last_year.groupby("unit_id")["ndc11"].nunique()

        applications_now = set(zip(active["unit_id"], active["application"]))
        exited = [
            unit_id
            for unit_id, application in set(zip(active_a_year_earlier["unit_id"],
                                                 active_a_year_earlier["application"]))
            if (unit_id, application) not in applications_now
        ]
        counts["application_exits_prior_year"] = pd.Series(exited).value_counts()

        counts["year"] = year
        rows.append(counts.rename_axis("unit_id").reset_index())
    return pd.concat(rows, ignore_index=True)


def discontinuation_notice_features(episodes: pd.DataFrame, episode_units: pd.DataFrame,
                                    years: range) -> pd.DataFrame:
    # A notice is dated by the first capture listing the episode as To Be Discontinued, which can
    # be later than the episode's first listing. Notices already listed at the first capture have
    # an unknown listing date.
    listed = episodes["first_listed_discontinued"]
    is_dated_notice = listed.notna() & (listed > episodes["first_seen"].min())
    notices = episode_units.join(listed[is_dated_notice], on="episode_id", how="inner")
    notices["year"] = notices["first_listed_discontinued"].dt.year + 1
    counts = (notices[notices["year"].isin(years)]
              .groupby(["unit_id", "year"])["episode_id"].nunique()
              .rename("discontinuation_notices_prior_year"))
    return counts.reset_index()


def approval_features(approvals: pd.DataFrame, years: range) -> pd.DataFrame:
    first_approval = approvals.groupby("unit_id")["approved"].min()
    rows = []
    for year in years:
        as_of = end_of_year(year - 1)
        approved_by_then = approvals[approvals["approved"] <= as_of]
        years_on_market = (as_of - first_approval).dt.days / 365.25
        rows.append(pd.DataFrame({
            # A unit first approved during year t gets 0: it had no time on the market before t.
            "years_since_first_approval": years_on_market.clip(lower=0).round(1),
            "cumulative_applicants": approved_by_then.groupby("unit_id")["applicant"].nunique(),
            "year": year,
        }).rename_axis("unit_id").reset_index())
    return pd.concat(rows, ignore_index=True)


def history_and_recall_features(panel: pd.DataFrame, spells: pd.DataFrame,
                                recall_units: pd.DataFrame) -> pd.DataFrame:
    features = panel[["unit_id", "year"]].copy()

    last_spell_end = spells.groupby("unit_id")["end"].apply(sorted)
    january_first = pd.to_datetime(features["year"].astype(str) + "-01-01")
    features["had_prior_shortage"] = [
        any(end < jan_1 for end in last_spell_end.get(unit_id, []))
        for unit_id, jan_1 in zip(features["unit_id"], january_first)
    ]

    # Recalls are dated by when FDA published them in its enforcement report: a recall's
    # classification (e.g. Class I) is assigned after it starts and is public only from then.
    recalls = recall_units.assign(year=recall_units["reported"].dt.year + 1)
    by_unit_year = recalls.groupby(["unit_id", "year"])
    recall_counts = pd.DataFrame({
        "recalls_prior_year": by_unit_year["recall_number"].nunique(),
        "serious_recalls_prior_year": recalls[recalls["classification"] == "Class I"]
                                      .groupby(["unit_id", "year"])["recall_number"].nunique(),
    }).reset_index()
    return features.merge(recall_counts, on=["unit_id", "year"], how="left")


# ---- Assembly -----------------------------------------------------------------------------------

COUNT_FEATURES = [
    "active_packages", "active_applications", "active_generic_applications", "active_labelers",
    "package_exits_prior_year", "application_exits_prior_year",
    "discontinuation_notices_prior_year", "cumulative_applicants",
    "recalls_prior_year", "serious_recalls_prior_year",
]


def add_features(panel: pd.DataFrame) -> pd.DataFrame:
    units = pd.read_parquet(INTERIM_DATA_DIR / "units.parquet")
    application_units = pd.read_parquet(INTERIM_DATA_DIR / "application_units.parquet")
    spells = pd.read_parquet(INTERIM_DATA_DIR / "shortage_spells.parquet")
    episodes = pd.read_parquet(INTERIM_DATA_DIR / "shortage_episodes_clean.parquet")
    episode_units = pd.read_parquet(INTERIM_DATA_DIR / "episode_units.parquet")
    recall_units = pd.read_parquet(INTERIM_DATA_DIR / "recall_units.parquet")
    years = range(panel["year"].min(), panel["year"].max() + 1)

    features = panel.merge(units[["unit_id", "route_group"]], on="unit_id", how="left")
    for feature_group in [
        supply_and_exit_features(load_unit_packages(application_units), years),
        discontinuation_notice_features(episodes, episode_units, years),
        approval_features(load_unit_approvals(application_units), years),
        history_and_recall_features(panel, spells, recall_units),
    ]:
        features = features.merge(feature_group, on=["unit_id", "year"], how="left")

    # A unit with no matching packages, notices or recalls in a year has a count of zero.
    features[COUNT_FEATURES] = features[COUNT_FEATURES].fillna(0).astype(int)
    return features


def print_summary(features: pd.DataFrame) -> None:
    feature_columns = [column for column in features.columns
                       if column not in ("unit_id", "year", "in_shortage_on_january_1",
                                         "at_risk", "onset", "route_group")]
    print(f"rows: {len(features):,}  columns: {features.shape[1]}")
    missing = features[feature_columns].isna().sum()
    print(f"missing values: {missing[missing > 0].to_dict()}")

    at_risk = features[features["at_risk"]]
    comparison = at_risk.groupby("onset")[feature_columns].mean().T.round(2)
    comparison.columns = ["no onset (mean)", "onset (mean)"]
    print("\nat-risk rows, feature means by outcome:")
    print(comparison.to_string())
    print("\nonset rate by route group (at-risk rows):")
    print(at_risk.groupby("route_group")["onset"].agg(["size", "sum", "mean"]).round(3)
          .sort_values("mean", ascending=False).to_string())


def main():
    panel = pd.read_parquet(PANEL_PATH)
    features = add_features(panel)
    features.to_parquet(FEATURES_PATH, index=False)
    print_summary(features)
    print(f"\nwrote {FEATURES_PATH}")


if __name__ == "__main__":
    main()
