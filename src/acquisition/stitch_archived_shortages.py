"""Stitch archived FDA drug-shortage snapshots into one row per shortage episode.

Why this is needed: each archived CSV from fetch_archived_shortages.py is FDA's shortage list as it
looked on one day. FDA deletes resolved shortages about six months after they resolve, so no single
snapshot holds the full history. Lining up every snapshot recovers it.

How it works:
  1. An episode is one presentation (a specific package from a specific company) going into
     shortage on a given posting date, identified by
     (generic name, company, presentation, initial posting date).
  2. Every row of every snapshot is matched to its episode; the episode is created the first time
     it is seen.
  3. Each sighting adds what that snapshot knows: when the episode was first and last seen, which
     statuses it passed through, and, once a snapshot lists it as Resolved, its resolution date.

Episodes that open and close between two captures never appear, so short shortages are
under-represented.

Input:  data/raw/cder_archive/*.csv
Output: data/interim/shortage_episodes.csv

Usage: uv run python src/acquisition/stitch_archived_shortages.py
"""

import csv
import datetime
import io
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from paths import INTERIM_DATA_DIR, RAW_DATA_DIR

ARCHIVE_DIR = RAW_DATA_DIR / "cder_archive"
OUTPUT_PATH = INTERIM_DATA_DIR / "shortage_episodes.csv"

# FDA records shortages that began before its records start as 01/01/2012, which its website
# shows as "Prior to 2012". Their true start date is unknown (left-censored).
PRIOR_TO_2012_SENTINEL = datetime.date(2012, 1, 1)

# Years outside this range are typos (e.g. 12/03/2108) and are treated as missing dates.
PLAUSIBLE_YEARS = range(2005, 2028)

# A gap between captures longer than FDA's purge window can hide resolutions entirely.
PURGE_WINDOW_DAYS = 183

OUTPUT_COLUMNS = [
    "generic", "company", "presentation", "posted", "resolved_date", "discontinued_date",
    "duration_days", "resolved", "left_censored", "category", "reason",
    "first_seen", "last_seen", "statuses",
]

EpisodeKey = tuple[str, str, str, datetime.date]


@dataclass
class Episode:
    generic: str
    company: str
    presentation: str
    posted: datetime.date
    category: str
    reason: str
    first_seen: datetime.date
    last_seen: datetime.date
    resolved_date: datetime.date | None = None
    discontinued_date: datetime.date | None = None
    statuses: set[str] = field(default_factory=set)

    @property
    def is_left_censored(self) -> bool:
        return self.posted == PRIOR_TO_2012_SENTINEL

    @property
    def duration_days(self) -> int | None:
        if self.resolved_date is None or self.is_left_censored:
            return None
        return (self.resolved_date - self.posted).days

    def to_csv_row(self) -> dict:
        return {
            "generic": self.generic,
            "company": self.company,
            "presentation": self.presentation,
            "posted": self.posted.isoformat(),
            "resolved_date": self.resolved_date.isoformat() if self.resolved_date else None,
            "discontinued_date":
                self.discontinued_date.isoformat() if self.discontinued_date else None,
            "duration_days": self.duration_days,
            "resolved": int(self.resolved_date is not None),
            "left_censored": int(self.is_left_censored),
            "category": self.category,
            "reason": self.reason,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "statuses": "|".join(sorted(status for status in self.statuses if status)),
        }


def parse_fda_date(text: str | None) -> datetime.date | None:
    """Parse an FDA date (MM/DD/YYYY or YYYY-MM-DD), returning None if missing or implausible."""
    text = (text or "").strip()
    for date_format in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            date = datetime.datetime.strptime(text, date_format).date()
        except ValueError:
            continue
        return date if date.year in PLAUSIBLE_YEARS else None
    return None


def clean_cell(value: str | list | None) -> str:
    # csv.DictReader collects the extra cells of an over-long row into a list.
    if isinstance(value, list):
        value = " ".join(part for part in value if part)
    return (value or "").strip()


def read_snapshot(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", errors="replace") as file:
        # Some captures begin with blank lines, which would otherwise be read as the header.
        text = file.read().lstrip("\r\n")
    return [
        {clean_cell(column): clean_cell(value) for column, value in row.items()}
        for row in csv.DictReader(io.StringIO(text))
    ]


def snapshot_date(path: Path) -> datetime.date:
    """Captures are named by Internet Archive timestamp, e.g. 20191020223457.csv."""
    return datetime.datetime.strptime(path.stem[:8], "%Y%m%d").date()


def record_sighting(episodes: dict[EpisodeKey, Episode], row: dict[str, str],
                    seen_on: datetime.date) -> None:
    """Fold one snapshot row into its episode, creating the episode on its first sighting."""
    posted = parse_fda_date(row.get("Initial Posting Date"))
    if posted is None:
        return

    key = (row.get("Generic Name", ""), row.get("Company Name", ""),
           row.get("Presentation", ""), posted)
    episode = episodes.get(key)
    if episode is None:
        episode = Episode(
            generic=row.get("Generic Name", ""),
            company=row.get("Company Name", ""),
            presentation=row.get("Presentation", ""),
            posted=posted,
            category=row.get("Therapeutic Category", ""),
            reason=row.get("Reason for Shortage", ""),
            first_seen=seen_on,
            last_seen=seen_on,
        )
        episodes[key] = episode

    episode.first_seen = min(episode.first_seen, seen_on)
    episode.last_seen = max(episode.last_seen, seen_on)

    status = row.get("Status", "")
    episode.statuses.add(status)

    if not episode.category:
        episode.category = row.get("Therapeutic Category", "")
    if not episode.reason:
        episode.reason = row.get("Reason for Shortage", "")

    if status.lower() == "resolved":
        # On a Resolved row, Change Date is the resolution date. If snapshots disagree, keep
        # the earliest.
        resolved_on = parse_fda_date(row.get("Change Date"))
        if resolved_on and (episode.resolved_date is None or resolved_on < episode.resolved_date):
            episode.resolved_date = resolved_on

    if status.lower().startswith("to be disc"):
        discontinued_on = parse_fda_date(row.get("Date Discontinued"))
        if discontinued_on:
            episode.discontinued_date = discontinued_on


def print_capture_coverage(capture_dates: list[datetime.date]) -> None:
    days = sorted(set(capture_dates))
    gaps = [(later - earlier).days for earlier, later in zip(days, days[1:])]
    print(f"observation days: {len(days)}  {days[0]} -> {days[-1]}")
    if gaps:
        median_gap = sorted(gaps)[len(gaps) // 2]
        gaps_over_purge_window = sum(gap > PURGE_WINDOW_DAYS for gap in gaps)
        print(f"gaps: median {median_gap}d  max {max(gaps)}d  "
              f"> {PURGE_WINDOW_DAYS}d (FDA purge window): {gaps_over_purge_window}")


def print_episode_summary(episodes: list[Episode]) -> None:
    durations = sorted(e.duration_days for e in episodes if e.duration_days is not None)

    print(f"\nEPISODES: {len(episodes)}")
    print(f"  distinct generic names        : {len({e.generic for e in episodes})}")
    print(f"  with a RESOLUTION date        : {sum(e.resolved_date is not None for e in episodes)}")
    print(f"  with a computable duration    : {len(durations)}")
    print(f"  left-censored ('Prior to 2012'): {sum(e.is_left_censored for e in episodes)}")

    if durations:
        def percentile(fraction):
            return durations[int(fraction * (len(durations) - 1))]

        print(f"  duration days  p25={percentile(.25)}  median={percentile(.5)}  "
              f"p75={percentile(.75)}  mean={sum(durations) // len(durations)}")

    onsets_by_year = Counter(e.posted.year for e in episodes)
    print("\n  episode onsets by year:")
    for year in sorted(onsets_by_year):
        if year >= 2012:
            print(f"    {year}  {onsets_by_year[year]:>5}")


def write_episodes(episodes: list[Episode], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(episode.to_csv_row() for episode in episodes)


def main():
    snapshot_paths = sorted(ARCHIVE_DIR.glob("*.csv"))
    print(f"snapshots: {len(snapshot_paths)}")
    if not snapshot_paths:
        raise SystemExit("no archived snapshots -- run fetch_archived_shortages.py first")

    episodes: dict[EpisodeKey, Episode] = {}
    for path in snapshot_paths:
        seen_on = snapshot_date(path)
        for row in read_snapshot(path):
            record_sighting(episodes, row, seen_on)

    print_capture_coverage([snapshot_date(path) for path in snapshot_paths])
    print_episode_summary(list(episodes.values()))
    write_episodes(list(episodes.values()), OUTPUT_PATH)
    print(f"\nwrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
