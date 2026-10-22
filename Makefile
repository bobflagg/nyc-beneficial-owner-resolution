.PHONY: install test lint build-lwc eval export build-release validate-release explain fixtures excerpt help

# Release build (see docs/release-contract.md). Until nlr 0.2.0 is released and pinned in
# pyproject.toml, point NLR at a local checkout of nlr's capture-decisions branch:
#   make test NLR=../nyc-landlord-resolution-capture
OUT ?= release/contract
NLR ?=
UVRUN = uv run $(if $(NLR),--with-editable $(NLR))

help:
	@echo "install    - uv sync (deps incl. nlr from git)"
	@echo "test       - run the test suite (integration tests skip without PG*)"
	@echo "lint       - ruff check"
	@echo "build-lwc  - build landlords_with_connections from wow_landlords (needs PG*)"
	@echo "eval       - the paired divergence report vs Who Owns What (needs PG*)"
	@echo "export     - write the person-free dataset to release/ (needs PG*)"
	@echo "build-release    - build and validate a contract release in OUT (default release/contract)"
	@echo "                   make build-release SNAPSHOT_ID=<id> [AS_OF=YYYY-MM-DD] [RUN_ID=<id>] [REQUIRE_CLEAN=1] [NLR=<path>]"
	@echo "validate-release - validate the release in OUT against the contract"
	@echo "explain          - explain a lot, pair or group of the release in OUT: make explain ARGS=\"lot <bbl>\""
	@echo "fixtures         - regenerate tests/fixtures/synthetic_release (no database)"
	@echo "excerpt          - cut an excerpt of the release in OUT: make excerpt SEEDS=\"OP-67966\" EXCERPT_OUT=tests/fixtures/citadel_excerpt"

install:
	uv sync

test:
	$(UVRUN) pytest -q

lint:
	uv run ruff check src tests

build-lwc:
	uv run python -m bor.build_lwc

eval:
	uv run python -m bor.eval.divergence

export:
	uv run python -m bor.export release

build-release:
	@test -n "$(SNAPSHOT_ID)" || { echo "SNAPSHOT_ID is required, in the form the KG defines: make build-release SNAPSHOT_ID=<id>"; exit 2; }
	$(UVRUN) python -m bor.release build $(OUT) --snapshot-id $(SNAPSHOT_ID) $(if $(AS_OF),--as-of $(AS_OF)) $(if $(RUN_ID),--run-id $(RUN_ID)) $(if $(REQUIRE_CLEAN),--require-clean)

validate-release:
	$(UVRUN) python -m bor.release validate $(OUT)

explain:
	@test -n "$(ARGS)" || { echo "usage: make explain ARGS=\"lot <bbl>\"  |  \"pair <bbl> <bbl> [layer]\"  |  \"group <id>\""; exit 2; }
	$(UVRUN) python -m bor.explain $(OUT) $(ARGS)

fixtures:
	uv run python tests/fixtures/make_synthetic_release.py

EXCERPT_OUT ?= tests/fixtures/citadel_excerpt
excerpt:
	@test -n "$(SEEDS)" || { echo "usage: make excerpt SEEDS=\"OP-67966\" [OUT=<release>] [EXCERPT_OUT=<dir>]"; exit 2; }
	$(UVRUN) python -m bor.excerpt $(OUT) $(EXCERPT_OUT) $(SEEDS)
