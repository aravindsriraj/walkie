import sqlite3


def test_init_moves_an_old_stepcast_db(tmp_path, monkeypatch):
    from app import store
    old = tmp_path / "stepcast.db"
    sqlite3.connect(old).execute("CREATE TABLE articles (id TEXT PRIMARY KEY, data TEXT, created_at TEXT)").connection.commit()
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_db", tmp_path / "walkie.db")
    store.init()
    assert (tmp_path / "walkie.db").exists() and not old.exists()
