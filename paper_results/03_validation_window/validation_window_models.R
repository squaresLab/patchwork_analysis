# Gap 3 (RQ2): does a patch make developers VALIDATE more? The interview model
# claims validation took more effort with a patch. We test it behaviorally in the
# post-fix window (last source edit -> task end): comprehension effort on a fix
# that already passes the tests.
#
# Direct test on validation_window_model_input.csv (last-source-edit boundary),
# built locally by build_validation_window.py in this directory from primary data.
# The result is the perception-vs-behavior gap: nothing shows MORE validation
# under a patch; source-minutes are LOWER (the one BH-surviving effect), buggy
# share/minutes flat. Full output (including the first-buggy-method-boundary
# sensitivity from post_localization_models.R) is in logs/validation_window.log.
#
# Run from repo root:
#   Rscript patchwork_analysis/paper_results/03_validation_window/validation_window_models.R

script_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- sub("^--file=", "", args[grep("^--file=", args)])
  if (length(file_arg) == 1) return(dirname(normalizePath(file_arg)))
  if (!is.null(sys.frames()[[1]]$ofile)) return(dirname(normalizePath(sys.frames()[[1]]$ofile)))
  getwd()
}
find_root <- function() {
  env <- Sys.getenv("PATCHWORK_ROOT", unset = "")
  if (nzchar(env)) return(normalizePath(env))
  d <- script_dir()
  repeat {
    if (basename(d) == "patchwork_analysis") return(dirname(d))
    parent <- dirname(d)
    if (parent == d) stop("Could not locate 'patchwork_analysis' above the script; set PATCHWORK_ROOT.")
    d <- parent
  }
}
ROOT <- find_root()
source(file.path(ROOT, "patchwork_analysis/paper_results/lib/model_helpers.R"))

IN <- file.path(script_dir(), "validation_window_model_input.csv")
OUT <- file.path(ROOT, "patchwork_analysis/paper_results/results/results_validation_window.json")

df <- read.csv(IN, stringsAsFactors = FALSE, na.strings = c("", "NA"))
to_bool <- function(x) x %in% c("True", "TRUE", "true", TRUE)
df$has_gaze <- to_bool(df$has_gaze)
df$has_window <- to_bool(df$has_window)

# Base set: defined window + gaze present; drop genuinely-empty windows.
base <- df[df$has_window & df$has_gaze, ]
bad <- !is.na(base$window_dur_min) & (base$window_dur_min <= 0 | base$task_dur_min > 26)
cat("Excluded empty/artifact windows:", sum(bad), "\n")
base <- base[!bad, ]
base$source_minutes <- base$source_window * base$window_dur_min
base$buggy_minutes  <- base$buggy_window  * base$window_dur_min
# Window as a share of total task time: does validation take up MORE of the
# debugging effort under a patch, even when its absolute duration is similar?
base$window_frac <- base$window_dur_min / base$task_dur_min
base <- prep_condition(base)
cat("N per condition:\n"); print(table(base$condition))

# Join test-pass status from the main analysis CSV for the sensitivity subset.
# Both CSVs key on (PID, task_no) with identical PID format ("P1"), so a left
# merge should match every base row. We verify no unmatched rows below.
main <- read.csv(file.path(ROOT, "patchwork_analysis/timing_correctness_data.csv"),
                 stringsAsFactors = FALSE, na.strings = c("", "NA"))
pass_key <- data.frame(PID = as.character(main$PID),
                       task_no = main$task_no,
                       passes_original_tests = main$passes_original_tests,
                       stringsAsFactors = FALSE)
base_pid_chr <- as.character(base$PID)
n_before <- nrow(base)
base <- merge(transform(base, PID = base_pid_chr), pass_key,
              by = c("PID", "task_no"), all.x = TRUE, sort = FALSE)
base <- prep_condition(base)  # re-factor PID/condition/bug after merge
n_match <- sum(!is.na(base$passes_original_tests))
cat(sprintf("Merge of passes_original_tests: %d/%d base rows matched (%d unmatched).\n",
            n_match, n_before, n_before - n_match))

# Primary family: the post-fix window measures, including the window's share of
# total task time. If a patch made validation MORE effortful, or took up MORE of
# the debugging effort, these would be HIGHER under patch; the finding is they
# are not.
fit_y <- function(yname, outcome) {
  d <- base[is.finite(base[[yname]]), ]
  d$.y <- d[[yname]]
  fit_contrasts(".y ~ condition + (1 | PID) + (1 | bug)", d,
                finding = "validation_window", outcome = outcome,
                model_label = "lmer (post-fix window)")
}

recs <- rbind(
  fit_y("window_dur_min",  "window_duration_min"),
  fit_y("window_frac",     "window_fraction_of_task"),
  fit_y("source_minutes",  "source_minutes_in_window"),
  fit_y("source_window",   "source_share_in_window"),
  fit_y("buggy_minutes",   "buggy_method_minutes_in_window"),
  fit_y("buggy_window",    "buggy_method_share_in_window")
)

# BH family choice is a researcher degree of freedom that moves the source-minutes
# effect across .05. Record BOTH: the narrow family (the patch-vs-control tests,
# one per outcome) and the wider family (both contrasts per outcome). The NULL
# headline (no measure shows MORE validation under a patch, in absolute time or
# as a share of the task) holds under either.
recs$p_BH_family10 <- round(p.adjust(recs$p_raw, method = "BH"), 6)
pvc <- recs$contrast == "patch_vs_control"
recs$p_BH_pvc5 <- NA_real_
recs$p_BH_pvc5[pvc] <- round(p.adjust(recs$p_raw[pvc], method = "BH"), 6)
recs$p_BH <- recs$p_BH_family10  # default reported = conservative wider family
recs$p_raw <- round(recs$p_raw, 6)
recs$subset <- "all_tasks"
cat("\n===== BH families (pvc5 = narrow, family10 = wide) =====\n")
print(recs[, c("outcome", "contrast", "estimate", "p_raw", "p_BH_pvc5", "p_BH_family10")])

# ---------------------------------------------------------------------------
# SENSITIVITY: restrict to test-passing tasks (passes_original_tests == 'Y').
# The validation window is only validating a PASSING fix for tasks whose final
# state passed the tests; for never-passing tasks the post-edit window is not
# really validation. This subset checks the NULL is not an artifact of including
# unsolved tasks. NOTE: passes_original_tests is the test-pass status, NOT the
# stricter semantic `correct` (overfitting tasks pass tests but are wrong).
# ---------------------------------------------------------------------------
base_pass <- base[!is.na(base$passes_original_tests) & base$passes_original_tests == "Y", ]
base_pass <- prep_condition(base_pass)
cat("\n===== SENSITIVITY: passes_original_tests == 'Y' =====\n")
cat("N per condition (test-pass subset):\n"); print(table(base_pass$condition))

# Parallel fitter closing over base_pass; tags records with the subset label.
fit_y_sub <- function(yname, outcome) {
  d <- base_pass[is.finite(base_pass[[yname]]), ]
  d$.y <- d[[yname]]
  fit_contrasts(".y ~ condition + (1 | PID) + (1 | bug)", d,
                finding = "validation_window", outcome = outcome,
                model_label = "lmer (post-fix window, test-pass subset)")
}

recs_sub <- rbind(
  fit_y_sub("window_dur_min",  "window_duration_min"),
  fit_y_sub("window_frac",     "window_fraction_of_task"),
  fit_y_sub("source_minutes",  "source_minutes_in_window"),
  fit_y_sub("source_window",   "source_share_in_window"),
  fit_y_sub("buggy_minutes",   "buggy_method_minutes_in_window"),
  fit_y_sub("buggy_window",    "buggy_method_share_in_window")
)
# Same BH family scheme as the primary block, applied within the subset.
recs_sub$p_BH_family10 <- round(p.adjust(recs_sub$p_raw, method = "BH"), 6)
pvc_sub <- recs_sub$contrast == "patch_vs_control"
recs_sub$p_BH_pvc5 <- NA_real_
recs_sub$p_BH_pvc5[pvc_sub] <- round(p.adjust(recs_sub$p_raw[pvc_sub], method = "BH"), 6)
recs_sub$p_BH <- recs_sub$p_BH_family10
recs_sub$p_raw <- round(recs_sub$p_raw, 6)
recs_sub$subset <- "passes_original_tests==Y"

cat("\n===== SENSITIVITY contrasts (test-pass subset) =====\n")
print(recs_sub[, c("outcome", "contrast", "estimate", "p_raw", "p_BH_pvc5", "p_BH_family10")])

# Write BOTH families into one JSON, clearly separated by the `subset` field.
all_recs <- rbind(recs, recs_sub)
write_results_json(all_recs, "validation_window", OUT)
