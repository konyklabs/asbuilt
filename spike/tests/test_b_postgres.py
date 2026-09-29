"""Stack B against a real Postgres (konyklabs/asbuilt#4): the store contract
from tests/_support/store_contract.py on PostgresStore, and the integration
test on the real fixture (c5, then c6 incrementally, and a full c6), no
model, hash embedder. One throwaway pgvector container per module
(testcontainers), started only when Docker answers; every test here is
skipped otherwise. Ryuk is disabled and the container is stopped in the
fixture's own teardown."""

from __future__ import annotations

import os
import secrets
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from bench.build import build
from bench.protocol import Tier
from bench.run import ENTITY_KINDS, assemble_ingest_root
from tests._support import SPIKE_ROOT
from tests._support.store_contract import CHECKS

pytestmark = pytest.mark.postgres
IMAGE = "pgvector/pgvector:pg17"


def _docker_host() -> str | None:
    if os.environ.get("DOCKER_HOST"):
        return os.environ["DOCKER_HOST"]
    try:
        out = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _docker_answers() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="module")
def pg_dsn():
    postgres = pytest.importorskip("testcontainers.postgres")
    pytest.importorskip("psycopg")
    host = _docker_host()
    if host is None or not _docker_answers():
        pytest.skip("Docker is unavailable")
    patch = pytest.MonkeyPatch()
    patch.setenv("DOCKER_HOST", host)
    patch.setenv("TESTCONTAINERS_RYUK_DISABLED", "true")
    password = secrets.token_hex(12)  # a throwaway container's, generated per run
    container = postgres.PostgresContainer(
        IMAGE, username="asbuilt", password=password, dbname="asbuilt", driver=None
    )
    container.start()
    try:
        port = container.get_exposed_port(5432)
        yield f"postgresql://asbuilt:{password}@{container.get_container_host_ip()}:{port}/asbuilt"
    finally:
        container.stop()
        patch.undo()


@pytest.fixture
def pg_store(pg_dsn):
    from prototypes.b_postgres.store import PostgresStore

    store = PostgresStore(pg_dsn, schema="contract")
    store.reset()
    yield store
    store.close()


@pytest.mark.parametrize("check", CHECKS, ids=[c.__name__ for c in CHECKS])
def test_postgres_store_contract(pg_store, check):
    check(pg_store)


def test_schema_applies_from_nothing_and_resets(pg_dsn):
    from prototypes.b_postgres.store import PostgresStore

    store = PostgresStore(pg_dsn, schema="fresh")
    tables = {
        r["table_name"]
        for r in store._q(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'fresh'"
        )
    }
    assert tables == {
        "source",
        "document",
        "entity",
        "entity_relation",
        "fact",
        "fact_entity",
        "citation",
        "contradiction",
        "snapshot",
    }
    store.snapshot("x", step="c1")
    store.reset()
    assert store.last_step() is None
    store.close()


@pytest.mark.fixture
def test_real_fixture_on_postgres_c5_then_c6(pg_dsn, tmp_path: Path, monkeypatch):
    """The spec's integration test: no model, hash embedder, a real
    container. What the no-model path can see of staleness is asserted
    too: nothing, because no documented fact exists without extraction."""
    if not (SPIKE_ROOT / "truth" / "facts.yaml").is_file():
        pytest.skip("real fixture not present")
    from prototypes.b_postgres import Prototype
    from prototypes.b_postgres.store import PostgresStore

    monkeypatch.setenv("ASBUILT_B_NO_MODEL", "1")
    monkeypatch.setenv("ASBUILT_EMBED", "fake")
    monkeypatch.setenv("ASBUILT_B_BUILT", str(tmp_path / "built"))
    build(SPIKE_ROOT, tmp_path / "built")
    store = PostgresStore(pg_dsn, schema="integration")
    prototype = Prototype(store=store)

    report = prototype.ingest(assemble_ingest_root(SPIKE_ROOT, "c5", tmp_path / "c5"), ENTITY_KINDS)
    assert report.services == ("postgres",) and report.calls == 0
    (pair,) = prototype.contradictions("lost-bike-fee")
    assert {pair.a.statement, pair.b.statement} == {
        "Lost bike fee $100.00.",
        "Lost bike fee is $150.00.",
    }
    assert pair.winner.statement == "Lost bike fee is $150.00."
    assert any(c.document == "run/pytest-c5-rerun" for c in pair.a.citations + pair.b.citations)

    prototype.ingest(assemble_ingest_root(SPIKE_ROOT, "c6", tmp_path / "c6"), ENTITY_KINDS, True)
    assert prototype.last_ingest["steps"] == ["c6"]
    top = prototype.explain("lost bike fee")[0]
    assert top.tier == Tier.EXECUTED and "150" in top.statement
    assert any(c.document.startswith("run/pytest-c6") for c in top.citations)
    # One fact for the $150 claim, from the code constant's step (c5), not the test's (c6).
    assert top.valid_from == datetime.fromisoformat("2026-07-22T14:00:00-04:00")
    assert "code/farebox/pricing.py" in {c.document for c in top.citations}
    assert len(prototype.contradictions("lost-bike-fee")) == 1
    assert prototype.last_ingest["documents_extracted"] == 0
    assert prototype.stale(datetime.fromisoformat("2025-01-01T00:00:00+00:00")) == []

    full = Prototype(store=PostgresStore(pg_dsn, schema="integration_full"))
    full.ingest(assemble_ingest_root(SPIKE_ROOT, "c6", tmp_path / "c6-full"), ENTITY_KINDS)
    assert full.last_ingest["steps"] == ["c1", "c2", "c3", "c4", "c5", "c6"]
    assert [f.statement for f in full.explain("lost bike fee")] == [
        f.statement for f in prototype.explain("lost bike fee")
    ]
    assert len(full.contradictions()) == len(prototype.contradictions())
