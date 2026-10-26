ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PYTHON ?= $(if $(wildcard $(ROOT).baseline/venv/bin/python),$(ROOT).baseline/venv/bin/python,python3)

.PHONY: demo
demo:
	$(PYTHON) $(ROOT)scripts/demo.py
