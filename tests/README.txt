tests/ directory guide
======================

The CI workflow (.github/workflows/ci-tests.yml, job "python-tests") runs five pytest
suites. Run the suite that matches the code you changed, using the same path CI uses,
from the repository root:

  Suite     Command
  -------   ----------------------------------------------------
  app       pytest tests/app --ignore=tests/app/v1/common
  common    pytest tests/app/v1/common
  sagents   pytest tests/sagents
  clients   pytest tests/clients
  mcp       pytest tests/mcp_servers

Python version, system dependencies (such as the Linux sandbox setup) and pip
installs are defined in the CI workflow. See that file rather than copying them here.

Directories
-----------

app/
    Application backend tests: FastAPI routes, services and core modules.
    app/v1/common/   Legacy v1 shared services and models. Runs in the "common" suite.
    app/v1/server/   Legacy v1 server tests.
    app/v1/desktop/  Legacy v1 desktop tests.
    app/v2/server/   v2 server tests.
    app/v2/desktop/  v2 desktop tests.

sagents/
    Agent runtime tests.
    sagents/v1/      Legacy v1 runtime tests: agent/, flow/, tool/, utils/, messages/ and related.
    sagents/v2/      v2 runtime tests (matrix and contract tests, stores, sandbox, plugins).
    sagents/test_architecture.py checks import boundaries (architecture gate);
    sagents/test_versioned_layout.py smoke-tests public imports and entry points.
    sagents/v2/live/ Tests marked "live" call a real model provider. They are skipped
                     unless the API key environment variable is set (see pytest.ini).

clients/
    clients/cli/     Command-line client tests (JSON contracts, version dispatch, TUI, v2 run).

mcp_servers/
    Tests for the bundled MCP servers.

deploy/
    Deployment checks: Dockerfile, Windows runner manifest and Elasticsearch ownership.
    These are not part of the five CI suites above. Run them directly with
    pytest tests/deploy.

Legacy v1 tests and cross-version tests
---------------------------------------
v1 tests are kept in their current locations while the v1 code still exists.
v2 tests and cross-version CLI tests stay where they are as well.

manual/
-------
Hand-run demo scripts, for example tests/manual/planning_agent_run.py. pytest does not
collect them (norecursedirs in pytest.ini lists "manual"), so CI never runs them. Run a
script directly with python when you need it.

Shared pytest setup
-------------------
The root conftest.py adds the repository root to sys.path, so test files do not need
their own path setup or hard-coded user directories.
