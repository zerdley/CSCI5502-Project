"""Locations of the project's local data folders, which are gitignored."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"
INTERIM_DATA_DIR = REPO_ROOT / "data" / "interim"
