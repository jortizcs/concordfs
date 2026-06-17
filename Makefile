.PHONY: help install test run-experiment clean

help:
	@echo "ConcordFS v0.3.0 - Make targets"
	@echo ""
	@echo "  make install         Install Python SDK"
	@echo "  make test            Run pytest suite"
	@echo "  make run-experiment  Run minimal latency experiment"
	@echo "  make clean           Clean build artifacts"
	@echo "  make inspect         Show filesystem state"

install:
	@echo "Installing Concord Python SDK..."
	cd sdk/python && pip install -e .
	@echo ""
	@echo "✅ Done! Try: make run-experiment"

test:
	@echo "Running tests..."
	cd sdk/python && pytest tests/ -v

run-experiment:
	@echo "Running minimal latency experiment..."
	@cd sdk/examples && ./run_experiment.sh

clean:
	@echo "Cleaning build artifacts..."
	rm -rf sdk/python/build sdk/python/dist sdk/python/*.egg-info
	rm -rf sdk/python/**/__pycache__
	rm -rf /tmp/concord
	@echo "✅ Done!"

inspect:
	@echo "=== Concord Filesystem State ==="
	@if [ -d /tmp/concord/demo ]; then \
		tree -L 3 /tmp/concord/demo 2>/dev/null || find /tmp/concord/demo -type f -o -type d | head -20; \
	else \
		echo "No agent running. Start one with: make run-experiment"; \
	fi
