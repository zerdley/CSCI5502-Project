# Predicting US Drug Shortages from Federal Supply-Side Signals

**CSCI 5502 — Data Mining — Fall 2026 — University of Colorado Boulder**

| | |
|---|---|
| **Project website** | https://zerdley.github.io/CSCI5502-Project/ |
| **Repository** | https://github.com/zerdley/CSCI5502-Project |

## Team

Zach Erdley \
Dylan Hudson \
Mar Lonsway 

## Project Goal

Drug shortages are a persistent problem for hospitals, pharmacies, and patients, affecting
everything from over-the-counter medications to critical preparations for surgery and emergency
care. Warning times vary widely and unpredictably, which makes stockpiling and preparation both
difficult and expensive — Vizient estimates shortages cost hospitals roughly $900 million per
year in labor expenses alone.

This project asks whether shortages can be anticipated from public federal data. We combine FDA
shortage history, product lifecycle records, approval data, and Medicare utilization to study
which drugs enter shortage and whether supply-side withdrawal is measurable *before* a shortage
is formally declared.

## Research Questions

1. How predictable is shortage onset?
2. What distinguishes drugs that go into shortage?
3. Do manufacturers exit before a shortage is declared?
4. Does predictability hold as the causes of shortage change?

## Data Sources

All sources are US federal public-domain data available as bulk downloads without authentication.
Total download is approximately 100 MB.

| Dataset | Provider | Access | Role |
|---|---|---|---|
| Drug Shortages (current) | openFDA | `download.open.fda.gov/drug/shortages/` | Current shortage state, NDC keys |
| Archived CDER shortage CSVs | Internet Archive | `web.archive.org` → `accessdata.fda.gov` | Historical labels: start and end dates |
| NSDE (product lifecycle) | openFDA | `download.open.fda.gov/other/nsde/` | Supply-side panel; retains delisted products |
| NDC Directory | openFDA | `download.open.fda.gov/drug/ndc/` | Product master, route/form features |
| Drug Enforcement (recalls) | openFDA | `download.open.fda.gov/drug/enforcement/` | Recall history |
| Orange Book | FDA | `fda.gov/media/76860/download` | Approval type, ANDA counts |
| Medicare Part B / Part D Spending | CMS | `data.cms.gov` | Demand, price trend, manufacturer counts |

Licensing: openFDA and CDER data are public domain (CC0) and may be freely redistributed.
ASHP / University of Utah shortage bulletins are copyrighted for personal use only and are **not**
used or redistributed in this project.

### Data Acquisition

Raw and intermediate data are not committed to this repository (see `.gitignore`). To rebuild
them, run from the repository root:

```bash
uv run python src/acquisition/download_bulk_files.py         # ~100 MB of bulk files -> data/raw/
uv run python src/acquisition/fetch_archived_shortages.py    # ~120 captures, ~12 min -> data/raw/cder_archive/
uv run python src/acquisition/stitch_archived_shortages.py   # -> data/interim/shortage_episodes.csv
uv run python src/cleaning/clean_shortage_episodes.py        # -> data/interim/*.parquet
uv run python src/cleaning/map_episodes_to_units.py          # -> data/interim/units.parquet, episode_units.parquet
uv run python src/panel/build_unit_year_panel.py             # -> data/processed/unit_year_panel.parquet
```

The archive fetch is throttled to one request every 6 seconds because the Internet Archive rate
limits aggressively. It skips captures already on disk, so it is safe to re-run after an
interruption.

The stitch step turns point-in-time snapshots into one row per shortage episode. FDA purges
resolved shortages from its live list after about six months, so resolution dates survive only in
archived captures. Short episodes that open and close between captures are not observed.


## Repository Structure

```
.
├── src/            # Analysis and data-acquisition code
├── notebooks/      # Exploratory notebooks
├── data/           # Local only; not committed
│   ├── raw/        # Bulk downloads as retrieved
│   ├── interim/    # Intermediate artifacts
│   └── processed/  # Analysis-ready tables
├── report/         # Milestone writeups and submitted documents
└── milestones/     # Instructor-provided milestone specifications
```

## Development Setup

This project uses [uv](https://docs.astral.sh/uv/) for Python environment management. It installs
the pinned Python version automatically; no separate Python install is needed.

```bash
uv sync                   
uv run python <script>
```

## Milestones/Roadmap

| Milestone | Focus | Status |
|---|---|---|
| **M0** | Proposal: problem, data sources, feasibility and ethics | ✅ Approved |
| **M1** | Project framing, research questions, team, repository, website | 🚧 In progress |
| **M2** | _TBD_ | — |
| **M3** | _TBD_ | — |
| **M4** | _TBD_ | — |
