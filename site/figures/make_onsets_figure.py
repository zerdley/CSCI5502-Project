"""Generate the Introduction figure: reconstructed shortage onsets per year.

TODO:
When `src/` gains the reconstruction pipeline, replace ONSETS_BY_YEAR with a read
of the generated episode table so this figure regenerates from data.

Run:  uv run python site/figures/make_onsets_figure.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

OUT = "site/figures/shortage-onsets-by-year.png"

ONSETS_BY_YEAR = {
    2018: 128, 2019: 205, 2020: 162, 2021: 139, 2022: 182,
    2023: 230, 2024: 99, 2025: 138, 2026: 60,
}

INCOMPLETE = {2018, 2026}

LIVE_FILE_RANGE = (3, 17)

# --- Design tokens -----------------------------------------------------------
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
SERIES_1 = "#2a78d6"
NEUTRAL = "#8a8a83"

years = list(ONSETS_BY_YEAR)
values = [ONSETS_BY_YEAR[y] for y in years]

fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=200)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

# Live-file visibility band, drawn behind the bars.
ax.axhspan(
    LIVE_FILE_RANGE[0], LIVE_FILE_RANGE[1],
    color=NEUTRAL, alpha=0.30, zorder=1, linewidth=0,
)

for year, value in zip(years, values):
    incomplete = year in INCOMPLETE
    ax.bar(
        year, value,
        width=0.72,
        color=SERIES_1,
        alpha=0.35 if incomplete else 1.0,
        hatch="///" if incomplete else None,
        edgecolor=SERIES_1 if incomplete else "none",
        linewidth=1.1 if incomplete else 0,
        zorder=3,
    )
    ax.text(
        year, value + 5, str(value),
        ha="center", va="bottom",
        fontsize=10, color=TEXT_PRIMARY,
        zorder=4,
    )

ax.set_ylabel("Drug-level shortage onsets", fontsize=11, color=TEXT_SECONDARY)
ax.set_title(
    "Reconstructing the shortage record recovers an order of magnitude more onsets",
    fontsize=13, color=TEXT_PRIMARY, fontweight="bold", pad=16, loc="left",
)

ax.set_xticks(years)
ax.set_xticklabels(years, fontsize=10, color=TEXT_SECONDARY)
ax.tick_params(axis="y", labelsize=10, colors=TEXT_SECONDARY, length=0)
ax.tick_params(axis="x", length=0)
ax.set_ylim(0, 268)
ax.set_xlim(2017.4, 2026.6)

# Recessive grid and axes.
ax.yaxis.grid(True, color="#e4e4e0", linewidth=0.9, zorder=0)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color("#d6d6d1")

ax.legend(
    handles=[
        Patch(facecolor=SERIES_1, label="Reconstructed onsets (complete coverage)"),
        Patch(facecolor=SERIES_1, alpha=0.35, hatch="///", edgecolor=SERIES_1,
              label="Incomplete coverage (2018 left-censored, 2026 partial year)"),
        Patch(facecolor=NEUTRAL, alpha=0.30,
              label=f"FDA's live file: only {LIVE_FILE_RANGE[0]}–{LIVE_FILE_RANGE[1]} onsets/yr visible"),
    ],
    loc="upper left", frameon=False, fontsize=9.5,
    labelcolor=TEXT_SECONDARY, handlelength=1.6, handleheight=1.0,
)

fig.text(
    0.5, 0.012,
    "Source: authors' reconstruction from 102 Internet Archive captures of FDA's CDER "
    "drug shortage file, 2019-10-20 to 2026-07-20.",
    ha="center", fontsize=8.5, color=TEXT_SECONDARY,
)

fig.tight_layout(rect=(0, 0.035, 1, 1))
fig.savefig(OUT, facecolor=SURFACE, bbox_inches="tight")
print(f"wrote {OUT}")
