# Predicting US Drug Shortages from Federal Supply-Side Signals

**CSCI 5502 — Data Mining — Fall 2026 — University of Colorado Boulder**

| | |
|---|---|
| **Project website** | _TBD — GitHub Pages URL once published_ |
| **Repository** | https://github.com/zerdley/CSCI5502-Project |

## Team

| Member | Initial Responsibilities |
|---|---|
| Zach Erdley | _TBD — confirm with team_ |
| Dylan Hudson | _TBD — confirm with team_ |
| Mar Lonsway | _TBD — confirm with team_ |

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

The unit of analysis is **active ingredient &times; route of administration** (2,897 approved
prescription units). Validation is temporal: train on earlier years, test on later ones.

## Research Questions

1. **(Relationship)** Do package-level NDC delistings increase in the months preceding a declared
   shortage, and what is the typical lead time?
2. **(Comparative / explanatory)** Which product characteristics — route and dosage form, generic
   competition, labeler and applicant counts, Medicare spending and claim volume, and recall
   history — distinguish ingredient &times; route units that enter shortage from those that do not?
3. **(Predictive)** Using only information available at time *t*, how well can ingredient &times; route
   units be ranked by probability of entering shortage within the next 6 and 12 months?
4. **(Robustness)** Does predictive performance vary across shortage-cause regimes — periods
   dominated by manufacturing and quality problems versus periods dominated by demand increases?

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

**Licensing:** openFDA and CDER data are public domain (CC0) and may be freely redistributed.
ASHP / University of Utah shortage bulletins are copyrighted for personal use only and are **not**
used or redistributed in this project.

### Data Acquisition

Raw and intermediate data are **not committed** to this repository (see `.gitignore`). Acquisition
scripts and instructions will be added to `src/` as the pipeline stabilizes.

Two access notes that matter in practice:

- Use the **bulk ZIP files**, not the openFDA API — anonymous API access is capped at 1,000
  requests/day.
- `accessdata.fda.gov` sits behind bot detection and requires a browser `User-Agent` header;
  without one it returns a small error page disguised as a successful download.

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
uv sync                    # create the environment from uv.lock
uv run python <script>
```

## Milestone Roadmap

| Milestone | Focus | Status |
|---|---|---|
| **M0** | Proposal: problem, data sources, feasibility and ethics | ✅ Approved |
| **M1** | Project framing, research questions, team, repository, website | 🚧 In progress |
| **M2** | _TBD_ | — |
| **M3** | _TBD_ | — |
| **M4** | _TBD_ | — |

## Contributing

- Do not commit data files, credentials, API keys, or personal data.
- Raw data stays local; document how to regenerate it instead.
