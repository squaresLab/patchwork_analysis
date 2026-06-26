# Test-run-rate model: does the rate of running tests differ by condition?
#
# This is the IDE companion to the fix-validation finding. The motivating
# question (Kaia's) is whether developers run the tests proportionally more
# often in some conditions, measured as test runs PER MINUTE of task time.
#
# Outcome n_test_run is the count of test-execution ACTION events (the TEST_RUN
# set) read from the IntelliJ event stream by build_test_run_rate.py. The
# duration offset (time_minutes) matches ide_navigation's offset, so the rate is
# directly comparable to the navigation rate.
#
# Models (finding = "test_run_rate"):
#   - n_test_run ~ condition + offset(log(duration_min)) + (1|PID) + (1|bug)
#       PRIMARY: the per-minute RATE Kaia asked for                  [COUNT, rate]
#   - n_test_run ~ condition + (1|PID) + (1|bug)
#       raw count, no offset, reported side by side                 [COUNT, raw]
#
# Counts are fit with a negative-binomial GLMM (overdispersion expected),
# falling back to Poisson GLMM, with the RE-dropping fallback (full crossed REs,
# then drop bug, then drop PID, then plain glm.nb / glm). This mirrors
# ide_navigation.R; fit_contrasts in lib/model_helpers.R assumes a gaussian lmer
# and cannot carry the offset through a count GLMM, so the count fitter is local.
#
# The two planned contrasts (patch_vs_control, correct_vs_overfit) come from
# lib/model_helpers.R::CONTRASTS, reported as rate ratios via exp(). BH
# correction is applied within this finding's family. The results JSON shape
# matches the other findings.
#
# Run: Rscript \
#   patchwork_analysis/paper_results/06_test_run_rate/test_run_rate.R

suppressMessages({
  library(lme4)      # glmer.nb / glmer; glmmTMB unavailable (no TMB toolchain)
  library(MASS)      # glm.nb for the no-RE fallback
  library(emmeans)
  library(jsonlite)
})

# Resolve repo root from PATCHWORK_ROOT or the script's own location, so this
# runs from any working directory (matching the sibling model scripts).
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
LIB <- file.path(ROOT, "patchwork_analysis/paper_results/lib")
RESULTS <- file.path(ROOT, "patchwork_analysis/paper_results/results")
source(file.path(LIB, "model_helpers.R"))  # CONTRASTS, prep_condition, etc.

INPUT <- file.path(script_dir(), "test_run_rate_input.csv")
OUT_JSON <- file.path(RESULTS, "results_test_run_rate.json")
FINDING <- "test_run_rate"

d <- read.csv(INPUT)
d <- prep_condition(d)  # condition levels control/correct/overfitting; PID,bug factors
d$dur <- d$duration_min

cat(sprintf(
  "Test-run sample: %d tasks, %d participants\n",
  nrow(d), nlevels(droplevels(d$PID))))
cat("Per-condition N:", per_condition_n(d), "\n\n")

cat("=== descriptive: mean test runs per minute by condition ===\n")
d$rate_per_min <- d$n_test_run / d$dur
mr <- aggregate(rate_per_min ~ condition, data = d, FUN = mean)
print(format(mr, digits = 3), row.names = FALSE)
cat("\n=== descriptive: mean / median raw n_test_run by condition ===\n")
mt <- aggregate(n_test_run ~ condition, data = d, FUN = mean)
md <- aggregate(n_test_run ~ condition, data = d, FUN = median)
print(format(merge(
  setNames(mt, c("condition", "mean_count")),
  setNames(md, c("condition", "median_count"))), digits = 3),
  row.names = FALSE)
cat("\n")

# ---- local count-GLMM fitter with the RE-dropping fallback ----------------
# Tries, in order: NB GLMM (full crossed RE), NB GLMM dropping bug, NB GLMM
# dropping PID, then plain glm.nb. Each NB attempt that fails / does not
# converge falls back to the Poisson analogue at the same RE level before
# dropping more structure. Returns list(model, re_structure, family).
fit_count <- function(outcome, use_offset, data) {
  off <- if (use_offset) " + offset(log(dur))" else ""
  re_specs <- list(
    list(re = "(1 | PID) + (1 | bug)", label = "(1|PID)+(1|bug)"),
    list(re = "(1 | PID)", label = "(1|PID); dropped bug"),
    list(re = "(1 | bug)", label = "(1|bug); dropped PID")
  )
  for (spec in re_specs) {
    fs <- sprintf("%s ~ condition%s + %s", outcome, off, spec$re)
    m <- tryCatch(
      suppressMessages(suppressWarnings(
        glmer.nb(as.formula(fs), data = data))),
      error = function(e) NULL, warning = function(w) NULL)
    if (!is.null(m) && !isSingular(m, tol = 1e-4)) {
      return(list(model = m, re_structure = spec$label, family = "nbinom"))
    }
    mp <- tryCatch(
      suppressMessages(suppressWarnings(glmer(
        as.formula(fs), data = data, family = poisson))),
      error = function(e) NULL, warning = function(w) NULL)
    if (!is.null(mp) && !isSingular(mp, tol = 1e-4)) {
      return(list(model = mp, re_structure = spec$label,
                  family = "poisson(fallback)"))
    }
  }
  # No-RE fallback: NB GLM, then Poisson GLM.
  fs <- sprintf("%s ~ condition%s", outcome, off)
  m <- tryCatch(glm.nb(as.formula(fs), data = data),
                error = function(e) NULL)
  if (!is.null(m)) {
    return(list(model = m, re_structure = "none; plain glm.nb",
                family = "nbinom"))
  }
  m <- tryCatch(glm(as.formula(fs), data = data, family = poisson),
                error = function(e) NULL)
  if (!is.null(m)) {
    return(list(model = m, re_structure = "none; plain glm(poisson)",
                family = "poisson(fallback)"))
  }
  NULL
}

# Fit one count outcome, extract the two planned contrasts as rate ratios,
# return a data.frame of records (one per contrast).
fit_count_contrasts <- function(outcome, use_offset, model_label, data) {
  cat("\n=====", FINDING, "::", model_label, "=====\n")
  fb <- fit_count(outcome, use_offset, data)
  if (is.null(fb)) {
    cat("MODEL FAILED for", model_label, "\n")
    return(NULL)
  }
  m <- fb$model
  cat("RE:", fb$re_structure, " | family:", fb$family,
      " | offset:", use_offset, " | N =", nrow(data),
      " |", per_condition_n(data), "\n")
  # overdispersion on the Poisson scale, for transparency
  rp <- residuals(m, type = "pearson")
  od <- sum(rp^2) / df.residual(m)
  cat(sprintf("  overdispersion (Pearson/df): %.2f%s\n", od,
              if (fb$family == "poisson(fallback)" && od > 1.5)
                "  <- >1.5: Poisson SEs likely too small, caution"
              else ""))

  # emmeans on the response (rate ratio) scale. offset = 0 holds log(dur) fixed
  # so the contrast is a per-unit-time rate ratio when an offset is present.
  em <- if (use_offset) emmeans(m, ~ condition, offset = 0) else
    emmeans(m, ~ condition)
  ct <- contrast(em, method = CONTRASTS, type = "response")
  s <- as.data.frame(summary(ct, infer = c(TRUE, TRUE)))
  ratio_col <- if ("ratio" %in% names(s)) "ratio" else "estimate"
  lo_col <- if ("asymp.LCL" %in% names(s)) "asymp.LCL" else "lower.CL"
  hi_col <- if ("asymp.UCL" %in% names(s)) "asymp.UCL" else "upper.CL"
  cat("  contrasts (rate ratios):\n")
  print(s[, c("contrast", ratio_col, lo_col, hi_col, "p.value")])

  recs <- lapply(seq_len(nrow(s)), function(i) {
    list(
      finding = FINDING, outcome = outcome, model = model_label,
      re_structure = fb$re_structure, family = fb$family,
      offset = use_offset, contrast = as.character(s$contrast[i]),
      estimate = round(s[[ratio_col]][i], 5),
      se = round(s$SE[i], 5),
      ci_low = round(s[[lo_col]][i], 5),
      ci_high = round(s[[hi_col]][i], 5),
      effect_scale = "rate_ratio",
      p_raw = s$p.value[i], p_BH = NA_real_,
      n_tasks = nrow(data), per_condition_n = per_condition_n(data)
    )
  })
  do.call(rbind, lapply(recs, function(r) as.data.frame(r, stringsAsFactors = FALSE)))
}

# ---- fit the family -------------------------------------------------------
# PRIMARY headline: the per-minute RATE (with offset). The raw count (no offset)
# is reported side by side, labelled, to show whether any rate difference is
# carried by the count itself or by the duration normalization.
records <- rbind(
  fit_count_contrasts("n_test_run", TRUE,
                      "n_test_run (rate, offset)", d),
  fit_count_contrasts("n_test_run", FALSE,
                      "n_test_run (count, no offset)", d)
)

# ---- BH within this finding's family, write JSON --------------------------
records$p_BH <- p.adjust(records$p_raw, method = "BH")
records$p_raw <- round(records$p_raw, 6)
records$p_BH <- round(records$p_BH, 6)

cat("\n===== BH-adjusted (family =", nrow(records), "tests) =====\n")
print(records[, c("model", "contrast", "estimate", "p_raw", "p_BH")],
      row.names = FALSE)

obj <- list(finding = FINDING, contrasts = records)
write(toJSON(obj, dataframe = "rows", auto_unbox = TRUE, na = "null",
             pretty = TRUE), file = OUT_JSON)
cat("\nWrote", OUT_JSON, "\n")
