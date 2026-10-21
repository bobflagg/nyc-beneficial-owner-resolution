.PHONY: install test lint build-lwc eval export build-release validate-release help

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
