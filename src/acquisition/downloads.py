"""Shared download helpers for the acquisition scripts."""

import json
from pathlib import Path

import requests
import truststore

# Trust the operating system's certificate store, as curl does. Without this, Python fails TLS
# verification on networks that intercept traffic with their own certificate.
truststore.inject_into_ssl()

# fda.gov and cms.gov sit behind Akamai bot detection and reject requests without a browser UA.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)

# Akamai's block page arrives as a ~419-byte file with HTTP 200, so file size is the only
# reliable sign that a download actually worked. Every real file we fetch is far larger.
MIN_VALID_FILE_BYTES = 10_000

CMS_DATA_API = "https://data.cms.gov/data-api/v1/dataset"
CMS_PAGE_SIZE = 5_000


class DownloadFailed(Exception):
    pass


def download_file(url: str, destination: Path, timeout_seconds: int = 180) -> int:
    """Download url to destination and return its size in bytes.

    Raises DownloadFailed on an HTTP error or a suspiciously small file, and deletes any
    partial file so a re-run will try again.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(
            url,
            headers={"User-Agent": BROWSER_USER_AGENT},
            timeout=timeout_seconds,
            stream=True,
        )
        response.raise_for_status()
        with open(destination, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                file.write(chunk)
    except requests.RequestException as error:
        destination.unlink(missing_ok=True)
        raise DownloadFailed(f"{url}: {error}") from error

    size = destination.stat().st_size
    if size < MIN_VALID_FILE_BYTES:
        destination.unlink()
        raise DownloadFailed(f"{url}: only {size} bytes, likely a bot-detection page")
    return size


def download_cms_dataset(dataset_id: str, destination: Path) -> int:
    """Download every row of a data.cms.gov dataset to destination as one JSON array.

    The CMS API returns at most 1,000 rows per request by default, so a single request silently
    truncates larger datasets. This pages through until a short page comes back, then checks the
    row count against the total the API reports. Returns the number of rows.
    """
    dataset_url = f"{CMS_DATA_API}/{dataset_id}/data"
    try:
        rows = []
        while True:
            response = requests.get(
                dataset_url,
                params={"offset": len(rows), "size": CMS_PAGE_SIZE},
                timeout=180,
            )
            response.raise_for_status()
            page = response.json()
            rows.extend(page)
            if len(page) < CMS_PAGE_SIZE:
                break

        stats = requests.get(f"{dataset_url}/stats", timeout=60)
        stats.raise_for_status()
        expected_rows = stats.json()["total_rows"]
    except requests.RequestException as error:
        raise DownloadFailed(f"{dataset_url}: {error}") from error

    if len(rows) != expected_rows:
        raise DownloadFailed(f"{dataset_url}: got {len(rows)} rows, CMS reports {expected_rows}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "w") as file:
        json.dump(rows, file)
    return len(rows)


def is_already_downloaded(path: Path) -> bool:
    return path.exists() and path.stat().st_size >= MIN_VALID_FILE_BYTES
