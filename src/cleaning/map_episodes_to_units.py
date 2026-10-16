"""Define the study's units (ingredient x route) and map each shortage episode to its units.

The unit list comes from the Orange Book, FDA's list of approved drugs. Unlike the live NDC
Directory it keeps discontinued products, which matters here: a list built from what is on the
market today would leave out exactly the drugs whose manufacturers exited.

Each episode reaches its unit through a chain of identifiers:
    episode NDC  --NSDE-->  application number  --Orange Book-->  (ingredient, route group)
NSDE is used for the first link because it keeps every package ever marketed, including delisted
ones. Biologics (not in the Orange Book) and unapproved drugs have no unit and are reported, not
mapped.

Known limit: units are defined by the Orange Book's ingredient text, which sometimes spells the
same product two ways (e.g. two multivitamin infusions whose vitamin lists are written
differently). Such a product becomes two units, so one shortage can count as two onsets. This
affects a handful of products and is not corrected here.

Input:  data/interim/shortage_episodes_clean.parquet, data/interim/shortage_episode_ndcs.parquet
        data/raw/products.txt (Orange Book), data/raw/other-nsde-*.json
Output: data/interim/units.parquet              one row per unit
        data/interim/episode_units.parquet      one row per (episode, unit) link
        data/interim/application_units.parquet  one row per (application number, unit) link

Usage: uv run python src/cleaning/map_episodes_to_units.py
"""

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"

ORANGE_BOOK_PATH = RAW_DATA_DIR / "products.txt"
NSDE_PATHS = sorted(RAW_DATA_DIR.glob("other-nsde-*-of-*.json"))
EPISODES_PATH = INTERIM_DATA_DIR / "shortage_episodes_clean.parquet"
EPISODE_NDCS_PATH = INTERIM_DATA_DIR / "shortage_episode_ndcs.parquet"
UNITS_PATH = INTERIM_DATA_DIR / "units.parquet"
EPISODE_UNITS_PATH = INTERIM_DATA_DIR / "episode_units.parquet"
APPLICATION_UNITS_PATH = INTERIM_DATA_DIR / "application_units.parquet"

# ---- Route groups -------------------------------------------------------------------------------

# Every route word the Orange Book uses, assigned to a group. A spelling missing from this table
# stops the script, so new routes get a human decision.
ROUTE_WORD_GROUPS = {
    **dict.fromkeys([
        "INJECTION", "INTRAVENOUS", "INTRAMUSCULAR", "SUBCUTANEOUS", "IM-IV", "INTRATHECAL",
        "INTRA-ARTERIAL", "EPIDURAL", "SPINAL", "INTRADERMAL", "INTRAPERITONEAL", "INTRAVITREAL",
        "INFILTRATION", "INTRA-ARTICULAR", "INTRAOSSEOUS", "ENDOTRACHEAL", "INTRACAVITARY",
        "INTRAOCULAR", "INTRACAMERAL", "INTRACRANIAL", "INTERSTITIAL", "INTRALYMPHATIC",
        "PERIARTICULAR", "INTRAPLEURAL", "PERFUSION", "CARDIAC",
    ], "injectable"),
    **dict.fromkeys([
        "ORAL", "ORAL-20", "ORAL-21", "ORAL-28", "ENTERAL", "SUBLINGUAL", "BUCCAL", "TRANSMUCOSAL",
    ], "oral"),
    **dict.fromkeys(["TOPICAL", "TRANSDERMAL", "IONTOPHORESIS"], "topical"),
    "OPHTHALMIC": "ophthalmic",
    "INHALATION": "inhalation",
    "NASAL": "nasal",
    "OTIC": "otic",
    "VAGINAL": "vaginal",
    "RECTAL": "rectal",
    **dict.fromkeys([
        "IRRIGATION", "N/A", "DENTAL", "IMPLANTATION", "FOR RX COMPOUNDING", "INTRAUTERINE",
        "INTRAVESICAL", "INTRAVESICULAR", "URETHRAL", "INTRA-ANAL", "INTRATRACHEAL", "URETERAL",
        "PERIODONTAL", "ENDOCERVICAL", "PYELOCALYCEAL", "BILIARY",
    ], "other"),
}

# A product listed under several routes ("INTRAMUSCULAR, INTRAVENOUS") takes the first group here
# that any of its routes belongs to. Injectable comes first because a product injected even some
# of the time must be made as a sterile injectable, where most US shortages occur. Oral comes
# before rectal because the "ORAL, RECTAL" products (lactulose, sodium polystyrene sulfonate,
# diatrizoate) are oral liquids that can also be given rectally.
ROUTE_GROUP_PRIORITY = [
    "injectable", "inhalation", "ophthalmic", "nasal", "otic", "vaginal", "oral", "rectal",
    "topical", "other",
]


def route_group(route: str) -> str:
    # Splitting on commas also splits "PERFUSION, CARDIAC", one route written with a comma; both
    # halves are in the table, so it still groups correctly.
    words = {word.strip() for word in route.split(",")}
    unknown = words - set(ROUTE_WORD_GROUPS)
    if unknown:
        raise SystemExit(f"unmapped Orange Book route words -- add them to ROUTE_WORD_GROUPS: "
                         f"{sorted(unknown)}")
    groups = {ROUTE_WORD_GROUPS[word] for word in words}
    return next(group for group in ROUTE_GROUP_PRIORITY if group in groups)


# ---- Sources ------------------------------------------------------------------------------------

def load_orange_book() -> pd.DataFrame:
    """Prescription and discontinued Orange Book products, with application numbers in NSDE's
    format (NDA018902, ANDA212174) and a route group."""
    products = pd.read_csv(ORANGE_BOOK_PATH, sep="~", dtype=str)
    products = products[products["Type"].isin(["RX", "DISCN"])]
    route = products["DF;Route"].str.split(";", n=1).str[1]
    return pd.DataFrame({
        "application": products["Appl_Type"].map({"N": "NDA", "A": "ANDA"}) + products["Appl_No"],
        "ingredient": products["Ingredient"],
        "route": route,
        "route_group": route.map(route_group),
    }).drop_duplicates()


def load_nsde() -> pd.DataFrame:
    rows = []
    for path in NSDE_PATHS:
        with open(path) as file:
            rows.extend(json.load(file)["results"])
    nsde = pd.DataFrame(rows)[["package_ndc11", "application_number_or_citation",
                               "marketing_category"]]
    return (nsde.dropna(subset=["package_ndc11"])
                .drop_duplicates("package_ndc11")
                .rename(columns={"package_ndc11": "ndc11",
                                 "application_number_or_citation": "application"}))


# ---- Units --------------------------------------------------------------------------------------

def build_units(orange_book: pd.DataFrame) -> pd.DataFrame:
    units = (orange_book[["ingredient", "route_group"]].drop_duplicates()
             .sort_values(["ingredient", "route_group"]).reset_index(drop=True))
    units.index.name = "unit_id"
    return units.reset_index()


# ---- Episode -> NDC -> application --------------------------------------------------------------

def ten_digit_readings(digits: str) -> list[str]:
    """The three 11-digit NDCs a bare 10-digit NDC could be, one per standard layout."""
    return [
        "0" + digits,                         # 4-4-2
        digits[:5] + "0" + digits[5:],        # 5-3-2
        digits[:9] + "0" + digits[9:],        # 5-4-1
    ]


def resolve_ambiguous_ndcs(ndcs: pd.DataFrame, nsde_ndcs: set[str]) -> pd.DataFrame:
    """Fill ndc11 for NDCs whose layout couldn't be read, when exactly one reading is in NSDE."""
    ndcs = ndcs.copy()
    ambiguous = ndcs["ndc_format"] == "ambiguous_10"
    for row in ndcs[ambiguous].itertuples():
        digits = "".join(character for character in row.ndc_raw if character.isdigit())
        readings_in_nsde = [ndc for ndc in ten_digit_readings(digits) if ndc in nsde_ndcs]
        if len(readings_in_nsde) == 1:
            ndcs.loc[row.Index, "ndc11"] = readings_in_nsde[0]
            ndcs.loc[row.Index, "ndc_format"] = "resolved_via_nsde"
    return ndcs


# ---- Application -> unit ------------------------------------------------------------------------

def ingredient_appears_in(ingredient: str, generic_name: str) -> bool:
    """True if every component of an Orange Book ingredient ("EPINEPHRINE; LIDOCAINE
    HYDROCHLORIDE") appears in FDA's shortage name. Only each component's first word is
    checked, since salts are written inconsistently ("Lidocaine HCl")."""
    generic_name = generic_name.upper()
    return all(component.split()[0] in generic_name for component in ingredient.split("; "))


def pick_unit_by_name(candidates: pd.DataFrame, generic_name: str) -> int | None:
    """Choose among several units on one application using the episode's shortage name.

    Of the candidates whose ingredients all appear in the name, the one with the most components
    wins, so "Lidocaine and Epinephrine Injection" maps to the combination, not plain lidocaine.
    Returns None if the name doesn't single out one unit.
    """
    named = candidates[candidates["ingredient"].map(
        lambda ingredient: ingredient_appears_in(ingredient, generic_name))]
    if named.empty:
        return None
    component_counts = named["ingredient"].str.count("; ") + 1
    most_specific = named[component_counts == component_counts.max()]
    unit_ids = most_specific["unit_id"].unique()
    return int(unit_ids[0]) if len(unit_ids) == 1 else None


def link_episodes_to_units(episodes: pd.DataFrame, episode_applications: pd.DataFrame,
                           application_units: pd.DataFrame) -> pd.DataFrame:
    candidates_by_application = dict(tuple(application_units.groupby("application")))
    links = []
    for row in episode_applications.itertuples():
        candidates = candidates_by_application.get(row.application)
        if candidates is None:
            continue
        if candidates["unit_id"].nunique() == 1:
            links.append((row.episode_id, int(candidates["unit_id"].iloc[0]), "application"))
        else:
            unit_id = pick_unit_by_name(candidates, episodes.at[row.episode_id, "generic"])
            if unit_id is not None:
                links.append((row.episode_id, unit_id, "application_and_name"))
    links = pd.DataFrame(links, columns=["episode_id", "unit_id", "match_method"])
    # One episode can list several NDCs that land on the same unit; keep the most direct match
    # ("application" sorts before "application_and_name").
    return (links.sort_values("match_method")
                 .drop_duplicates(["episode_id", "unit_id"])
                 .sort_values(["episode_id", "unit_id"])
                 .reset_index(drop=True))


# ---- Reporting ----------------------------------------------------------------------------------

def unmatched_reason(episode_id: int, ndcs: pd.DataFrame, episode_applications: pd.DataFrame,
                     orange_book_applications: set[str]) -> str:
    episode_ndcs = ndcs[ndcs["episode_id"] == episode_id]
    if episode_ndcs["ndc11"].isna().all():
        return "no usable NDC"
    applications = episode_applications[episode_applications["episode_id"] == episode_id]
    if applications.empty:
        return "NDC not in NSDE"
    if not any(application in orange_book_applications
               for application in applications["application"]):
        return "not in Orange Book: " + applications["marketing_category"].str.lower().iloc[0]
    return "several units on application, name didn't decide"


def print_summary(units, episodes, episode_units, ndcs, episode_applications,
                  application_units, orange_book) -> None:
    print(f"units: {len(units):,}  by route group: "
          f"{units['route_group'].value_counts().to_dict()}")

    print("\nOrange Book route -> route group:")
    for route, group in (orange_book[["route", "route_group"]].drop_duplicates()
                         .sort_values(["route_group", "route"]).itertuples(index=False)):
        print(f"  {group:<12} {route}")

    resolved = (ndcs["ndc_format"] == "resolved_via_nsde").sum()
    print(f"\nambiguous NDCs resolved via NSDE: {resolved} "
          f"of {resolved + (ndcs['ndc_format'] == 'ambiguous_10').sum()}")

    mapped = episode_units["episode_id"].nunique()
    print(f"\nepisodes mapped to a unit: {mapped:,} of {len(episodes):,} "
          f"({mapped / len(episodes):.1%})")
    print(f"  by match method: {episode_units['match_method'].value_counts().to_dict()}")
    print(f"  mapped to more than one unit: "
          f"{(episode_units.groupby('episode_id').size() > 1).sum()}")
    print(f"  distinct units with at least one episode: {episode_units['unit_id'].nunique():,}")

    unmatched = episodes.index.difference(episode_units["episode_id"])
    orange_book_applications = set(application_units["application"])
    reasons = pd.Series([unmatched_reason(episode_id, ndcs, episode_applications,
                                          orange_book_applications) for episode_id in unmatched])
    print("\nunmatched episodes by reason:")
    for reason, count in reasons.value_counts().items():
        print(f"  {count:>5}  {reason}")


def main():
    episodes = pd.read_parquet(EPISODES_PATH)
    orange_book = load_orange_book()
    nsde = load_nsde()

    units = build_units(orange_book)
    application_units = orange_book.merge(units, on=["ingredient", "route_group"])[
        ["application", "unit_id", "ingredient"]].drop_duplicates()

    ndcs = resolve_ambiguous_ndcs(pd.read_parquet(EPISODE_NDCS_PATH), set(nsde["ndc11"]))
    episode_applications = (ndcs.dropna(subset=["ndc11"])
                                .merge(nsde, on="ndc11")
                                [["episode_id", "application", "marketing_category"]]
                                .drop_duplicates(["episode_id", "application"]))
    episode_units = link_episodes_to_units(episodes, episode_applications, application_units)

    units.to_parquet(UNITS_PATH, index=False)
    episode_units.to_parquet(EPISODE_UNITS_PATH, index=False)
    (application_units[["application", "unit_id"]].drop_duplicates()
     .to_parquet(APPLICATION_UNITS_PATH, index=False))
    print_summary(units, episodes, episode_units, ndcs, episode_applications,
                  application_units, orange_book)
    print(f"\nwrote {UNITS_PATH}\nwrote {EPISODE_UNITS_PATH}\nwrote {APPLICATION_UNITS_PATH}")


if __name__ == "__main__":
    main()
