from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
SCARF_INPUT_CSV = BASE_DIR / "scarf_plot_input.csv"

AOI_ORDER = [
	"Patch",
	"Browser",
	"Test and Runtime Feedback",
	"Tests",
	"Source Code",
]

N_PERMUTATIONS = 10_000
RNG_SEED = 42
ALPHA = 0.05


def collapse_sequence(seq: list[str]) -> list[str]:
	"""Remove Missing/unknown AOIs and merge consecutive identical AOIs."""
	out: list[str] = []
	prev = object()
	for item in seq:
		if item not in AOI_ORDER:
			continue
		if item != prev:
			out.append(item)
			prev = item
	return out


def load_data() -> pd.DataFrame:
	scarf_df = pd.read_csv(SCARF_INPUT_CSV)
	scarf_df["PID"] = scarf_df["PID"].astype(str)
	scarf_df["task_no"] = scarf_df["task_no"].astype(int)
	scarf_df["scarf_aoi"] = scarf_df["scarf_aoi"].fillna("Missing")
	scarf_df["scarf_aoi"] = scarf_df["scarf_aoi"].where(
		scarf_df["scarf_aoi"].isin(AOI_ORDER), "Missing"
	)
	sort_cols = ["PID", "task_no", "start_min"]
	if "fixation_group_id" in scarf_df.columns:
		sort_cols.append("fixation_group_id")
	return scarf_df.sort_values(sort_cols)


def participant_condition_props(df: pd.DataFrame) -> pd.DataFrame:
	"""
	For each (PID, condition) trial, compute the proportion of every observed
	(from_aoi, to_aoi) transition out of all transitions in that trial.

	The unit of analysis is a participant × condition cell, not an event.
	Participants with no valid AOI sequence in a condition are simply absent.
	"""
	rows: list[dict] = []
	for (pid, _task_no, condition), trial_df in df.groupby(
		["PID", "task_no", "condition"], sort=False
	):
		seq = collapse_sequence(trial_df["scarf_aoi"].tolist())
		counts: dict[tuple[str, str], int] = {}
		for src, dst in zip(seq[:-1], seq[1:]):
			counts[(src, dst)] = counts.get((src, dst), 0) + 1
		total = sum(counts.values())
		if total == 0:
			continue
		for (src, dst), count in counts.items():
			rows.append(
				{
					"PID": pid,
					"condition": condition,
					"from_aoi": src,
					"to_aoi": dst,
					"proportion": count / total,
				}
			)
	return pd.DataFrame(rows, columns=["PID", "condition", "from_aoi", "to_aoi", "proportion"])


def sign_flip_permutation_test(
	diffs: np.ndarray,
	n_perm: int = N_PERMUTATIONS,
	rng: np.random.Generator | None = None,
) -> float:
	"""
	One-sample sign-flip permutation test (paired equivalent).

	Under H0, the sign of each within-participant difference is exchangeable.
	We randomly flip signs and measure how often |mean| >= |observed mean|.
	Returns a two-sided p-value.

	Minimum achievable p-value = 1 / n_perm.
	"""
	if rng is None:
		rng = np.random.default_rng(RNG_SEED)
	obs = float(np.abs(np.mean(diffs)))
	n = len(diffs)
	# Vectorised: (n_perm × n) sign matrix
	signs = rng.choice(np.array([-1.0, 1.0]), size=(n_perm, n))
	perm_means = np.abs((signs * diffs[np.newaxis, :]).mean(axis=1))
	return float((perm_means >= obs).mean())


def bh_reject(pvalues: np.ndarray, alpha: float = ALPHA) -> np.ndarray:
	"""
	Benjamini-Hochberg FDR correction.
	Returns a boolean mask (same order as input) indicating rejection.
	"""
	n = len(pvalues)
	order = np.argsort(pvalues)
	sorted_p = pvalues[order]
	thresholds = (np.arange(1, n + 1) / n) * alpha
	below = sorted_p <= thresholds
	mask = np.zeros(n, dtype=bool)
	if below.any():
		cutoff = int(np.where(below)[0].max())
		mask[order[: cutoff + 1]] = True
	return mask


def main() -> None:
	df = load_data()
	props = participant_condition_props(df)

	# ── Determine eligible participants ───────────────────────────────────────
	# A participant is eligible iff they have valid gaze data in the control
	# condition AND in at least one patch condition (correct or overfitting).
	# This excludes e.g. P1 whose task-1 (control) gaze was dropped.
	pids_ctrl = set(props[props["condition"] == "control"]["PID"].unique())
	pids_corr = set(props[props["condition"] == "correct"]["PID"].unique())
	pids_over = set(props[props["condition"] == "overfitting"]["PID"].unique())
	eligible_pids = sorted(pids_ctrl & (pids_corr | pids_over))

	print("=" * 70)
	print("PARTICIPANT-LEVEL TRANSITION ANALYSIS")
	print("Had-Patch (correct + overfitting, averaged per participant) vs. Control")
	print(f"Eligible participants (control + at least one patch condition): {len(eligible_pids)}")
	print(f"Test: one-sample sign-flip permutation ({N_PERMUTATIONS:,} permutations)")
	print(f"Multiple comparisons: Benjamini-Hochberg FDR (α = {ALPHA})")
	print("Unit of analysis: participant-level mean transition proportion")
	print("(pooled event counts are reported as descriptive only)")
	print("=" * 70)

	# ── Exclude Patch AOI from transitions ────────────────────────────────────
	props_no_patch = props[
		(props["from_aoi"] != "Patch") & (props["to_aoi"] != "Patch")
	].copy()

	transitions = (
		props_no_patch[["from_aoi", "to_aoi"]]
		.drop_duplicates()
		.reset_index(drop=True)
	)

	rng = np.random.default_rng(RNG_SEED)
	results: list[dict] = []

	for _, trow in transitions.iterrows():
		from_aoi, to_aoi = trow["from_aoi"], trow["to_aoi"]
		t_df = props_no_patch[
			(props_no_patch["from_aoi"] == from_aoi) & (props_no_patch["to_aoi"] == to_aoi)
		]

		diffs: list[float] = []
		had_patch_vals: list[float] = []
		ctrl_vals: list[float] = []

		for pid in eligible_pids:
			p = t_df[t_df["PID"] == pid]
			ctrl_prop = float(p[p["condition"] == "control"]["proportion"].sum())

			# Average across whichever patch conditions this participant has gaze for
			patch_props = []
			if pid in pids_corr:
				patch_props.append(
					float(p[p["condition"] == "correct"]["proportion"].sum())
				)
			if pid in pids_over:
				patch_props.append(
					float(p[p["condition"] == "overfitting"]["proportion"].sum())
				)

			had_patch_prop = float(np.mean(patch_props))
			diffs.append(had_patch_prop - ctrl_prop)
			had_patch_vals.append(had_patch_prop)
			ctrl_vals.append(ctrl_prop)

		diffs_arr = np.array(diffs)

		# Skip transitions where every participant has identical proportions
		# (no information — typically self-transitions eliminated by collapse_sequence)
		if np.all(diffs_arr == 0.0):
			continue

		p_val = sign_flip_permutation_test(diffs_arr, rng=rng)

		results.append(
			{
				"transition": f"{from_aoi} -> {to_aoi}",
				"from_aoi": from_aoi,
				"to_aoi": to_aoi,
				"n_participants": len(eligible_pids),
				"mean_had_patch_prop": round(float(np.mean(had_patch_vals)), 4),
				"mean_control_prop": round(float(np.mean(ctrl_vals)), 4),
				"mean_diff_patch_minus_ctrl": round(float(diffs_arr.mean()), 4),
				"p_value": p_val,
			}
		)

	if not results:
		print("\nNo testable transitions found.")
		return

	results_df = pd.DataFrame(results)
	results_df["bh_significant"] = bh_reject(results_df["p_value"].values)
	results_df = results_df.sort_values("p_value").reset_index(drop=True)

	# ── Significant results ───────────────────────────────────────────────────
	sig = results_df[results_df["bh_significant"]]
	n_tested = len(results_df)
	print(f"\nSignificant after FDR correction: {len(sig)} / {n_tested} transitions tested\n")

	display_cols = [
		"transition",
		"n_participants",
		"mean_had_patch_prop",
		"mean_control_prop",
		"mean_diff_patch_minus_ctrl",
		"p_value",
	]
	if len(sig) > 0:
		print(sig[display_cols].to_string(index=False))
	else:
		print("No individual transitions reached significance after FDR correction.")

	# ── Full table ────────────────────────────────────────────────────────────
	print(f"\n{'─' * 70}")
	print("All transitions (sorted by p-value):")
	print(f"{'─' * 70}")
	print(
		results_df[display_cols + ["bh_significant"]].to_string(index=False)
	)

	# ── Save ──────────────────────────────────────────────────────────────────
	output_csv = BASE_DIR / "transition_paired_permutation_analysis.csv"
	results_df.to_csv(output_csv, index=False)
	print(f"\nFull results saved to {output_csv.name}")


if __name__ == "__main__":
	main()
