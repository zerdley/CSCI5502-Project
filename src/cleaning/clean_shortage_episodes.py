"""Clean the stitched shortage episodes into two analysis-ready tables.

Input:  data/interim/shortage_episodes.csv (from src/acquisition/stitch_archived_shortages.py)

Output: data/interim/shortage_episodes_clean.parquet
            One row per episode. Statuses are standardized, and the free-text reason is mapped to
            one yes/no column per cause category (an episode can list several causes).
        data/interim/shortage_episode_ndcs.parquet
            One row per (episode, NDC) found in the episode's presentation text, with the NDC
            converted to the 11-digit form NSDE uses (package_ndc11), ready to join on.

episode_id links the two tables. It is the episode's row number in this run's output, so it is
consistent between the two files but changes whenever the episodes are rebuilt.

Usage: uv run python src/cleaning/clean_shortage_episodes.py
"""

import re
from pathlib import Path

import pandas as pd

INTERIM_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "interim"

EPISODES_PATH = INTERIM_DATA_DIR / "shortage_episodes.csv"
CLEAN_EPISODES_PATH = INTERIM_DATA_DIR / "shortage_episodes_clean.parquet"
EPISODE_NDCS_PATH = INTERIM_DATA_DIR / "shortage_episode_ndcs.parquet"

DATE_COLUMNS = ["posted", "resolved_date", "discontinued_date", "first_seen", "last_seen",
                "first_listed_discontinued"]

STATUS_SPELLINGS = {
    "current": "Current",
    "resolved": "Resolved",
    "to be discontinued": "To Be Discontinued",
}

# ---- Reasons ------------------------------------------------------------------------------------

# The categories manufacturers report under the 2012 FDASIA notification rule, plus manufacturing
# delay, which is common in the data but fits none of them.
REASON_CATEGORIES = [
    "demand_increase",
    "active_ingredient",
    "inactive_ingredient",
    "gmp_compliance",
    "discontinuation",
    "shipping_delay",
    "regulatory_delay",
    "manufacturing_delay",
    "other",
]

# Values that appear in the reason field but say nothing about the cause. "Available" is an
# availability status that leaked into the reason column in some captures.
NOT_A_REASON = {"", "available", "tbd", "information pending"}

# Every reason spelling seen in the data, after normalize_reason(), mapped to its categories.
# A spelling missing from this table stops the script, so new variants get a human decision.
REASON_MAP = {
    "demand increase for the drug": ["demand_increase"],
    "demand increase for drug": ["demand_increase"],
    "demand increase in the drug": ["demand_increase"],
    "demand increase of the drug": ["demand_increase"],
    "demand increase of drug": ["demand_increase"],
    "demand increase for the product": ["demand_increase"],
    "demand increase": ["demand_increase"],
    "increase in demand": ["demand_increase"],
    "increased demand for the product": ["demand_increase"],
    "demand increase due to covid-19": ["demand_increase"],
    "available; demand increase for the drug": ["demand_increase"],

    "shortage of an active ingredient": ["active_ingredient"],
    "shortage of active ingredient": ["active_ingredient"],
    "shortage of an active ingredient component": ["active_ingredient"],
    "shortage of an active component": ["active_ingredient"],
    "api shortage": ["active_ingredient"],
    "limited api availability": ["active_ingredient"],
    "availability of api": ["active_ingredient"],
    "api procurement delay": ["active_ingredient"],
    "api supply issue": ["active_ingredient"],
    # Molybdenum-99 is the raw isotope that technetium-99m imaging agents are made from.
    "molybdenum-99 shortage": ["active_ingredient"],
    "molybdenum 99 shortage": ["active_ingredient"],

    "shortage of an inactive ingredient component": ["inactive_ingredient"],
    "shortage of an inactive ingredient": ["inactive_ingredient"],
    "shortage of inactive ingredient": ["inactive_ingredient"],

    "requirements related to complying with good manufacturing practices": ["gmp_compliance"],
    "requirements related to complying with good manufacturing processes": ["gmp_compliance"],

    "discontinuation of the manufacture of the drug": ["discontinuation"],
    "discontinuation of manufacture of the drug (from existing site)": ["discontinuation"],
    "discontinuation of the manufacture of the drug substance": ["discontinuation"],
    "discontinued": ["discontinuation"],

    "delay in shipping of the drug": ["shipping_delay"],
    "delay in shipping of drug": ["shipping_delay"],
    "delay in shipping of the drug product": ["shipping_delay"],
    "delay in shipping": ["shipping_delay"],

    "regulatory delay": ["regulatory_delay"],

    "manufacturing delay": ["manufacturing_delay"],
    "manufacturing delays": ["manufacturing_delay"],
    "delay in manufacturing": ["manufacturing_delay"],
    "delays due to manufacturing issues": ["manufacturing_delay"],

    "other": ["other"],
    "oither": ["other"],
    "third-party supplier issue": ["other"],
    "catering to 100's count pack requirement": ["other"],

    "requirements related to complying with good manufacturing practices "
    "& demand increase for the drug": ["gmp_compliance", "demand_increase"],
    "shortage of an active ingredient, delay in shipping of the drug, "
    "and demand increase for the drug": ["active_ingredient", "shipping_delay", "demand_increase"],
    "demand increase for the drug and shortage of an active ingredient":
        ["demand_increase", "active_ingredient"],
    "demand increase for the drug and manufacturing delays":
        ["demand_increase", "manufacturing_delay"],
    "manufacturing interruptions and demand increase": ["manufacturing_delay", "demand_increase"],
    "delay in manufacturing/shipping of the drug": ["manufacturing_delay", "shipping_delay"],
    "regulatory delay, shortage of active ingredient": ["regulatory_delay", "active_ingredient"],
}


def normalize_reason(text: str) -> str:
    text = text.replace("’", "'").lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip(" .")


def reason_flags(reasons: pd.Series) -> pd.DataFrame:
    """One 0/1 column per category, plus reason_missing for blank or non-informative values."""
    normalized = reasons.map(normalize_reason)

    unmapped = set(normalized) - set(REASON_MAP) - NOT_A_REASON
    if unmapped:
        raise SystemExit("unmapped reason spellings -- add them to REASON_MAP:\n  "
                         + "\n  ".join(sorted(unmapped)))

    flags = pd.DataFrame(
        {f"reason_{category}": normalized.map(
            lambda reason, category=category: int(category in REASON_MAP.get(reason, [])))
         for category in REASON_CATEGORIES},
        index=reasons.index,
    )
    flags["reason_missing"] = normalized.isin(NOT_A_REASON).astype(int)
    return flags


# ---- NDCs ---------------------------------------------------------------------------------------

# Three digit groups split by hyphens, tolerating stray spaces ("0517 - 0901-25"). Not anchored on
# the word "NDC", so plural lists like "NDCs 0093-7027-56 and 0093-7027-90" are fully captured.
HYPHENATED_NDC = re.compile(r"(?<!\d)(\d{4,6})\s*-\s*(\d{2,4})\s*-\s*(\d{1,4})(?!\d)")

# A bare 10- or 11-digit run directly after "NDC", e.g. "(NDC 1672907901)".
UNHYPHENATED_NDC = re.compile(r"NDCs?[:#\s]*(\d{10,11})(?!\d)", re.IGNORECASE)

# A 10-digit NDC has one of three layouts. Each converts to 11 digits by left-padding the segment
# that is one digit short, which is the HIPAA standard NSDE uses.
TEN_DIGIT_LAYOUTS_TO_11 = {
    (4, 4, 2): lambda labeler, product, package: f"0{labeler}{product}{package}",
    (5, 3, 2): lambda labeler, product, package: f"{labeler}0{product}{package}",
    (5, 4, 1): lambda labeler, product, package: f"{labeler}{product}0{package}",
}


def to_ndc11(segments: tuple[str, ...]) -> tuple[str | None, str]:
    """Convert hyphenated NDC segments to 11 digits. Returns (ndc11 or None, how it was read).

    Ten digits with hyphens in non-standard places ("0781-13-9101") could belong to any of the
    three layouts, so they are left unresolved rather than guessed.
    """
    layout = tuple(len(segment) for segment in segments)
    if layout == (5, 4, 2):
        return "".join(segments), "standard_11"
    if layout in TEN_DIGIT_LAYOUTS_TO_11:
        return TEN_DIGIT_LAYOUTS_TO_11[layout](*segments), "standard_10"
    if sum(layout) == 10:
        return None, "ambiguous_10"
    return None, "invalid"


def extract_ndcs(presentation: str) -> list[dict]:
    found = []
    for match in HYPHENATED_NDC.finditer(presentation):
        ndc11, ndc_format = to_ndc11(match.groups())
        found.append({"ndc_raw": match.group(0), "ndc11": ndc11, "ndc_format": ndc_format})
    for match in UNHYPHENATED_NDC.finditer(presentation):
        digits = match.group(1)
        if len(digits) == 11:
            found.append({"ndc_raw": digits, "ndc11": digits, "ndc_format": "standard_11"})
        else:
            found.append({"ndc_raw": digits, "ndc11": None, "ndc_format": "ambiguous_10"})
    return found


def episode_ndc_table(episodes: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"episode_id": episode_id, **ndc}
        for episode_id, presentation in episodes["presentation"].items()
        for ndc in extract_ndcs(presentation)
    ]
    return pd.DataFrame(rows).drop_duplicates(["episode_id", "ndc_raw"]).reset_index(drop=True)


# ---- Episodes -----------------------------------------------------------------------------------

def standardize_statuses(statuses: str) -> str:
    standardized = {STATUS_SPELLINGS[status.lower()] for status in statuses.split("|") if status}
    return "|".join(sorted(standardized))


def clean_episodes(raw: pd.DataFrame) -> pd.DataFrame:
    episodes = raw.copy()
    episodes.index.name = "episode_id"
    for column in DATE_COLUMNS:
        episodes[column] = pd.to_datetime(episodes[column].replace("", None))
    episodes["duration_days"] = pd.to_numeric(episodes["duration_days"]).astype("Int64")
    for column in ["resolved", "left_censored"]:
        episodes[column] = episodes[column].astype(int)
    episodes["statuses"] = episodes["statuses"].map(standardize_statuses)
    return pd.concat([episodes, reason_flags(episodes["reason"])], axis=1)


def print_summary(episodes: pd.DataFrame, ndcs: pd.DataFrame) -> None:
    print(f"episodes: {len(episodes):,}")
    print("\nreason categories (episodes flagged):")
    for column in [f"reason_{category}" for category in REASON_CATEGORIES] + ["reason_missing"]:
        print(f"  {column:<30} {episodes[column].sum():>6,}")
    multi_reason = (episodes[[f"reason_{c}" for c in REASON_CATEGORIES]].sum(axis=1) > 1).sum()
    print(f"  {'(more than one reason)':<30} {multi_reason:>6,}")

    with_usable_ndc = ndcs.dropna(subset=["ndc11"])["episode_id"].nunique()
    print(f"\nNDCs found: {len(ndcs):,}  by format: {ndcs['ndc_format'].value_counts().to_dict()}")
    print(f"episodes with at least one usable 11-digit NDC: {with_usable_ndc:,} "
          f"({with_usable_ndc / len(episodes):.1%})")


def main():
    raw = pd.read_csv(EPISODES_PATH, dtype=str, keep_default_na=False)
    episodes = clean_episodes(raw)
    ndcs = episode_ndc_table(episodes)

    episodes.to_parquet(CLEAN_EPISODES_PATH)
    ndcs.to_parquet(EPISODE_NDCS_PATH, index=False)
    print_summary(episodes, ndcs)
    print(f"\nwrote {CLEAN_EPISODES_PATH}\nwrote {EPISODE_NDCS_PATH}")


if __name__ == "__main__":
    main()
