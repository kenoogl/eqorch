PYTHON ?= python3
PYTHONPATH_VALUE ?= src
TEST_DATABASE_URL ?= postgresql://eqorch:eqorch@127.0.0.1:55432/eqorch_test
POSTGRES_COMPOSE_FILE ?= tests/postgres-compose.yml

.PHONY: test-unit test-integration test-e2e test-performance test-postgres test-all postgres-up postgres-down postgres-ps

test-unit:
	PYTHONPATH=$(PYTHONPATH_VALUE) $(PYTHON) -m unittest discover -s tests/unit -v

test-integration:
	PYTHONPATH=$(PYTHONPATH_VALUE) $(PYTHON) -m unittest tests.integration.test_integration_paths -v

test-e2e:
	PYTHONPATH=$(PYTHONPATH_VALUE) $(PYTHON) -m unittest tests.e2e.test_cli_startup -v

test-performance:
	PYTHONPATH=$(PYTHONPATH_VALUE) $(PYTHON) -m unittest tests.performance.test_performance_budget -v

test-postgres:
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) PYTHONPATH=$(PYTHONPATH_VALUE) $(PYTHON) -m unittest tests.integration.test_postgres_persistence -v

test-all: test-unit test-integration test-e2e test-performance

postgres-up:
	docker-compose -f $(POSTGRES_COMPOSE_FILE) up -d

postgres-down:
	docker-compose -f $(POSTGRES_COMPOSE_FILE) down

postgres-ps:
	docker-compose -f $(POSTGRES_COMPOSE_FILE) ps
