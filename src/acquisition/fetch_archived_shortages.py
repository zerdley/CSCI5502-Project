"""Fetch every archived copy of FDA's drug-shortage CSV from the Internet Archive.

FDA purges resolved shortages from its live list after about six months, so the live file is only
a snapshot. Archived copies are the only public source of shortage start and end dates.

Each capture is saved as data/raw/cder_archive/<capture timestamp>.csv. Captures already on disk
are skipped, so the script is safe to re-run after an interruption.

Usage: uv run python src/acquisition/fetch_archived_shortages.py
"""

import time
from pathlib import Path

import requests

from downloads import DownloadFailed, download_file, is_already_downloaded
from paths import RAW_DATA_DIR

SHORTAGE_CSV_URL = "https://www.accessdata.fda.gov/scripts/drugshortages/Drugshortages.cfm"
ARCHIVE_INDEX_URL = "https://web.archive.org/cdx/search/cdx"
ARCHIVE_DIR = RAW_DATA_DIR / "cder_archive"

# The Internet Archive throttles hard below this.
SECONDS_BETWEEN_REQUESTS = 6

# Every real capture begins with this column. The Wayback Machine sometimes serves its own HTML
# error page instead, large enough to pass the bot-detection size check.
EXPECTED_FIRST_COLUMN = "Generic Name"


def list_capture_timestamps() -> list[str]:
    """Ask the Internet Archive for the timestamp of every successful capture of the CSV."""
    response = requests.get(
        ARCHIVE_INDEX_URL,
        params={
            "url": SHORTAGE_CSV_URL.removeprefix("https://"),
            "output": "json",
            "filter": "statuscode:200",
            "limit": 2000,
        },
        timeout=60,
    )
    response.raise_for_status()
    header, *captures = response.json()
    timestamp_column = header.index("timestamp")
    return sorted({capture[timestamp_column] for capture in captures})


def capture_url(timestamp: str) -> str:
    # The "id_" suffix asks for the original file, without the Wayback Machine's page wrapper.
    return f"https://web.archive.org/web/{timestamp}id_/{SHORTAGE_CSV_URL}"


def is_shortage_csv(path: Path) -> bool:
    if not is_already_downloaded(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as file:
        return file.read(1000).lstrip().startswith(EXPECTED_FIRST_COLUMN)


def main():
    timestamps = list_capture_timestamps()
    print(f"{len(timestamps)} archived captures")

    downloaded = skipped = failed = 0
    for count, timestamp in enumerate(timestamps, start=1):
        destination = ARCHIVE_DIR / f"{timestamp}.csv"
        if is_shortage_csv(destination):
            skipped += 1
            continue

        try:
            download_file(capture_url(timestamp), destination)
            if not is_shortage_csv(destination):
                destination.unlink()
                raise DownloadFailed(f"{timestamp}: not a CSV, likely a Wayback error page")
            downloaded += 1
        except DownloadFailed as error:
            failed += 1
            print(f"  failed: {error}")

        if count % 10 == 0:
            print(f"  [{count}/{len(timestamps)}] "
                  f"downloaded={downloaded} skipped={skipped} failed={failed}")
        time.sleep(SECONDS_BETWEEN_REQUESTS)

    print(f"DONE downloaded={downloaded} skipped={skipped} failed={failed} -> {ARCHIVE_DIR}")


if __name__ == "__main__":
    main()
