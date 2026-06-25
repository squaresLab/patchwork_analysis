# Patch-editing (RQ2): how developers use a suggested patch, and whether that
# relates to correctness.
#
# Input: patch_usage.csv (in this directory, built by build_patch_usage.py) --
# each patch-condition task categorized against the canonical Eladawy suggested
# patches and the IDE event stream, into one of five patch_usage categories:
# applied_unchanged, applied_and_modified, own_fix_at_site, own_fix_elsewhere,
# nothing. Patch tasks only (conditions correct + overfitting), 84 rows. There is
# no control condition, so every condition contrast is overfitting-vs-correct.
#
# Fitted outcomes (all logistic GLMM ~ predictor + (1|PID)+(1|bug), standard
# RE-dropping fallback from model_helpers.R, condition releveled with `correct`
# as reference, BH within the family, ORs via exp()):
#   own_fix ~ condition            wrote their own fix (patch not used, anywhere)
#   own_fix_elsewhere ~ condition  abandoned the patch's fix LOCATION (the paper's
#                                  "fixed elsewhere" wording)
#   applied_unchanged ~ condition  left the patch as given
#   correct ~ patch_modified       among the tasks where the patch ENTERED the
#                                  code (applied_unchanged + applied_and_modified),
#                                  does modifying it relate to correctness
#
# SMALL-N DISCIPLINE. Several cells are tiny (applied_and_modified=12,
# own_fix_at_site=9). For every model we (a) report the per-condition Y/N cells,
# (b) report the plain descriptive rates by condition, and (c) flag any model
# where a 2x2 cell is < 5 or the model is separated / the CI explodes, as
# UNSTABLE -> treat as descriptive only. With these Ns the descriptive numbers
# are usually what the paper should report, not the OR.
#
# Run from repo root:
#   Rscript patchwork_analysis/paper_results/02_patch_editing/patch_editing_models.R

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

IN  <- file.path(ROOT, "patchwork_analysis/paper_results/02_patch_editing/patch_usage.csv")
OUT <- file.path(ROOT, "patchwork_analysis/paper_results/results/results_patch_editing.json")

SMALL_CELL <- 5L  # any 2x2 cell strictly below this => flag UNSTABLE
CI_HI_BLOWUP <- 50  # OR CI upper bound at/above this => flag UNSTABLE (separation)

d <- read.csv(IN, stringsAsFactors = FALSE)

# ---- input verification -----------------------------------------------------
stopifnot(nrow(d) == 84)
cat("Input rows:", nrow(d), "\n")
cat("Conditions:", paste(sort(unique(d$condition)), collapse = ", "), "\n")
cat("patch_usage counts:\n")
print(table(d$patch_usage))
expected_counts <- c(applied_unchanged = 44, applied_and_modified = 12,
                     own_fix_at_site = 9, own_fix_elsewhere = 13, nothing = 6)
got <- table(d$patch_usage)
for (k in names(expected_counts)) {
  stopifnot(as.integer(got[k]) == expected_counts[[k]])
}
cat("Category counts match expected (44/12/9/13/6).\n")

d$correct_bin <- as.integer(d$correct == "Y")
d$condition <- factor(d$condition, levels = c("correct", "overfitting"))
d$PID <- factor(d$PID)
d$bug <- factor(d$bug)

# ---- descriptive helpers ----------------------------------------------------

# raw rate of `outcome_bin` by condition, with Y/N cell counts.
descriptive_by_condition <- function(data, outcome_bin) {
  conds <- levels(droplevels(data$condition))
  out <- lapply(conds, function(cl) {
    sub <- data[data$condition == cl, ]
    y <- sum(sub[[outcome_bin]] == 1L)
    n <- nrow(sub)
    list(condition = cl, n = n, n_yes = y, n_no = n - y,
         rate = if (n > 0) round(y / n, 4) else NA_real_)
  })
  names(out) <- conds
  out
}

# pretty per-condition "cond=Y/N" string from a binary outcome.
per_cond_yn <- function(data, outcome_bin) {
  conds <- levels(droplevels(data$condition))
  paste(sapply(conds, function(cl) {
    sub <- data[data$condition == cl, ]
    y <- sum(sub[[outcome_bin]] == 1L)
    paste0(cl, "=", y, "/", nrow(sub) - y)  # yes/no
  }), collapse = "; ")
}

# min 2x2 cell count for an outcome x condition table.
min_cell <- function(data, outcome_bin) {
  tb <- table(data[[outcome_bin]], droplevels(data$condition))
  min(as.integer(tb))
}

# ---- generic 2-level fit ----------------------------------------------------
# Fits outcome_bin ~ predictor + (1|PID)+(1|bug) with the standard fallback.
# `predictor` is the fixed effect name (condition, or patch_modified). The
# second coefficient row is the contrast of interest. Returns a one-row record
# plus an attached descriptive list and stability flag.
fit_2level <- function(data, outcome_bin, predictor, outcome_label,
                       contrast_label) {
  cat("\n===== ", outcome_label, " =====\n", sep = "")

  fs <- paste0(outcome_bin, " ~ ", predictor, " + (1 | PID) + (1 | bug)")
  fb <- fit_with_fallback(fs, data, gaussian = FALSE, family = binomial())
  m <- fb$model
  if (is.null(m)) { cat("MODEL FAILED\n"); return(NULL) }

  co <- summary(m)$coefficients
  est <- co[2, 1]; se <- co[2, 2]; p <- co[2, 4]
  or <- exp(est); ci_low <- exp(est - 1.96 * se); ci_high <- exp(est + 1.96 * se)

  # 2x2 cell counts (outcome x predictor levels)
  pred_vec <- if (predictor == "condition") droplevels(data$condition) else data[[predictor]]
  tb <- table(outcome = data[[outcome_bin]], predictor = pred_vec)
  mc <- min(as.integer(tb))

  # stability assessment
  stability <- "ok"
  reasons <- character(0)
  if (mc < SMALL_CELL) reasons <- c(reasons, paste0("min 2x2 cell = ", mc, " (<", SMALL_CELL, ")"))
  if (is.finite(ci_high) && ci_high >= CI_HI_BLOWUP)
    reasons <- c(reasons, paste0("CI upper = ", round(ci_high, 1), " (separation/near-separation)"))
  if (!is.finite(or) || or > 1e4)
    reasons <- c(reasons, "OR non-finite / explosive (separation)")
  if (length(reasons) > 0)
    stability <- paste0("UNSTABLE: ", paste(reasons, collapse = "; "),
                        " -- treat as DESCRIPTIVE only")

  # The printed and JSON per-predictor-level Y/N breakdown must describe the
  # model's actual predictor. When the predictor is `condition` this is the
  # by-condition breakdown; when it is not (e.g. patch_modified), break down by
  # the predictor levels so the breakdown matches the contrast, not condition.
  per_pred_yn <- function(data, outcome_bin) {
    lv <- sort(unique(data[[predictor]]))
    paste(sapply(lv, function(pl) {
      sub <- data[data[[predictor]] == pl, ]
      y <- sum(sub[[outcome_bin]] == 1L)
      paste0(predictor, "=", pl, ": ", y, "/", nrow(sub) - y)  # yes/no
    }), collapse = "; ")
  }
  per_pred_n <- function(data) {
    lv <- sort(unique(data[[predictor]]))
    paste(sapply(lv, function(pl) {
      paste0(predictor, "=", pl, "=", sum(data[[predictor]] == pl))
    }), collapse = ";")
  }

  if (predictor == "condition") {
    cell_yn_str <- per_cond_yn(data, outcome_bin)
    cell_n_str <- paste(names(table(droplevels(data$condition))),
                        as.integer(table(droplevels(data$condition))),
                        sep = "=", collapse = ";")
  } else {
    cell_yn_str <- per_pred_yn(data, outcome_bin)
    cell_n_str <- per_pred_n(data)
  }

  cat("RE used: ", fb$re_structure, " | N = ", nrow(data), "\n", sep = "")
  cat("2x2 (outcome rows x predictor cols):\n"); print(tb)
  cat("per-predictor Y/N: ", cell_yn_str, "\n", sep = "")
  cat("OR = ", round(or, 4), "  95% CI [", round(ci_low, 4), ", ",
      round(ci_high, 4), "]  p = ", signif(p, 4), "\n", sep = "")
  cat("stability: ", stability, "\n", sep = "")

  desc <- descriptive_by_condition(data, outcome_bin)

  # When the predictor is NOT condition (i.e. patch_modified), the by-condition
  # descriptive is not the relevant breakdown; add the outcome rate by the
  # predictor levels so the JSON is self-contained for that model.
  desc_by_predictor <- NULL
  if (predictor != "condition") {
    lv <- sort(unique(data[[predictor]]))
    desc_by_predictor <- lapply(lv, function(pl) {
      sub <- data[data[[predictor]] == pl, ]
      y <- sum(sub[[outcome_bin]] == 1L); n <- nrow(sub)
      list(predictor = predictor, level = pl, n = n, n_yes = y, n_no = n - y,
           rate = if (n > 0) round(y / n, 4) else NA_real_)
    })
    names(desc_by_predictor) <- paste0(predictor, "=", lv)
  }

  rec <- list(
    finding = "patch_editing",
    outcome = outcome_label,
    model = "logistic GLMM",
    re_structure = fb$re_structure,
    contrast = contrast_label,
    estimate = round(or, 5),
    effect_scale = "odds_ratio",
    se = round(se, 5),
    ci_low = round(ci_low, 5),
    ci_high = round(ci_high, 5),
    p_raw = p,
    p_BH = NA_real_,
    n_tasks = nrow(data),
    per_condition_n = cell_n_str,
    per_cell_yn = cell_yn_str,
    min_2x2_cell = mc,
    stability = stability,
    descriptive = desc,
    descriptive_by_predictor = desc_by_predictor
  )
  rec
}

# =============================================================================
# Subsets
# =============================================================================

# Full patch set (all 84): used for outcomes 1a, 1b, 2.
patch <- d

# own_fix (broad): patch NOT used; participant wrote their own fix anywhere.
patch$own_fix <- as.integer(patch$patch_usage %in% c("own_fix_at_site", "own_fix_elsewhere"))
# own_fix_elsewhere (narrow): abandoned the patch's fix LOCATION.
patch$own_fix_elsewhere <- as.integer(patch$patch_usage == "own_fix_elsewhere")
# applied_unchanged: left the patch as given.
patch$applied_unchanged_bin <- as.integer(patch$patch_usage == "applied_unchanged")

# Patch-entered subset (56): patch actually entered the code.
entered <- d[d$patch_usage %in% c("applied_unchanged", "applied_and_modified"), ]
entered$condition <- droplevels(entered$condition)
entered$patch_modified <- as.integer(entered$patch_usage == "applied_and_modified")

cat("\n--- subset sizes ---\n")
cat("patch (all): ", nrow(patch), "\n", sep = "")
cat("entered (applied_unchanged + applied_and_modified): ", nrow(entered), "\n", sep = "")

# =============================================================================
# Fits
# =============================================================================

records <- list()

# OUTCOME 1a: own_fix ~ condition  (broad "wrote their own fix" reading)
records[[length(records) + 1]] <- fit_2level(
  patch, "own_fix", "condition",
  outcome_label = "own_fix ~ condition (broad: patch not used, any location)",
  contrast_label = "overfitting - correct")

# own_fix_elsewhere ~ condition: the narrow "abandoned the patch's fix LOCATION"
# reading, matching the paper's "fixed elsewhere" wording. The broad own_fix
# above is the "wrote their own fix anywhere" reading.
records[[length(records) + 1]] <- fit_2level(
  patch, "own_fix_elsewhere", "condition",
  outcome_label = "own_fix_elsewhere ~ condition (narrow: abandoned fix location)",
  contrast_label = "overfitting - correct")

# applied_unchanged ~ condition: left the patch as given.
records[[length(records) + 1]] <- fit_2level(
  patch, "applied_unchanged_bin", "condition",
  outcome_label = "applied_unchanged ~ condition (left patch as given)",
  contrast_label = "overfitting - correct")

# correct ~ patch_modified: among the tasks where the patch entered the code,
# does modifying it relate to correctness.
records[[length(records) + 1]] <- fit_2level(
  entered, "correct_bin", "patch_modified",
  outcome_label = "correct ~ patch_modified (patch-entered subset)",
  contrast_label = "patch_modified(applied_and_modified) - applied_unchanged")

records <- Filter(Negate(is.null), records)

# =============================================================================
# BH within the family of fitted contrasts
# =============================================================================
p_raw_vec <- sapply(records, function(r) r$p_raw)
p_BH_vec <- p.adjust(p_raw_vec, method = "BH")
for (i in seq_along(records)) {
  records[[i]]$p_raw <- round(records[[i]]$p_raw, 6)
  records[[i]]$p_BH <- round(p_BH_vec[i], 6)
}

cat("\n===== fitted contrasts (BH within family of ", length(records), ") =====\n", sep = "")
for (r in records) {
  cat(sprintf("%-55s OR=%.4f  CI[%.3f,%.3f]  p=%.4f  pBH=%.4f  | %s\n",
              r$outcome, r$estimate, r$ci_low, r$ci_high, r$p_raw, r$p_BH,
              if (startsWith(r$stability, "UNSTABLE")) "UNSTABLE" else "ok"))
}

# =============================================================================
# Claim C (descriptive only, NOT a fitted contrast):
# Among applied_and_modified tasks only, correct=Y rate by condition.
# The "coin flip" claim: editing an applied patch lands near 50% either way.
# N = 12 total, too small to model.
# =============================================================================
mod_only <- d[d$patch_usage == "applied_and_modified", ]
mod_only$condition <- droplevels(mod_only$condition)
claimC <- lapply(levels(mod_only$condition), function(cl) {
  sub <- mod_only[mod_only$condition == cl, ]
  y <- sum(sub$correct_bin == 1L); n <- nrow(sub)
  list(condition = cl, n = n, n_correct = y, n_incorrect = n - y,
       rate_correct = if (n > 0) round(y / n, 4) else NA_real_)
})
names(claimC) <- levels(mod_only$condition)
cat("\n===== Claim C (descriptive only; applied_and_modified, N=",
    nrow(mod_only), ") =====\n", sep = "")
for (c in claimC) {
  cat(sprintf("  %-12s correct %d/%d = %.0f%%\n",
              c$condition, c$n_correct, c$n, 100 * c$rate_correct))
}

claimC_obj <- list(
  label = "Claim C: applied_and_modified, correct=Y rate by condition",
  note = paste("DESCRIPTIVE ONLY -- N =", nrow(mod_only),
               "is too small to model. Editing an applied patch lands near 50%",
               "correct in either condition (the 'coin flip')."),
  by_condition = claimC
)

# =============================================================================
# Write JSON
# =============================================================================
obj <- list(
  finding = "patch_editing",
  input = "patch_usage.csv (84 patch-tasks)",
  note = paste(
    "Patch-editing models on the patch_usage categorization. Conditions:",
    "correct (reference) + overfitting. All contrasts are overfitting-vs-correct.",
    "Several cells are small; UNSTABLE-flagged contrasts should be read as",
    "descriptive, not as ORs."),
  category_counts = as.list(table(d$patch_usage)),
  contrasts = records,
  claim_C = claimC_obj
)
write(toJSON(obj, dataframe = "rows", auto_unbox = TRUE, na = "null", pretty = TRUE), OUT)
cat("\nWrote", OUT, "\n")
