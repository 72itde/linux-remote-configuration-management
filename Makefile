# Task runner for lrcm.
#
# These are the same commands CI runs, so `make check` passing locally means
# the pipeline will pass too. tests/test_makefile_matches_ci.py enforces that.

SHELL := /bin/bash
.DEFAULT_GOAL := help

SHELL_SCRIPTS := packaging/debian/build-deb.sh \
                 packaging/debian/postinst \
                 packaging/debian/postrm \
                 tests/smoke-test.sh \
                 tests/check-version-consistency.sh

.PHONY: help
help:  ## show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{ printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }'

.PHONY: venv
venv:  ## create .venv with the runtime and development dependencies
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt -r requirements-dev.txt

.PHONY: format
format:  ## rewrite the code to the project style
	ruff format .
	ruff check --fix .

.PHONY: lint
lint:  ## ruff, mypy, ansible-lint, yamllint, shellcheck, version consistency
	ruff check .
	ruff format --check .
	mypy
	ansible-lint --profile production
	yamllint --strict .
	shellcheck --severity=style $(SHELL_SCRIPTS)
	./tests/check-version-consistency.sh

.PHONY: test
test:  ## run the unit tests
	pytest

.PHONY: build
build:  ## build dist/lrcm_<version>_all.deb
	./packaging/debian/build-deb.sh

.PHONY: lintian
lintian: build  ## check the built package against Debian policy
	lintian --no-tag-display-limit dist/*.deb

.PHONY: smoke
smoke: build  ## run the container end-to-end test on Debian 13
	docker run --rm --volume "$(CURDIR):/workspace:ro" --workdir /workspace \
		--env DEBIAN_FRONTEND=noninteractive \
		docker.io/library/debian:13 /workspace/tests/smoke-test.sh package

.PHONY: check
check: lint test  ## everything CI checks, except the container matrix

.PHONY: clean
clean:  ## remove build output and caches
	rm -rf dist .mypy_cache .ruff_cache .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
