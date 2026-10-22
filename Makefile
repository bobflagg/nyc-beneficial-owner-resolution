.PHONY: install test test-offline package-release lint build-lwc eval export build-release validate-release explain fixtures excerpt help

# Release build (see docs/release-contract.md). nlr is pinned in pyproject.toml (v0.2.0); to try an
# unreleased nlr, point NLR at a local checkout:
#   make test NLR=../nyc-landlord-resolution-capture
OUT ?= release/contract
NLR ?=
UVRUN = uv run $(if $(NLR),--with-editable $(NLR))

help:
	@echo "install    - uv sync (deps incl. nlr from git)"
	@echo "test       - run the test suite (the integration tests run when PGDATABASE is set, in the environment or bor's .env)"
	@echo "test-offline - the same, with the integration tests skipped even if .env sets PGDATABASE"
	@echo "lint       - ruff check"
	@echo "build-lwc  - build landlords_with_connections from wow_landlords (needs PG*)"
	@echo "eval       - the paired divergence report vs Who Owns What (needs PG*)"
	@echo "export     - write the person-free dataset to release/ (needs PG*)"
	@echo "build-release    - build and validate a contract release in OUT (default release/contract)"
	@echo "                   make build-release SNAPSHOT_ID=<id> [AS_OF=YYYY-MM-DD] [RUN_ID=<id>] [REQUIRE_CLEAN=1] [EVAL_DIR=eval_out GOLD_STATUS=<status>] [NLR=<path>]"
	@echo "validate-release - validate the release in OUT against the contract"
	@echo "package-release  - zip the validated release in OUT for publication: dist/bor-v<version>-<snapshot>.zip, .sha256, -NOTES.md"
	@echo "explain          - explain a lot, pair or group of the release in OUT: make explain ARGS=\"lot <bbl>\""
	@echo "fixtures         - regenerate tests/fixtures/synthetic_release (no database)"
	@echo "excerpt          - cut an excerpt of the release in OUT: make excerpt SEEDS=\"OP-67966\" EXCERPT_OUT=tests/fixtures/citadel_excerpt [NOTE=\"text\"]"

install:
	uv sync

test:
	$(UVRUN) pytest -q

# An empty PGDATABASE is not overridden by the .env that nlr loads when it is imported.
test-offline:
	PGDATABASE= $(UVRUN) pytest -q

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
	$(UVRUN) python -m bor.release build $(OUT) --snapshot-id $(SNAPSHOT_ID) $(if $(AS_OF),--as-of $(AS_OF)) $(if $(RUN_ID),--run-id $(RUN_ID)) $(if $(REQUIRE_CLEAN),--require-clean) $(if $(EVAL_DIR),--eval-dir $(EVAL_DIR) --gold-status $(GOLD_STATUS))

package-release:
	$(UVRUN) python -m bor.release_package $(OUT) --out dist

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
	$(UVRUN) python -m bor.excerpt $(OUT) $(EXCERPT_OUT) $(SEEDS) $(if $(NOTE),--note "$(NOTE)")
