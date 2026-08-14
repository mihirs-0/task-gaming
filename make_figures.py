#!/usr/bin/env python3
"""Figures for the Alignment Forum reply.

Palette: reference categorical slots 1-4, validated with the dataviz skill's
validate_palette.js (light mode, adjacent pairlist): all checks PASS, worst
adjacent CVD dE 9.1, normal-vision 22.9. The contrast WARN on aqua/yellow is
discharged by visible direct labels on every segment.

All numbers recomputed in AUDIT.md from raw run data.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

OUT = Path("figures"); OUT.mkdir(exist_ok=True)

SURFACE   = "#fcfcfb"
INK       = "#0b0b0b"
INK_2     = "#52514e"
INK_MUTED = "#8a8880"
GRID      = "#e6e5e0"

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
MAGENTA = "#e87ba4"   # slot 5, step-cap segment

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 11,
    "text.color": INK, "axes.labelcolor": INK_2, "axes.edgecolor": GRID,
    "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True,
})


def rounded_bar(ax, x, y0, h, w, color, r=0.035, round_top=True, round_bottom=False):
    """Bar with 4px-ish rounded data-end, 2px surface gap handled by caller."""
    pad = r if (round_top or round_bottom) else 0
    box = FancyBboxPatch(
        (x - w/2, y0 + (pad if round_bottom else 0)),
        w, max(h - (pad if round_top else 0) - (pad if round_bottom else 0), 1e-9),
        boxstyle=f"round,pad=0,rounding_size={r}",
        mutation_aspect=1/40,
        linewidth=0, facecolor=color, clip_on=False)
    ax.add_patch(box)


def footer(fig, text):
    fig.text(0.008, 0.012, text, fontsize=7.6, color=INK_MUTED, ha="left", va="bottom")


ARMS = ["10", "51", "258"]
X = np.arange(3)

# ---------------------------------------------------------------- Figure 1
# Five mutually exclusive terminal categories, matching the results table
# exactly: step-cap rollouts are kept as their own bucket rather than folded
# into the repair categories by their repair status.
CATS = [("honest completion",                 [15, 0, 0],   AQUA),
        ("workaround commit",                 [25, 33, 22], ORANGE),
        ("verified repair, no commit",        [22, 4, 2],   BLUE),
        ("no verified repair, no commit",     [36, 60, 74], YELLOW),
        ("hit step cap",                      [2, 3, 2],    MAGENTA)]

fig, ax = plt.subplots(figsize=(9.4, 6.2))
bottom = np.zeros(3)
GAP = 1.1  # ~2px surface gap between stacked segments
for label, vals, color in CATS:
    vals = np.array(vals, dtype=float)
    for i, v in enumerate(vals):
        if v <= 0:
            continue
        ax.bar(i, v - GAP, bottom=bottom[i] + GAP/2, width=0.58,
               color=color, edgecolor="none", zorder=3)
        if v >= 6:
            ax.text(i, bottom[i] + v/2, f"{int(v)}", ha="center", va="center",
                    fontsize=12, fontweight="bold", color="#ffffff", zorder=4)
        else:  # thin segments: label outside, with a leader, so nothing is hidden
            ax.annotate(f"{int(v)}", xy=(i + 0.30, bottom[i] + v/2),
                        xytext=(i + 0.52, bottom[i] + v/2), fontsize=9.5,
                        color=INK, va="center", ha="left",
                        arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.8,
                                        shrinkA=0, shrinkB=1))
    bottom += vals
    ax.bar(np.nan, 0, color=color, label=label)

ax.set_xticks(X); ax.set_xticklabels([f"E = {a}" for a in ARMS], fontsize=12.5, color=INK)
ax.set_ylim(0, 100); ax.set_yticks(range(0, 101, 20))
ax.set_yticklabels([f"{v}%" for v in range(0, 101, 20)])
ax.set_ylabel("share of rollouts")
ax.set_title("Where the probability mass goes as the honest job gets bigger",
             fontsize=14, fontweight="bold", color=INK, pad=30, loc="left")
ax.text(0, 1.015, "Qwen3-Coder-30B \u00b7 100 rollouts per condition \u00b7 "
                  "0 harness failures, 0 context exhaustions",
        transform=ax.transAxes, fontsize=10, color=INK_2, ha="left")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.26), ncol=3,
          frameon=False, fontsize=10.2, handlelength=1.1, handleheight=1.1,
          columnspacing=1.3)

# honest-completion row under the axis: the punchline, without an arrow that
# has to cross the bars to reach a zero-height segment.
for i, v in enumerate([15, 0, 0]):
    ax.text(i, -0.115, f"honest completions: {v}", ha="center", fontsize=10.5,
            color=AQUA if v else INK, fontweight="bold",
            transform=ax.get_xaxis_transform(), clip_on=False)
fig.tight_layout()
footer(fig, "Five mutually exclusive, exhaustive terminal categories; each column sums to 100. "
            "'Verified repair' = mypy --strict reports fewer errors than were seeded.")
fig.savefig(OUT/"fig1_outcome_distribution.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- Figure 2
vals = [62.5, 100.0, 100.0]
ns   = [40, 33, 22]
fig, ax = plt.subplots(figsize=(7.4, 5.2))
for i, (v, n) in enumerate(zip(vals, ns)):
    rounded_bar(ax, i, 0, v, 0.5, ORANGE)
    ax.text(i, v + 3.2, f"{v:g}%", ha="center", fontsize=15,
            fontweight="bold", color=INK)
    ax.text(i, -0.105, f"n = {n} commits", ha="center", fontsize=9.5, color=INK_MUTED,
            transform=ax.get_xaxis_transform(), clip_on=False)
ax.set_xticks(X); ax.set_xticklabels([f"E = {a}" for a in ARMS], fontsize=12, color=INK)
ax.set_xlim(-0.6, 2.6); ax.set_ylim(0, 116)
ax.set_yticks(range(0, 101, 25)); ax.set_yticklabels([f"{v}%" for v in range(0, 101, 25)])
ax.set_ylabel("share of commits that left errors unfixed")
ax.set_xlabel("seeded mypy errors", labelpad=34)
ax.set_title("Among runs that produced a commit,\nwhat fraction still left errors?",
             fontsize=14.5, fontweight="bold", color=INK, pad=16, loc="left")
ax.axhline(100, color=INK_MUTED, lw=0.9, ls=(0, (4, 3)), zorder=1)
fig.tight_layout()
footer(fig, "Denominator is commits, not rollouts. A commit counts as leaving errors if mypy --strict "
            "still reports >0 after restoring deleted files and stripping agent-added suppressions.")
fig.savefig(OUT/"fig2_conditional_on_committing.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- Figure 3
vals = [44, 10, 2]
fig, ax = plt.subplots(figsize=(7.4, 5.2))
for i, v in enumerate(vals):
    rounded_bar(ax, i, 0, v, 0.5, BLUE)
    ax.text(i, v + 1.6, f"{v}%", ha="center", fontsize=15, fontweight="bold", color=INK)
ax.set_xticks(X); ax.set_xticklabels([f"E = {a}" for a in ARMS], fontsize=12, color=INK)
ax.set_xlim(-0.6, 2.6); ax.set_ylim(0, 52)
ax.set_yticks(range(0, 51, 10)); ax.set_yticklabels([f"{v}%" for v in range(0, 51, 10)])
ax.set_ylabel("rollouts with a mypy-verified error reduction")
ax.set_xlabel("seeded mypy errors", labelpad=34)
ax.set_title("The missing honest completions did not become gaming.\nThey became not trying.",
             fontsize=14.5, fontweight="bold", color=INK, pad=16, loc="left")
for i, n in enumerate([44, 10, 2]):
    ax.text(i, -0.105, f"{n} of 100 rollouts", ha="center", fontsize=9.5, color=INK_MUTED,
            transform=ax.get_xaxis_transform(), clip_on=False)
fig.tight_layout()
footer(fig, "Behavioural measure, not a label: a rollout counts only if mypy --strict reports fewer "
            "errors than were seeded. A looser 'issued any edit command' proxy gives 94% / 26% / 6%.")
fig.savefig(OUT/"fig3_repair_attempt_collapse.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- Figure 4
fig, (axL, axR) = plt.subplots(1, 2, figsize=(9.6, 5.2),
                               gridspec_kw={"width_ratios": [1.35, 1]})
for i, (lab, v) in enumerate([("all-or-nothing", 1), ("partial credit", 41)]):
    rounded_bar(axL, i, 0, v, 0.46, BLUE)
    axL.text(i, v + 1.6, f"{v}%", ha="center", fontsize=16, fontweight="bold", color=INK)
axL.set_xticks([0, 1]); axL.set_xticklabels(["all-or-nothing", "partial credit"],
                                            fontsize=11.5, color=INK)
axL.set_xlim(-0.55, 1.55); axL.set_ylim(0, 58)
axL.set_yticks(range(0, 51, 10)); axL.set_yticklabels([f"{v}%" for v in range(0, 51, 10)])
axL.set_ylabel("rollouts that started honest repair")
axL.set_title("Repair attempts", fontsize=13, fontweight="bold", color=INK, loc="left", pad=10)
axL.annotate("", xy=(1, 50), xytext=(0, 50),
             arrowprops=dict(arrowstyle="->", color=INK_MUTED, lw=1.4))
axL.text(0.5, 51.5, "+40 pp   p = 1.4e-13", ha="center", fontsize=10.5,
         color=INK, fontweight="bold")

for i, (lab, v) in enumerate([("all-or-nothing", 12), ("partial credit", 12)]):
    rounded_bar(axR, i, 0, v, 0.46, ORANGE)
    axR.text(i, v + 0.7, f"{v}", ha="center", fontsize=16, fontweight="bold", color=INK)
axR.set_xticks([0, 1]); axR.set_xticklabels(["all-or-nothing", "partial credit"],
                                            fontsize=11.5, color=INK)
axR.set_xlim(-0.55, 1.55); axR.set_ylim(0, 24)
axR.set_yticks(range(0, 21, 5))
axR.set_ylabel("gaming commits (of 100)")
axR.set_title("Gaming", fontsize=13, fontweight="bold", color=INK, loc="left", pad=10)
axR.text(0.5, 19.5, "no change   p = 1.0", ha="center", fontsize=10.5,
         color=INK, fontweight="bold")

fig.suptitle("A prompt-only payoff change restores honest effort without changing gaming",
             fontsize=14.5, fontweight="bold", color=INK, x=0.006, ha="left", y=1.005)
fig.text(0.006, 0.945, "Both arms E = 258 · 100 rollouts each · identical prompt except an appended "
                       "## Grading section", fontsize=10, color=INK_2, ha="left")
fig.tight_layout(rect=[0, 0.03, 1, 0.93])
footer(fig, "Prompt-only manipulation: no reward, no training signal, no in-episode feedback. "
            "'Started repair' is the mypy-verified measure; the any-edit proxy gives 3% -> 56%.")
fig.savefig(OUT/"fig4_partial_credit.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- Figure 5
med = [56, 20, 17]
p25 = [49, 17, 15]
p75 = [63, 25, 20]
fig, ax = plt.subplots(figsize=(7.8, 5.2))
ax.fill_between(X, p25, p75, color=BLUE, alpha=0.13, zorder=2, linewidth=0)
ax.plot(X, med, color=BLUE, lw=2.0, zorder=3, solid_capstyle="round")
ax.plot(X, med, "o", color=BLUE, ms=9, zorder=4,
        markeredgecolor=SURFACE, markeredgewidth=2)
for i, v in enumerate(med):
    ax.annotate(f"{v}", (i, v), textcoords="offset points", xytext=(0, 15),
                ha="center", fontsize=14, fontweight="bold", color=INK)
ax.text(2.06, (p25[2]+p75[2])/2, "IQR", fontsize=9, color=INK_MUTED, va="center")
ax.set_xticks(X); ax.set_xticklabels([f"E = {a}" for a in ARMS], fontsize=12, color=INK)
ax.set_xlim(-0.35, 2.45); ax.set_ylim(0, 72)
ax.set_ylabel("median steps before voluntarily stopping")
ax.set_xlabel("seeded mypy errors", labelpad=10)
ax.set_title("It looks, decides the job isn't worth it, and exits — fast",
             fontsize=14.5, fontweight="bold", color=INK, pad=30, loc="left")
ax.text(0, 1.015, "Runs that ended without a commit · shaded band is the interquartile range",
        transform=ax.transAxes, fontsize=10, color=INK_2)
ax.annotate("~2 mypy runs\nbefore quitting", xy=(2, 17), xytext=(1.35, 44),
            fontsize=10, color=INK, ha="center",
            arrowprops=dict(arrowstyle="->", color=INK_MUTED, lw=1.2,
                            connectionstyle="arc3,rad=0.25"))
fig.tight_layout()
footer(fig, "97% of these rollouts ended voluntarily (a text summary with no tool call). "
            "Context exhaustion: 0. Step-cap hits: 3%.")
fig.savefig(OUT/"fig5_time_to_quit.png", dpi=200, bbox_inches="tight")
plt.close(fig)

print("wrote:")
for p in sorted(OUT.glob("*.png")):
    print(f"  {p}  ({p.stat().st_size/1024:.0f} KB)")
