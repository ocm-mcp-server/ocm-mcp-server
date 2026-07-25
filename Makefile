# ocm-mcp-server developer entry points.
#
#   make bootstrap          create the local fleet (1 hub + 3 spokes) end to end
#   make teardown           delete the fleet
#   make install            install the package (editable) + dev deps
#   make test               unit tests
#   make lint               ruff
#   make inject SCENARIO=failing-rollout CLUSTER=cluster2
#   make reset CLUSTER=cluster2
#   make eval               run the evaluation harness (see eval/README.md)
#   make audit              tail the tool-call audit log

SCENARIO ?= failing-rollout
CLUSTER  ?= cluster2

.PHONY: bootstrap teardown install test lint inject reset eval audit

bootstrap:
	./hack/bootstrap.sh

teardown:
	./hack/teardown.sh

install:
	python3 -m pip install -e ".[dev,tracing]"

test:
	python3 -m pytest -q

lint:
	python3 -m ruff check src tests eval

inject:
	./chaos/inject.sh $(SCENARIO) $(CLUSTER)

reset:
	./chaos/inject.sh reset $(CLUSTER)

eval:
	python3 eval/run_eval.py --scenarios eval/scenarios.yaml

audit:
	ocm-mcp audit -n 40
