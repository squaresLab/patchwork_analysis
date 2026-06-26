# Reproduce every paper number from local inputs.
#
#   make all      run all builders + models, write results/ JSON + logs/
#   make clean     remove generated results (keeps the committed scripts)
#
# Run from this directory (patchwork_analysis/paper_results/).

ROOT ?= /Users/clegoues/research/_current/patchwork
export PATCHWORK_ROOT ?= $(ROOT)
PY ?= python3
RS ?= Rscript
HERE := $(ROOT)/patchwork_analysis/paper_results

.PHONY: all clean manifest search editing validation debugger browser test_run

all: search editing validation debugger browser test_run
	@echo "All analyses complete. Results in results/, logs in logs/."

# search-vs-study: does a patch reduce the developer's SEARCH, in two halves.
# GAZE half: per-task buggy/other-method fixation shares, normalized by fixation
# over the four non-patch AOIs (matching Kaia's AOI analyses). Raw minutes are
# retained in the input for descriptive illustration only. IDE half: navigation
# and distinct-files-opened counts from the IDE event stream (files-opened is the
# one significant "patch narrows search" signal; navigation is null after the
# duration offset, matching the prior Phases 0-5 result).
search:
	$(PY) $(HERE)/01_search_behavior/build_fixation_buggy_method.py | tee $(HERE)/logs/fixation_buggy_method_build.log
	cd $(ROOT) && $(RS) $(HERE)/01_search_behavior/fixation_buggy_method.R 2>&1 | tee $(HERE)/logs/fixation_buggy_method.log
	$(PY) $(HERE)/01_search_behavior/build_ide_navigation.py | tee $(HERE)/logs/ide_navigation_build.log
	cd $(ROOT) && $(RS) $(HERE)/01_search_behavior/ide_navigation.R 2>&1 | tee $(HERE)/logs/ide_navigation.log

# patch-editing: how developers edit the suggested patch (modeled contrasts).
editing:
	cd $(ROOT) && $(RS) $(HERE)/02_patch_editing/patch_editing_models.R 2>&1 | tee $(HERE)/logs/patch_editing.log

# fix-validation window (NULL: no measure shows more validation under a patch).
validation:
	cd $(ROOT) && $(RS) $(HERE)/03_validation_window/validation_window_models.R 2>&1 | tee $(HERE)/logs/validation_window.log

# debugger use (RQ3, and non-gaze corroboration of the search finding).
debugger:
	cd $(ROOT) && $(RS) $(HERE)/04_debugger_use/debugger_use_models.R 2>&1 | tee $(HERE)/logs/debugger_use.log

# late-task browser engagement (suggestive).
browser:
	cd $(ROOT) && $(RS) $(HERE)/05_browser_engagement/browser_engagement_models.R 2>&1 | tee $(HERE)/logs/browser_engagement.log

# test-run rate: do developers run tests proportionally more often per minute in
# some conditions? IDE companion to the fix-validation finding.
test_run:
	$(PY) $(HERE)/06_test_run_rate/build_test_run_rate.py | tee $(HERE)/logs/test_run_rate_build.log
	cd $(ROOT) && $(RS) $(HERE)/06_test_run_rate/test_run_rate.R 2>&1 | tee $(HERE)/logs/test_run_rate.log

clean:
	rm -f $(HERE)/results/results_*.json
	rm -f $(HERE)/01_search_behavior/fixation_buggy_method_input.csv
	rm -f $(HERE)/01_search_behavior/ide_navigation_input.csv
