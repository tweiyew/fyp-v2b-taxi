

# Shortcuts for the simulator. Run `make` to list them.

PY := .venv/bin/python

CONFIG ?= configs/chicago_v1g.yaml
POLICY ?= EIGHTYTWENTY
WEIGHTS ?=
OUT ?= logs/$(basename $(notdir $(CONFIG)))_$(shell echo $(POLICY) | tr A-Z a-z).csv
ifndef RUN_ID
RUN_ID := $(shell date +%Y%m%d-%H%M%S)-$(basename $(notdir $(CONFIG)))-$(shell echo $(POLICY) | tr A-Z a-z)
endif

.DEFAULT_GOAL := help
.PHONY: help install test run trace viz

help: ## List targets and the variables `make run` accepts
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-8s %s\n", $$1, $$2}'
	@echo ""
	@echo "  make run variables (defaults shown):"
	@echo "    CONFIG=$(CONFIG)"
	@echo "    POLICY=$(POLICY)   (EIGHTYTWENTY or DNN)"
	@echo "    OUT=$(OUT)"
	@echo "    WEIGHTS=<policy .pt file, DNN only>"
	@echo "  make trace / make viz also take RUN_ID (default: <timestamp>-<config>-<policy>)"

install: .venv/.installed ## Create .venv with uv and install requirements.txt

$(PY):
	uv venv .venv --python 3.12

.venv/.installed: requirements.txt | $(PY)
	uv pip install --python $(PY) -r requirements.txt
	touch $@

test: install ## Run the test suite
	$(PY) -m pytest -q

# The simulator prints every simulated hour to stdout (simulator/simulator.py:243),
# so stdout is discarded. Errors go to stderr and still show. The one warning
# filtered here is gymnasium casting the action bounds to float32, which loses nothing.
run: install ## Simulate CONFIG's time window with POLICY and write the log to OUT
	@mkdir -p $(dir $(OUT))
	@echo "Simulating $(CONFIG) with $(POLICY) (a month takes about 15 s)..."
	@PYTHONPATH=$(CURDIR) $(PY) -W "ignore::UserWarning:gymnasium.spaces.box" -m scheduler -a EVAL -p $(POLICY) -c $(CONFIG) -o $(OUT) $(if $(WEIGHTS),-w $(WEIGHTS)) > /dev/null
	@echo "Wrote $(OUT) ($$(($$(wc -l < $(OUT)) - 1)) rows, one per tick)"

viz/zones.geojson:
	$(PY) -m viz.zones --out $@

trace: install ## Record CONFIG with POLICY hour by hour into results/RUN_ID/
	@echo "Recording $(CONFIG) with $(POLICY) (a month takes about 15 s)..."
	@PYTHONPATH=$(CURDIR) $(PY) -m viz.trace -c $(CONFIG) -p $(POLICY) $(if $(WEIGHTS),-w $(WEIGHTS)) --run-id $(RUN_ID)

viz: trace viz/zones.geojson ## Record a run and build its 3D replay page in viz/out/
	@$(PY) -m viz.build results/$(RUN_ID)
