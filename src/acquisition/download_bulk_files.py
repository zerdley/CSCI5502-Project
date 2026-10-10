"""Download the public bulk files the project uses (~100 MB) into data/raw/ and unzip them.

Usage: uv run python src/acquisition/download_bulk_files.py
"""

import zipfile

from downloads import download_cms_dataset, download_file
from paths import RAW_DATA_DIR

OPENFDA = "https://download.open.fda.gov"

BULK_FILES = {
    # openFDA
    "drug-shortages-0001-of-0001.json.zip":
        f"{OPENFDA}/drug/shortages/drug-shortages-0001-of-0001.json.zip",
    "drug-ndc-0001-of-0001.json.zip":
        f"{OPENFDA}/drug/ndc/drug-ndc-0001-of-0001.json.zip",
    "drug-enforcement-0001-of-0001.json.zip":
        f"{OPENFDA}/drug/enforcement/drug-enforcement-0001-of-0001.json.zip",
    "other-nsde-0001-of-0003.json.zip": f"{OPENFDA}/other/nsde/other-nsde-0001-of-0003.json.zip",
    "other-nsde-0002-of-0003.json.zip": f"{OPENFDA}/other/nsde/other-nsde-0002-of-0003.json.zip",
    "other-nsde-0003-of-0003.json.zip": f"{OPENFDA}/other/nsde/other-nsde-0003-of-0003.json.zip",
    # FDA Orange Book
    "orangebook_ascii.zip": "https://www.fda.gov/media/76860/download?attachment",
    # CMS publishes a new crosswalk each quarter under a dated URL; this one will eventually 404.
    "ndc_hcpcs_crosswalk.zip": "https://www.cms.gov/files/zip/july-2026-ndc-hcpcs-crosswalk.zip",
}

# Medicare spending datasets on data.cms.gov, fetched through its paginated API.
CMS_DATASETS = {
    "ptb_spending.json": "76a714ad-3a2c-43ac-b76d-9dadf8f7d890",
    "ptd_spending.json": "7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b",
}


def main():
    for file_name, url in BULK_FILES.items():
        destination = RAW_DATA_DIR / file_name
        size = download_file(url, destination)
        print(f"  {file_name} ({size:,} bytes)")

        if destination.suffix == ".zip":
            with zipfile.ZipFile(destination) as archive:
                archive.extractall(RAW_DATA_DIR)

    for file_name, dataset_id in CMS_DATASETS.items():
        row_count = download_cms_dataset(dataset_id, RAW_DATA_DIR / file_name)
        print(f"  {file_name} ({row_count:,} rows)")

    print(f"done -> {RAW_DATA_DIR}")


if __name__ == "__main__":
    main()
