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

Raw and intermediate data are not committed to this repository (see `.gitignore`). Acquisition
scripts and instructions will be added to `src/` as the pipeline is developed.


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
