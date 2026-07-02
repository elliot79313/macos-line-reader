from datetime import datetime

from line_mac_reader.state import StateStore
from line_mac_reader.utils_time import tzinfo_for

TZ = tzinfo_for("Asia/Taipei")


def test_roundtrip(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    assert store.get_last_read("王小明") is None
    when = datetime(2026, 7, 2, 14, 30, tzinfo=TZ)
    store.set_last_read("王小明", when)
    assert store.get_last_read("王小明") == when
    store.close()


def test_upsert_overwrites(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    t1 = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)
    t2 = datetime(2026, 7, 2, 9, 0, tzinfo=TZ)
    store.set_last_read("k", t1)
    store.set_last_read("k", t2)
    assert store.get_last_read("k") == t2
    store.close()


def test_reset(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.set_last_read("k", datetime(2026, 7, 1, tzinfo=TZ))
    store.reset()
    assert store.get_last_read("k") is None
    store.close()


def test_persists_across_instances(tmp_path):
    path = tmp_path / "state.sqlite3"
    when = datetime(2026, 7, 2, 14, 30, tzinfo=TZ)
    s1 = StateStore(path)
    s1.set_last_read("k", when)
    s1.close()
    s2 = StateStore(path)
    assert s2.get_last_read("k") == when
    s2.close()
