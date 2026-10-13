"""Build the unit x year panel: which units were at risk of a new shortage each year, and which
had one.

Shortage spells. A unit's shortage episodes are merged into spells: stretches of time when the
unit was in shortage, where a gap of less than WASHOUT_DAYS does not end a spell. Without the
washout, FDA editing a presentation's text (which the stitch step sees as a new episode) or a long
gap between archive captures would look like the unit leaving and re-entering shortage.

Onset date. An episode's start is FDA's Initial Posting Date when that date falls between the
last archive capture that did not list the episode and the first that did, since the archive then
confirms it. Otherwise it is the first capture listing the episode (first_seen). Since about 2023,
FDA files newly affected packages under a drug's original posting date (a median of three years
earlier for rows first seen in 2025), so a posting date outside that window is stale. The check
also gives precise dates to shortages that began during the archive's long capture gaps, which
first_seen alone would push to the end of the gap.

Discontinuations are not shortages. Episodes only ever listed as "To Be Discontinued" record a
manufacturer exiting, which is a predictor of interest (research question 3), not the outcome.

Panel rows. One row per unit per year in which at least one of its packages was on the market,
according to NSDE marketing dates. A unit-year is at risk if the unit was not already in a
shortage spell on January 1; onset = 1 if a spell started that year.

Label years are 2020-2025. The archive starts 2019-10-20, so spells already running at the first
capture have unknown start dates, and 2026 is incomplete.

Input:  data/interim/shortage_episodes_clean.parquet, data/interim/episode_units.parquet,
        data/interim/application_units.parquet, data/raw/other-nsde-*.json,
        data/raw/cder_archive/*.csv (file names only, for the capture dates)
Output: data/interim/shortage_spells.parquet  one row per (unit, shortage spell)
        data/processed/unit_year_panel.parquet  one row per (unit, year on the market)

Usage: uv run python src/panel/build_unit_year_panel.py
"""

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

EPISODES_PATH = INTERIM_DATA_DIR / "shortage_episodes_clean.parquet"
EPISODE_UNITS_PATH = INTERIM_DATA_DIR / "episode_units.parquet"
APPLICATION_UNITS_PATH = INTERIM_DATA_DIR / "application_units.parquet"
NSDE_PATHS = sorted(RAW_DATA_DIR.glob("other-nsde-*-of-*.json"))
ARCHIVE_DIR = RAW_DATA_DIR / "cder_archive"
SPELLS_PATH = INTERIM_DATA_DIR / "shortage_spells.parquet"
PANEL_PATH = PROCESSED_DATA_DIR / "unit_year_panel.parquet"

WASHOUT_DAYS = 365
LABEL_YEARS = range(2020, 2026)

# ---- Shortage spells ----------------------------------------------------------------------------

def archive_capture_dates() -> pd.DatetimeIndex:
    """Captures are named by Internet Archive timestamp, e.g. 20191020223457.csv."""
    dates = pd.to_datetime([path.stem[:8] for path in ARCHIVE_DIR.glob("*.csv")], format="%Y%m%d")
    return pd.DatetimeIndex(sorted(set(dates)))


def estimated_start(first_seen: pd.Series, posted: pd.Series,
                    capture_dates: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    """Each episode's start date, and whether it came from the posting date or first_seen."""
    position = capture_dates.searchsorted(first_seen)
    has_previous = position > 0
    previous_capture = pd.Series(pd.NaT, index=first_seen.index, dtype=first_seen.dtype)
    previous_capture[has_previous] = capture_dates[position[has_previous] - 1]

    posted_confirmed = (posted > previous_capture) & (posted <= first_seen)
    start = posted.where(posted_confirmed, first_seen)
    source = pd.Series("first_seen", index=first_seen.index).where(~posted_confirmed, "posted")
    return start, source


def shortage_episode_intervals(episodes: pd.DataFrame, episode_units: pd.DataFrame,
                               capture_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per (unit, shortage episode) with the dates it was known to be in shortage."""
    is_shortage = episodes["statuses"] != "To Be Discontinued"
    intervals = episode_units.join(episodes.loc[is_shortage], on="episode_id", how="inner")
    start, start_source = estimated_start(intervals["first_seen"], intervals["posted"],
                                          capture_dates)
    # An episode with no resolution date was in shortage at least until the last capture listing
    # it. Some are first captured already resolved, so the end can't precede the start.
    end = intervals["resolved_date"].fillna(intervals["last_seen"])
    return pd.DataFrame({
        "unit_id": intervals["unit_id"],
        "start": start,
        "end": end.where(end > start, start),
        "start_source": start_source,
        "start_unknown": intervals["first_seen"] == capture_dates[0],
    })


def merge_into_spells(intervals: pd.DataFrame, final_capture: pd.Timestamp) -> pd.DataFrame:
    washout = pd.Timedelta(days=WASHOUT_DAYS)
    spells = []
    for unit_id, unit_intervals in intervals.sort_values("start").groupby("unit_id"):
        spell = None
        for interval in unit_intervals.itertuples():
            if spell is not None and interval.start <= spell["end"] + washout:
                spell["end"] = max(spell["end"], interval.end)
            else:
                if spell is not None:
                    spells.append(spell)
                spell = {"unit_id": unit_id, "start": interval.start, "end": interval.end,
                         "start_source": interval.start_source,
                         "start_unknown": interval.start_unknown}
        spells.append(spell)

    spells = pd.DataFrame(spells)
    spells["still_active"] = spells["end"] == final_capture
    return spells.reset_index(drop=True)


# ---- Market presence ----------------------------------------------------------------------------

def unit_market_years(application_units: pd.DataFrame) -> pd.DataFrame:
    """Every (unit, year) in LABEL_YEARS in which NSDE shows one of the unit's packages marketed."""
    rows = []
    for path in NSDE_PATHS:
        with open(path) as file:
            rows.extend(json.load(file)["results"])
    packages = pd.DataFrame(rows)[["application_number_or_citation", "marketing_start_date",
                                   "marketing_end_date"]]
    packages = packages.rename(columns={"application_number_or_citation": "application"})
    packages = packages.merge(application_units, on="application")

    start_year = pd.to_datetime(packages["marketing_start_date"], format="%Y%m%d").dt.year
    # A missing end date means the package is still marketed.
    end_year = (pd.to_datetime(packages["marketing_end_date"], format="%Y%m%d").dt.year
                .fillna(max(LABEL_YEARS)))

    market_years = [
        (unit_id, year)
        for unit_id, first, last in zip(packages["unit_id"], start_year, end_year)
        for year in LABEL_YEARS
        if first <= year <= last
    ]
    return (pd.DataFrame(market_years, columns=["unit_id", "year"])
            .drop_duplicates().sort_values(["unit_id", "year"]).reset_index(drop=True))


# ---- Panel --------------------------------------------------------------------------------------

def build_panel(market_years: pd.DataFrame, spells: pd.DataFrame) -> pd.DataFrame:
    panel = market_years.copy()
    january_first = pd.to_datetime(panel["year"].astype(str) + "-01-01")

    spells_by_unit = dict(tuple(spells.groupby("unit_id")))
    in_shortage_on_january_1 = []
    onset = []
    for unit_id, jan_1, year in zip(panel["unit_id"], january_first, panel["year"]):
        unit_spells = spells_by_unit.get(unit_id)
        if unit_spells is None:
            in_shortage_on_january_1.append(False)
            onset.append(0)
            continue
        in_shortage_on_january_1.append(
            ((unit_spells["start"] < jan_1) & (unit_spells["end"] >= jan_1)).any())
        starts_this_year = (unit_spells["start"].dt.year == year) & ~unit_spells["start_unknown"]
        onset.append(int(starts_this_year.any()))

    panel["in_shortage_on_january_1"] = in_shortage_on_january_1
    panel["at_risk"] = ~panel["in_shortage_on_january_1"]
    panel["onset"] = onset
    return panel


def print_summary(spells: pd.DataFrame, panel: pd.DataFrame) -> None:
    print(f"shortage spells: {len(spells):,} across {spells['unit_id'].nunique():,} units")
    print(f"  started before the first capture (start unknown): {spells['start_unknown'].sum()}")
    known = spells[~spells["start_unknown"]]
    print(f"  start date from: {known['start_source'].value_counts().to_dict()}")
    print(f"  still active at the final capture: {spells['still_active'].sum()}")
    repeat_spells = spells[~spells["start_unknown"]].duplicated("unit_id").sum()
    print(f"  repeat spells for the same unit: {repeat_spells}")

    known_onsets = spells[~spells["start_unknown"]]
    onsets_in_label_years = known_onsets[known_onsets["start"].dt.year.isin(LABEL_YEARS)]
    onset_units_in_panel = onsets_in_label_years.merge(
        panel, left_on=["unit_id", onsets_in_label_years["start"].dt.year],
        right_on=["unit_id", "year"], how="left", indicator=True)
    off_market = (onset_units_in_panel["_merge"] == "left_only").sum()
    print(f"  onsets in {min(LABEL_YEARS)}-{max(LABEL_YEARS)} for a unit NSDE shows off the "
          f"market that year (dropped): {off_market}")

    by_year = panel.groupby("year").agg(
        units_on_market=("unit_id", "size"),
        at_risk=("at_risk", "sum"),
        onsets=("onset", "sum"),
    )
    at_risk_onsets = panel[panel["at_risk"]].groupby("year")["onset"].sum()
    by_year["onset_rate_among_at_risk"] = (at_risk_onsets / by_year["at_risk"]).round(4)
    print("\npanel by year:")
    print(by_year.to_string())
    not_at_risk_onsets = panel.loc[~panel["at_risk"], "onset"].sum()
    # The washout makes this impossible, so anything nonzero is a bug.
    print(f"\nonsets in unit-years not at risk (should be 0): {not_at_risk_onsets}")


def main():
    episodes = pd.read_parquet(EPISODES_PATH)
    episode_units = pd.read_parquet(EPISODE_UNITS_PATH)
    application_units = pd.read_parquet(APPLICATION_UNITS_PATH)

    capture_dates = archive_capture_dates()
    intervals = shortage_episode_intervals(episodes, episode_units, capture_dates)
    spells = merge_into_spells(intervals, capture_dates[-1])
    panel = build_panel(unit_market_years(application_units), spells)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    spells.to_parquet(SPELLS_PATH, index=False)
    panel.to_parquet(PANEL_PATH, index=False)
    print_summary(spells, panel)
    print(f"\nwrote {SPELLS_PATH}\nwrote {PANEL_PATH}")


if __name__ == "__main__":
    main()
