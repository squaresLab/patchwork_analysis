import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
# want to draw aggregate occupancy scarf for each condition permutation
# and individual scarf plots for each participant-task

# -----------------------------
# Config
# -----------------------------
INPUT_CSV = "scarf_plot_input.csv"
OUT_COMBINED = "scarf_plot_by_condition.png"
XMAX_MIN = 25.0

CONDITION_ORDER = ["control", "overfitting", "correct"]
AOI_ORDER = [
    "Patch",
    "Browser",
    "Test and Runtime Feedback",
    "Tests",
    "Source Code",
    "Other",
]

AOI_COLORS = {
    "Patch": "#d7301f",
    "Browser": "#3182bd",
    "Test and Runtime Feedback": "#31a354",
    "Tests": "#fd8d3c",
    "Source Code": "#756bb1",
    "Other": "#bdbdbd",
}

# -----------------------------
# Data prep
# -----------------------------
def load_scarf_data(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    required = [
        "PID",
        "task_no",
        "condition",
        "start_min",
        "end_min",
        "scarf_aoi",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df["condition"] = pd.Categorical(
        df["condition"], categories=CONDITION_ORDER, ordered=True
    )
    df["trial_id"] = df["PID"].astype(str) + "_t" + df["task_no"].astype(str)

    # Normalize AOI bucket in case unknown labels sneak in
    df["scarf_aoi"] = df["scarf_aoi"].where(
        df["scarf_aoi"].isin(AOI_ORDER), "Other"
    )
    return df


def build_trial_order(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df[["trial_id", "PID", "task_no", "condition"]]
        .drop_duplicates()
        .sort_values(["condition", "PID", "task_no"])
        .reset_index(drop=True)
    )


def compute_draw_window(start_min: float, end_min: float, xmax: float):
    draw_start = float(start_min)
    draw_end = min(float(end_min), xmax)
    if draw_start >= xmax:
        return None
    if draw_end <= draw_start:
        return None
    return draw_start, draw_end


# -----------------------------
# Plot helpers
# -----------------------------
def add_legend(ax):
    handles = [Patch(facecolor=AOI_COLORS[a], label=a) for a in AOI_ORDER]
    ax.legend(handles=handles, loc="upper right", ncol=2, frameon=False)


def draw_condition_separators(ax, trial_order: pd.DataFrame):
    counts = (
        trial_order.groupby("condition", observed=False)
        .size()
        .reindex(CONDITION_ORDER, fill_value=0)
    )

    offset = 0
    for cond in CONDITION_ORDER:
        n = int(counts.loc[cond])
        if n > 0:
            ax.text(-0.7, offset + (n - 1) / 2, cond, va="center", ha="right",
                    fontsize=10, fontweight="bold")
            offset += n
            ax.axhline(offset - 0.5, color="#dddddd", linewidth=1)


def draw_scarf(ax, df: pd.DataFrame, trial_order: pd.DataFrame, xmax: float, title: str):
    y_lookup = {tid: i for i, tid in enumerate(trial_order["trial_id"])}
    bar_h = 0.8

    for row in df.itertuples(index=False):
        y = y_lookup.get(row.trial_id)
        if y is None:
            continue

        if row.scarf_aoi == "Missing":
            continue

        window = compute_draw_window(row.start_min, row.end_min, xmax)
        if window is None:
            continue

        draw_start, draw_end = window
        width = draw_end - draw_start
        color = AOI_COLORS.get(row.scarf_aoi, AOI_COLORS["Other"])

        ax.broken_barh(
            [(draw_start, width)],
            (y - bar_h / 2, bar_h),
            facecolors=color,
            edgecolors="none",
        )

    ax.set_xlim(0, xmax)
    ax.set_xlabel("Minutes from task start")
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.2)


# -----------------------------
# Public plotting functions
# -----------------------------
def plot_combined_by_condition(df: pd.DataFrame, output_path: str, xmax: float):
    print("Preparing combined scarf plot data...", flush=True)
    trial_order = build_trial_order(df)
    fig_h = max(6, 0.22 * len(trial_order))
    fig, ax = plt.subplots(figsize=(16, fig_h))

    print(f"Drawing combined scarf plot for {len(trial_order)} trials...", flush=True)
    draw_scarf(
        ax=ax,
        df=df,
        trial_order=trial_order,
        xmax=xmax,
        title="Fixation Scarf Plot by Condition",
    )

    ax.set_yticks(range(len(trial_order)))
    ax.set_yticklabels(trial_order["trial_id"], fontsize=7)

    draw_condition_separators(ax, trial_order)
    print("Adding legend...", flush=True)
    add_legend(ax)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close(fig)


def main():
    df = load_scarf_data(INPUT_CSV)
    plot_combined_by_condition(df, OUT_COMBINED, XMAX_MIN)
    print("Scarf plots generated.")


if __name__ == "__main__":
    main()