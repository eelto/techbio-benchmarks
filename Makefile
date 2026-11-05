.PHONY: install db refresh extract review report sample test lint round model-day validate

install:
	uv sync

db:
	uv run techbio db upgrade

# Daily refresh: free ingestion, deterministic AdComs, extraction under the standing approval.
refresh: db
	uv run ledger ingest free
	uv run ledger adcoms
	uv run ledger extract --execute --job-kind ledger_daily
	uv run ledger report

# Paid extraction is a dry run unless EXECUTE=1 (and an APPROVAL when no standing approval covers it).
extract:
	uv run ledger extract $(if $(EXECUTE),--execute) $(if $(APPROVAL),--approval "$(APPROVAL)") $(if $(LIMIT),--limit $(LIMIT)) --job-kind $(or $(JOB),ledger_extract)

review:
	uv run ledger review

report:
	uv run ledger report

sample:
	uv run ledger sample

test:
	uv run pytest

lint:
	uv run ruff check src tests migrations && uv run ruff format --check src tests migrations

round model-day validate:
	@echo "$@ lands with its milestone (arena: M2, harness: M3)"; exit 1
