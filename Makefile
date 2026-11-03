ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PYTHON ?= $(if $(wildcard $(ROOT).baseline/venv/bin/python),$(ROOT).baseline/venv/bin/python,python3)

.PHONY: build demo test
build:
	$(MAKE) -C $(ROOT)src/lays/cachesim/native MODE=release apps
	$(MAKE) -C $(ROOT)src/lays/nocsim/eventsim
	$(MAKE) -C $(ROOT)src/lays/weight_trace_gen/loas

demo:
	$(PYTHON) $(ROOT)scripts/pipeline.py

test:
	$(PYTHON) -m pytest $(ROOT)tests -q
