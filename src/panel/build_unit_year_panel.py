"""Build the unit x year panel: which units were at risk of a new shortage each year, and which
had one.

Shortage spells. A unit's shortage episodes are merged into spells: stretches of time when the
unit was in shortage, where a gap of less than WASHOUT_DAYS does not end a spell. Without the
washout, FDA editing a presentation's text (which the stitch step sees as a new episode) or a long
gap between archive captures would look like the unit leaving and re-entering shortage.

Onset date. An episode's start is FDA's Initial Posting Date when that date falls between the
last archive capture that did not list the episode and the first that did, since the archive then
confirms it. Otherwise it is the first capture listing the episode (first_seen). From 2023 on,
most newly listed shortage episodes carry a posting date more than a year old: either FDA rewrote
an existing row's description (which the stitch step sees as a new episode but which keeps its
date), or FDA listed a new package under a drug's existing entry and date. The check also gives
precise dates to shortages that began during the archive's long capture gaps, which first_seen
alone would push to the end of the gap. An episode first captured already resolved began before
that capture, so it starts at its posting date, and its start is unknown if that posting date
precedes the archive.

Discontinuations are not shortages. Episodes only ever listed as "To Be Discontinued" record a
manufacturer exiting, which is a predictor of interest (research question 3), not the outcome.

Panel rows. One row per unit per year t if at least one of its packages was on the market at the
end of year t-1, according to NSDE (nsde_packages.py), so membership uses nothing from year t.
A unit-year is at risk if none of the unit's shortage episodes was active on January 1. That uses
episodes, not spells, because a spell can be bridged across January 1 by an episode that only
appears later in the year, which a forecaster on January 1 couldn't know. onset = 1 if a spell
started that year.

Label years are 2020-2025. The archive starts 2019-10-20, so spells already running at the first
capture have unknown start dates, and 2026 is incomplete.

Input:  data/interim/shortage_episodes_clean.parquet, data/interim/episode_units.parquet,
        data/interim/application_units.parquet, data/raw/other-nsde-*.json (via nsde_packages),
        data/raw/cder_archive/*.csv (file names only, for the capture dates)
Output: data/interim/shortage_spells.parquet  one row per (unit, shortage spell)
        data/processed/unit_year_panel.parquet  one row per (unit, year it entered on the market)

Usage: uv run python src/panel/build_unit_year_panel.py
"""

from pathlib import Path

import pandas as pd

from nsde_packages import is_active_on, load_unit_packages

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

EPISODES_PATH = INTERIM_DATA_DIR / "shortage_episodes_clean.parquet"
EPISODE_UNITS_PATH = INTERIM_DATA_DIR / "episode_units.parquet"
APPLICATION_UNITS_PATH = INTERIM_DATA_DIR / "application_units.parquet"
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
    start_unknown = intervals["first_seen"] == capture_dates[0]

    resolved_before_listed = intervals["resolved_date"] < intervals["first_seen"]
    start = start.where(~resolved_before_listed, intervals["posted"])
    start_source = start_source.where(~resolved_before_listed, "posted")
    start_unknown |= resolved_before_listed & ~(intervals["posted"] >= capture_dates[0])

    # An episode with no resolution date was in shortage at least until the last capture listing
    # it.
    end = intervals["resolved_date"].fillna(intervals["last_seen"])
    start = start.fillna(intervals["first_seen"])
    return pd.DataFrame({
        "unit_id": intervals["unit_id"],
        "start": start,
        "end": end.where(end > start, start),
        "start_source": start_source,
        "start_unknown": start_unknown,
    })


def merge_into_spells(intervals: pd.DataFrame, final_capture: pd.Timestamp,
                      washout_days: int = WASHOUT_DAYS) -> pd.DataFrame:
    washout = pd.Timedelta(days=washout_days)
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
    """Every (unit, year t) in LABEL_YEARS with a package on the market at the end of t-1."""
    packages = load_unit_packages(application_units)
    market_years = [
        pd.DataFrame({"unit_id": packages.loc[is_active_on(packages, end_of_previous_year),
                                              "unit_id"].unique(), "year": year})
        for year in LABEL_YEARS
        for end_of_previous_year in [pd.Timestamp(year=year - 1, month=12, day=31)]
    ]
    return pd.concat(market_years).sort_values(["unit_id", "year"]).reset_index(drop=True)


# ---- Panel --------------------------------------------------------------------------------------

def build_panel(market_years: pd.DataFrame, intervals: pd.DataFrame,
                spells: pd.DataFrame) -> pd.DataFrame:
    panel = market_years.copy()
    january_first = pd.to_datetime(panel["year"].astype(str) + "-01-01")

    intervals_by_unit = dict(tuple(intervals.groupby("unit_id")))
    spells_by_unit = dict(tuple(spells.groupby("unit_id")))
    in_shortage_on_january_1 = []
    onset = []
    for unit_id, jan_1, year in zip(panel["unit_id"], january_first, panel["year"]):
        unit_intervals = intervals_by_unit.get(unit_id)
        unit_spells = spells_by_unit.get(unit_id)
        if unit_spells is None:
            in_shortage_on_january_1.append(False)
            onset.append(0)
            continue
        in_shortage_on_january_1.append(
            ((unit_intervals["start"] < jan_1) & (unit_intervals["end"] >= jan_1)).any())
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
    print(f"  onsets in {min(LABEL_YEARS)}-{max(LABEL_YEARS)} for a unit with no package on the "
          f"market at the end of the previous year (dropped): {off_market}")

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
    # An episode active on January 1 belongs to a spell already running then, and the washout
    # stops a new spell from starting within the year, so anything nonzero is a bug.
    print(f"\nonsets in unit-years not at risk (should be 0): {not_at_risk_onsets}")


def main():
    episodes = pd.read_parquet(EPISODES_PATH)
    episode_units = pd.read_parquet(EPISODE_UNITS_PATH)
    application_units = pd.read_parquet(APPLICATION_UNITS_PATH)

    capture_dates = archive_capture_dates()
    intervals = shortage_episode_intervals(episodes, episode_units, capture_dates)
    spells = merge_into_spells(intervals, capture_dates[-1])
    panel = build_panel(unit_market_years(application_units), intervals, spells)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    spells.to_parquet(SPELLS_PATH, index=False)
    panel.to_parquet(PANEL_PATH, index=False)
    print_summary(spells, panel)
    print(f"\nwrote {SPELLS_PATH}\nwrote {PANEL_PATH}")


if __name__ == "__main__":
    main()
