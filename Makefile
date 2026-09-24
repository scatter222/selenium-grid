# Common tasks. Override variables on the command line, e.g.
#   make smoke ENV=env/physical.yaml
#   make app APP=app_one
#   make parallel N=4
ENV ?= env/virtual.yaml
APP ?= app_one
N ?= 4
REPORTS ?= reports
PYTEST = uv run pytest --env=$(ENV)
REPORT_ARGS = --alluredir=$(REPORTS)/allure-results --junitxml=$(REPORTS)/junit-$@.xml

.PHONY: help sync lint format typecheck shellcheck unit check health grid smoke regression app \
	parallel bundle verify-grid clean

help:  ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

sync:  ## Install locked dependencies into .venv
	uv sync --frozen

lint:  ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format:  ## Apply ruff fixes and formatting
	uv run ruff check --fix .
	uv run ruff format .

typecheck:  ## mypy --strict
	uv run mypy

shellcheck:  ## Lint infra/ shell scripts
	uv run shellcheck -x infra/*.sh infra/*/*.sh

unit:  ## Offline tests of the harness itself (no kit needed)
	uv run pytest -m unit

check: lint typecheck shellcheck unit  ## Everything that runs without a kit

health:  ## Wait for the kit to pass every readiness check
	uv run python ci/wait_healthy.py --env=$(ENV)

grid:  ## Check the Grid hub is up with the expected slots
	uv run python ci/check_grid.py --env=$(ENV)

smoke:  ## Smoke tests against ENV
	$(PYTEST) -m smoke -n $(N) $(REPORT_ARGS)

regression:  ## Regression tests against ENV
	$(PYTEST) -m regression -n $(N) $(REPORT_ARGS)

app:  ## One app's tests, e.g. make app APP=app_one
	$(PYTEST) -m $(APP) -n $(N) $(REPORT_ARGS)

parallel:  ## Whole suite across N Grid slots
	$(PYTEST) -n $(N) $(REPORT_ARGS)

bundle:  ## Build the offline Grid bundle (needs internet or ARTIFACT_MIRROR)
	infra/bundle.sh

verify-grid:  ## Real Firefox session through the hub, e.g. make verify-grid HUB=http://hub:4444 URL=https://app/
	@test -n "$(HUB)" || { echo "usage: make verify-grid HUB=http://<hub>:4444 [URL=...] [SLOTS=4]"; exit 2; }
	infra/verify.sh --hub $(HUB) $(if $(URL),--url $(URL)) $(if $(SLOTS),--expect-slots $(SLOTS))

clean:  ## Remove reports and caches
	rm -rf $(REPORTS) .pytest_cache .mypy_cache .ruff_cache
