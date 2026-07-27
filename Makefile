# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
# ocm-mcp-server developer entry points.
#
#   make e2e                one-command local end-to-end test + HTML report
#   make bootstrap          create the local fleet (1 hub + 3 spokes) end to end
#   make teardown           delete the fleet
#   make install            install the package (editable) + dev deps
#   make test               unit tests
#   make test-report        unit tests + refresh wiki/Unit-Test-Results.md, coverage badge,
#                           and the browsable HTML coverage report (.unit-report/htmlcov)
#   make lint               ruff
#   make inject SCENARIO=failing-rollout CLUSTER=cluster2
#   make reset CLUSTER=cluster2
#   make policy-test        offline Kyverno policy tests (needs kyverno CLI)
#   make eval               run the evaluation harness (see eval/README.md)
#   make release VERSION=0.2.3   bump versions everywhere, gate, tag, push; the tag
#                           pipeline publishes GitHub Release, PyPI, MCP Registry, image
#   make audit              tail the tool-call audit log

SCENARIO ?= failing-rollout
CLUSTER  ?= cluster2

.PHONY: e2e bootstrap teardown install test test-report lint policy-test inject reset eval audit release

release:
	./hack/release.sh $(VERSION)

e2e:
	./hack/e2e-local.sh

bootstrap:
	./hack/bootstrap.sh

teardown:
	./hack/teardown.sh

install:
	python3 -m pip install -e ".[dev,tracing]"

test:
	python3 -m pytest -q

test-report:
	python3 -m pytest -q --junitxml=.unit-report/junit.xml \
	  --cov=ocm_mcp_server --cov-report=json:.unit-report/coverage.json \
	  --cov-report=html:.unit-report/htmlcov --cov-report=term
	python3 hack/unit_report.py --junit .unit-report/junit.xml \
	  --coverage .unit-report/coverage.json \
	  --out-md wiki/Unit-Test-Results.md --out-badge wiki/coverage-badge.json

lint:
	python3 -m ruff check src tests eval

policy-test:
	kyverno test deploy/policies/tests

inject:
	./chaos/inject.sh $(SCENARIO) $(CLUSTER)

reset:
	./chaos/inject.sh reset $(CLUSTER)

eval:
	python3 eval/run_eval.py --scenarios eval/scenarios.yaml

audit:
	ocm-mcp audit -n 40
