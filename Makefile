.PHONY: check test lint typecheck lockcheck

PYTHON ?= python3

check:
	$(PYTHON) scripts/validate_repo.py

lockcheck:
	$(PYTHON) -m scripts.build_security.gate requirements-dev.lock
	$(PYTHON) -m scripts.build_security.gate --require-hashes --worker-inputs spikes/full_graph/requirements-worker.lock

test:
	$(PYTHON) -m unittest scripts.build_security.test_gate scripts.build_security.test_scan scripts.build_security.test_archive_inventory -v
	$(PYTHON) -m unittest discover -s eval/tests -v
	$(PYTHON) -m unittest discover -s eval/blind_review/tests -v
	$(PYTHON) -m unittest discover -s eval/mcp_fixture/tests -v
	PYTHONPATH=spikes/full_graph $(PYTHON) -m unittest discover -s spikes/full_graph/tests -v

lint:
	$(PYTHON) -m ruff check scripts/build_security eval spikes/full_graph

typecheck:
	$(PYTHON) -m mypy --explicit-package-bases --ignore-missing-imports scripts/build_security/gate.py scripts/build_security/scan.py scripts/build_security/archive_inventory.py scripts/build_security/secret_canary.py eval/scorecard.py eval/cost_export.py eval/tests/test_cost_export.py eval/target_projection.py eval/tests/test_target_projection.py eval/pre_distribution_attestation.py eval/tests/test_pre_distribution_attestation.py eval/blind_review/tool.py eval/blind_review/tests/test_blind_review.py eval/mcp_fixture/project.py eval/mcp_fixture/server.py eval/mcp_fixture/tests/test_fixture.py spikes/full_graph/spike

