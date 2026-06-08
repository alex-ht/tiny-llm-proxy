"""Pytest configuration and shared fixtures.

Scaffolded early (DESIGN.md Phase 0 Step 1) so that CI (ruff + pytest) protects
every subsequent incremental change from the very first PRs onward.
"""

import pytest

# Common fixtures (temp dirs for logs, test clients, monkeypatched config, etc.)
# will be added in later steps as the modules under test are implemented.


@pytest.fixture(scope="session")
def anyio_backend():
    """Enable anyio for async tests if/when we add them."""
    return "asyncio"
