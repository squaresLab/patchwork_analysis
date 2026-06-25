# Gap 5 (RQ3): do developers consult the browser MORE late in the task with a
# deceptive (overfitting) patch, to verify a distrusted suggestion?
#
# SUGGESTIVE, not confirmed. The cleanest piece is the binary "any late browser"
# question. The proper confirmatory model for the bounded late-third proportion
# would be a beta / ordered-beta GLMM, but glmmTMB is broken in this environment
# (TMB needs gfortran to rebuild, which is not installed) and brms/Stan are not
# installed. So we report the lme4 binary hurdle part plus a permutation test, and
# we show BOTH p-values so the method-dependence is explicit. The full lme4 hurdle,
# whole-task and late-third continuous models, and backstops are in
# logs/browser_engagement.log.
#
# The input CSV (browser_engagement_input.csv, in this directory) is produced
# locally by build_browser_engagement.py from the per-task fixation files and the
# timing CSV; it reads no exploration outputs.
#
# Run from repo root:
#   Rscript patchwork_analysis/paper_results/05_browser_engagement/browser_engagement_models.R

script_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- sub("^--file=", "", args[grep("^--file=", args)])
  if (length(file_arg) == 1) return(dirname(normalizePath(file_arg)))
  # fallback if sourced interactively
  if (!is.null(sys.frames()[[1]]$ofile)) return(dirname(normalizePath(sys.frames()[[1]]$ofile)))
  getwd()
}
find_root <- function() {
  env <- Sys.getenv("PATCHWORK_ROOT", unset = "")
  if (nzchar(env)) return(normalizePath(env))
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- sub("^--file=", "", args[grep("^--file=", args)])
  start <- if (length(file_arg) == 1) dirname(normalizePath(file_arg)) else getwd()
  d <- start
  repeat {
    if (basename(d) == "patchwork_analysis") return(dirname(d))
    parent <- dirname(d)
    if (parent == d) stop("Could not locate 'patchwork_analysis' above the script; set PATCHWORK_ROOT.")
    d <- parent
  }
}
ROOT <- find_root()
source(file.path(ROOT, "patchwork_analysis/paper_results/lib/model_helpers.R"))
set.seed(20260623)

IN <- file.path(script_dir(), "browser_engagement_input.csv")
OUT <- file.path(ROOT, "patchwork_analysis/paper_results/results/results_browser_engagement.json")

d <- read.csv(IN, stringsAsFactors = FALSE)
d <- prep_condition(d)
cat("N tasks:", nrow(d), "\n")
cat("P(any late browser) by condition:\n")
print(round(tapply(d$late_any, d$condition, mean), 3))

# Binary "any late browser" logistic GLMM with the standard RE fallback.
recs <- fit_contrasts(
  "late_any ~ condition + (1 | PID) + (1 | bug)", d,
  finding = "browser_engagement", outcome = "any_late_browser",
  model_label = "logistic GLMM (hurdle binary part)",
  gaussian = FALSE, family = binomial(), report_or = TRUE)
recs$p_BH <- p.adjust(recs$p_raw, method = "BH")

# Make the model label reflect what actually ran. When both random effects are
# singular the fallback drops to a plain glm, so the "GLMM" label is misleading;
# derive the label from re_structure in that case.
recs$model <- ifelse(
  grepl("plain lm/glm", recs$re_structure, fixed = TRUE),
  "logistic glm (hurdle binary part; both REs singular, dropped to glm)",
  recs$model)

# Model-free corroboration: permutation test on the late-third browser share
# (overfitting vs correct), and Fisher on any-late-browser (overfitting vs rest).
perm_p <- function(x, g, B = 10000) {
  obs <- abs(median(x[g]) - median(x[!g]))
  n <- length(x); k <- sum(g)
  ge <- 0
  for (b in seq_len(B)) {
    idx <- sample.int(n, k)
    gg <- logical(n); gg[idx] <- TRUE
    if (abs(median(x[gg]) - median(x[!gg])) >= obs - 1e-12) ge <- ge + 1
  }
  (ge + 1) / (B + 1)
}
sub <- d[d$condition %in% c("correct", "overfitting"), ]
pp <- perm_p(sub$late, sub$condition == "overfitting")
cat("\nPermutation (late-third share, overfitting vs correct) p =", round(pp, 4), "\n")

ft <- fisher.test(matrix(c(
  sum(d$condition != "overfitting" & d$late_any == 0),
  sum(d$condition != "overfitting" & d$late_any == 1),
  sum(d$condition == "overfitting" & d$late_any == 0),
  sum(d$condition == "overfitting" & d$late_any == 1)), nrow = 2))
cat("Fisher (any late browser, overfitting vs rest) p =", round(ft$p.value, 4), "\n")

corrob <- data.frame(
  finding = "browser_engagement",
  outcome = c("late_third_share", "any_late_browser"),
  model = c("permutation (median diff, 10k)", "Fisher exact (overfitting vs rest)"),
  re_structure = "none",
  contrast = c("correct_vs_overfit", "overfitting_vs_rest"),
  estimate = NA_real_, se = NA_real_, ci_low = NA_real_, ci_high = NA_real_,
  effect_scale = "none",
  p_raw = c(pp, ft$p.value), p_BH = NA_real_,
  n_tasks = c(nrow(sub), nrow(d)),
  per_condition_n = c(per_condition_n(sub), per_condition_n(d)),
  stringsAsFactors = FALSE)

all_recs <- rbind(recs, corrob)
all_recs$p_raw <- round(all_recs$p_raw, 6)
all_recs$p_BH <- round(all_recs$p_BH, 6)

cat("\n===== browser_engagement results (status: SUGGESTIVE) =====\n")
print(all_recs[, c("model", "contrast", "estimate", "p_raw", "p_BH")])

obj <- list(
  finding = "browser_engagement",
  status = "suggestive",
  note = paste("Binary GLMM correct-vs-overfit p~.05 vs permutation p~.23;",
               "no confirmatory beta/ordered-beta GLMM available (glmmTMB/Stan",
               "uninstallable here). Report as a suggestive correct-vs-overfit trend."),
  prop_any_late_browser = as.list(round(tapply(d$late_any, d$condition, mean), 4)),
  contrasts = all_recs)
write(jsonlite::toJSON(obj, dataframe = "rows", auto_unbox = TRUE, na = "null", pretty = TRUE), OUT)
cat("Wrote", OUT, "\n")
