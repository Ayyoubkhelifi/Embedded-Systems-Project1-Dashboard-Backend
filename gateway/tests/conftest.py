import os
import sys
from pathlib import Path

os.environ.setdefault("BUFFER_DB_PATH", "")  # not consulted; set per-test

pytest_plugins = []

import httpx  # noqa: E402
import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway_pkg.store import GatewayStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = GatewayStore(str(tmp_path / "gateway.sqlite3"))
    yield s
    s.close()

