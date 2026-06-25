# Shared modeling helpers for the paper_results layer.
#
# Encodes the project's fixed modeling conventions so every finding applies them
# identically and emits an auditable results record.
#
#   - Random effects (1|PID)+(1|bug), crossed. Fixed fallback when not estimable:
#     try full; on singular/error drop (1|bug) keeping (1|PID); else drop (1|PID)
#     keeping (1|bug); else plain lm/glm. The chosen structure is recorded.
#   - Two planned contrasts from the three-level condition factor:
#       patch_vs_control   = c(-1, 0.5, 0.5)
#       correct_vs_overfit = c(0, 1, -1)
#   - BH correction within a finding's family, never across findings.
#   - Odds ratios via exp() for logistic models.
#
# Results are accumulated into a list of records and written to one JSON per
# finding with write_results_json(). Each record carries enough to trace a paper
# number back to the model that produced it.

suppressMessages({
  library(lme4)
  library(lmerTest)
  library(emmeans)
  library(jsonlite)
})

CONTRASTS <- list(
  patch_vs_control = c(-1, 0.5, 0.5),
  correct_vs_overfit = c(0, 1, -1)
)

# Order condition consistently everywhere.
prep_condition <- function(d) {
  d$condition <- factor(d$condition, levels = c("control", "correct", "overfitting"))
  d$PID <- factor(d$PID)
  d$bug <- factor(d$bug)
  d
}

per_condition_n <- function(d) {
  tb <- table(d$condition)
  paste(names(tb), as.integer(tb), sep = "=", collapse = ";")
}

# Remove one random-effect grouping term from a model formula by its structure.
# Operates on the parsed formula via lme4's bar machinery, not on text, so it is
# insensitive to spacing and to fixed-effect names that share substrings with a
# grouping variable. The fixed part (including any offset()) is preserved
# verbatim through nobars(); the surviving RE bars are reattached unchanged.
drop_re_group <- function(formula_str, group) {
  f <- as.formula(formula_str)
  bars <- findbars(f)
  kept <- bars[vapply(bars, function(b) deparse(b[[3]]) != group, logical(1))]
  fixed_txt <- paste(deparse(nobars(f)), collapse = " ")
  if (length(kept) == 0) {
    return(fixed_txt)
  }
  re_txt <- paste(
    sprintf("(%s)", vapply(kept, function(b) paste(deparse(b), collapse = " "),
                           character(1))),
    collapse = " + "
  )
  paste(fixed_txt, "+", re_txt)
}

# Drop all random-effect terms, leaving only the fixed part.
drop_all_re <- function(formula_str) {
  paste(deparse(nobars(as.formula(formula_str))), collapse = " ")
}

# Fit a mixed model with the fixed RE-dropping fallback.
# `fitter` is lmer or glmer; `family` is passed through for glmer.
# The fitter tries the crossed (1|PID)+(1|bug) structure, falls back to (1|PID)
# (dropping bug), then to (1|bug) (dropping PID), then to a plain lm/glm with no
# random effects. A structure is passed over when its fit errors, emits a
# warning, or converges to a singular RE structure; the first structure whose
# fit clears all three is retained, and the chosen structure is recorded. The
# warning gate is deliberate: in a small-cell logistic family a convergence
# warning on the fuller RE structure signals separation, and retaining that fit
# yields an explosive odds ratio. Dropping to the simpler structure that the
# next-lower fallback fits cleanly is the safer choice for this design.
# Returns list(model, re_structure).
fit_with_fallback <- function(formula_str, data, gaussian = TRUE, family = NULL) {
  full   <- formula_str
  no_bug <- drop_re_group(formula_str, "bug")
  no_pid <- drop_re_group(formula_str, "PID")
  no_re  <- drop_all_re(formula_str)

  mk <- function(fs, drop_re = FALSE) {
    tryCatch({
      if (drop_re) {
        if (gaussian) lm(as.formula(fs), data = data)
        else glm(as.formula(fs), data = data, family = family)
      } else if (gaussian) {
        lmer(as.formula(fs), data = data, REML = TRUE,
             control = lmerControl(check.conv.singular = .makeCC("ignore", tol = 1e-4)))
      } else {
        glmer(as.formula(fs), data = data, family = family,
              control = glmerControl(check.conv.singular = .makeCC("ignore", tol = 1e-4)))
      }
    }, error = function(e) NULL, warning = function(w) NULL)
  }
  is_sing <- function(m) {
    if (is.null(m)) return(TRUE)
    if (inherits(m, "merMod")) return(isSingular(m, tol = 1e-4))
    FALSE
  }

  m <- mk(full); re <- "(1|PID)+(1|bug)"
  if (is_sing(m)) {
    m2 <- mk(no_bug)
    if (!is_sing(m2)) { m <- m2; re <- "(1|PID); dropped bug (singular)" }
    else {
      m3 <- mk(no_pid)
      if (!is_sing(m3)) { m <- m3; re <- "(1|bug); dropped PID (singular)" }
      else { m <- mk(no_re, drop_re = TRUE); re <- "none (both singular); plain lm/glm" }
    }
  }
  list(model = m, re_structure = re)
}

# Fit one outcome, extract the two planned contrasts, return a data.frame of
# records (one per contrast). `report_or` exponentiates the estimate/CI (logistic).
fit_contrasts <- function(formula_str, data, finding, outcome, model_label,
                          gaussian = TRUE, family = NULL, report_or = FALSE) {
  cat("\n=====", finding, "::", outcome, "=====\n")
  fb <- fit_with_fallback(formula_str, data, gaussian = gaussian, family = family)
  m <- fb$model
  if (is.null(m)) {
    cat("MODEL FAILED for", outcome, "\n")
    return(NULL)
  }
  cat("RE:", fb$re_structure, " | model:", model_label, " | N =", nrow(data),
      " |", per_condition_n(data), "\n")

  em <- emmeans(m, ~ condition)
  ct <- contrast(em, method = CONTRASTS)
  s <- as.data.frame(summary(ct, infer = c(TRUE, TRUE)))
  # emmeans names CI columns lower.CL/upper.CL (t-based) or asymp.LCL/asymp.UCL
  # (z-based, when df = Inf). Normalize to lo/hi.
  lo_col <- if ("lower.CL" %in% names(s)) "lower.CL" else "asymp.LCL"
  hi_col <- if ("upper.CL" %in% names(s)) "upper.CL" else "asymp.UCL"
  print(s[, c("contrast", "estimate", "SE", lo_col, hi_col, "p.value")])

  recs <- lapply(seq_len(nrow(s)), function(i) {
    est <- s$estimate[i]; lo <- s[[lo_col]][i]; hi <- s[[hi_col]][i]
    if (report_or) { est <- exp(est); lo <- exp(lo); hi <- exp(hi) }
    list(
      finding = finding, outcome = outcome, model = model_label,
      re_structure = fb$re_structure, contrast = as.character(s$contrast[i]),
      estimate = round(est, 5), se = round(s$SE[i], 5),
      ci_low = round(lo, 5), ci_high = round(hi, 5),
      effect_scale = if (report_or) "odds_ratio" else "raw",
      p_raw = s$p.value[i], p_BH = NA_real_,
      n_tasks = nrow(data), per_condition_n = per_condition_n(data)
    )
  })
  do.call(rbind, lapply(recs, function(r) as.data.frame(r, stringsAsFactors = FALSE)))
}

# Apply BH within a family of records (by p_raw) and write JSON + return.
finalize_family <- function(records, finding, results_path) {
  records$p_BH <- p.adjust(records$p_raw, method = "BH")
  records$p_raw <- round(records$p_raw, 6)
  records$p_BH <- round(records$p_BH, 6)
  cat("\n===== BH-adjusted (family =", nrow(records), "tests) =====\n")
  print(records[, c("outcome", "contrast", "estimate", "p_raw", "p_BH")])
  write_results_json(records, finding, results_path)
  records
}

write_results_json <- function(records, finding, results_path) {
  obj <- list(finding = finding, contrasts = records)
  write(toJSON(obj, dataframe = "rows", auto_unbox = TRUE, na = "null", pretty = TRUE),
        file = results_path)
  cat("Wrote", results_path, "\n")
}
