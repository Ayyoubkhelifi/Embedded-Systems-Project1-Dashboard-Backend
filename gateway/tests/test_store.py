import time

import pytest

from gateway_pkg.store import GatewayStore


def test_dedup_first_and_replay(store):
    assert store.is_new(1, 5) is True
    assert store.is_new(1, 5) is False
    assert store.is_new(1, 4) is False
    assert store.is_new(1, 6) is True


def test_dedup_persists_across_reopen(store, tmp_path):
    path = str(tmp_path / "gateway.sqlite3")
    store.is_new(1, 100)
    store.close()
    reopened = GatewayStore(path)
    assert reopened.is_new(1, 100) is False
    assert reopened.is_new(1, 101) is True
    reopened.close()


def test_dedup_seq_wraparound(store):
    assert store.is_new(1, 0xFFFFFFFF - 2) is True
    assert store.is_new(1, 0) is True  # wrapped: 0 > max within window logic
    # after wrap, pre-wrap sequences look stale again
    assert store.is_new(1, 0xFFFFFFFF) is False


def test_buffer_enqueue_peek_remove(store):
    store.enqueue(10, 1, {"device_id": 10, "seq": 1})
    store.enqueue(10, 2, {"device_id": 10, "seq": 2})
    rows = store.peek()
    assert len(rows) == 2
    assert store.buffered_count() == 2
    store.remove(rows[0][0])
    assert store.buffered_count() == 1
    remaining = store.peek()
    assert remaining[0][3].endswith('"seq": 2}')  # oldest-first FIFO


def test_buffer_unique_device_seq(store):
    store.enqueue(10, 3, {"seq": 3})
    store.enqueue(10, 3, {"seq": 3})
    assert store.buffered_count() == 1


def test_diagnostic_snapshot(store):
    store.is_new(1, 1)
    store.enqueue(1, 1, {"seq": 1})
    snap = store.diagnostic_snapshot()
    assert snap["buffered"] == 1
    assert snap["tracked_devices"] == 1
    assert snap["oldest_queued_at"] is not None


def test_repeated_attempts_tracked(store):
    store.enqueue(1, 9, {"seq": 9})
    store.mark_attempt(store.peek()[0][0])
    store.mark_attempt(store.peek()[0][0])
    assert store.peek()[0][4] == 2
