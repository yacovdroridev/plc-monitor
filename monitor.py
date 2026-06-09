#!/usr/bin/env python3
"""Raspberry Pi-side PLC monitor using python-snap7 + SQLite."""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import snap7
from snap7.type import Areas


DB_PATH = Path(__file__).with_name("plc_log.db")
CONFIG_PATH = Path(__file__).with_name("config.json")

STATUS_TEST = {
    0: "------",
    1: "Ready for test",
    2: "Inflating gasket",
    3: "Inflating glove",
    4: "Glove in Testing",
    5: "Test successful",
    6: "Test failed",
}

ERR_CODE = {
    0: "------",
    1: "Maximum Glove test were performed",
    2: "Failed to build Gasket pressure",
    3: "Gasket Leak test failed",
    4: "Failed to build Glove pressure",
    5: "Gasket pressure fell below Threshold",
    6: "Glove pressure fell below Threshold",
    7: "Glove Test failed",
    8: "Err in IGT",
    9: "Missed report",
}


def load_config():
    data = json.loads(CONFIG_PATH.read_text())
    for k in ("rack", "slot"):
        data["plc"].setdefault(k, 0 if k == "rack" else 1)
    data.setdefault("igt_id", 1)
    # candidate_dbs: ordered list of DB numbers to try for read success.
    # If absent, defaults to [1000 + igt, 1000 + igt_id - 1].
    igt_id = int(data["igt_id"])
    if "candidate_dbs" not in data:
        default_dbs = [1000 + igt_id, 100 + igt_id]
        data["candidate_dbs"] = [db for db in default_dbs if db > 0]
    return data


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          direction TEXT NOT NULL,
          db INTEGER,
          start INTEGER,
          size INTEGER,
          raw_hex TEXT,
          note TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS errors (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          db INTEGER,
          start INTEGER,
          size INTEGER,
          error TEXT
        )
        """
    )
    conn.commit()
    return conn


def _decode_note(raw_hex: str, start: int):
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    word = int.from_bytes(data[:2], byteorder="big")
    if start in (300, 302):
        return STATUS_TEST.get(word, f"StatusTest={word}")
    if start in (304, 306, 308, 310, 332, 334, 336, 338, 340, 342, 344, 346, 348):
        return ERR_CODE.get(word, f"ErrCode={word}")
    return None


def read_db(client, cfg):
    igt_id = int(cfg.get("igt_id", 1))
    default_db = int(cfg.get("watch_default_db", 1000 + igt_id))
    candidates = [int(x) for x in cfg.get("candidate_dbs", [default_db])]
    items = []
    for item in cfg.get("watch", []):
        start = int(item["start"])
        size = int(item["size"])
        pattern_db = int(item.get("db", default_db))
        # Build queryset: try pattern_db first, then fallbacks.
        dbs = [pattern_db] + [d for d in candidates if d != pattern_db]
        for db_number in dbs:
            try:
                raw = client.db_read(db_number, start, size)
                note = _decode_note(raw.hex(), start)
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "INSERT INTO events (ts, direction, db, start, size, raw_hex, note) VALUES (?,?,?,?,?,?,?)",
                    (
                        datetime.utcnow().isoformat() + "Z",
                        "read",
                        db_number,
                        start,
                        size,
                        raw.hex(),
                        note,
                    ),
                )
                conn.commit()
                items.append((db_number, start, size, note))
                break
            except Exception as e:
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "INSERT INTO errors (ts, db, start, size, error) VALUES (?,?,?,?,?)",
                    (
                        datetime.utcnow().isoformat() + "Z",
                        db_number,
                        start,
                        size,
                        str(e),
                    ),
                )
                conn.commit()
                continue
    return items


def main():
    cfg = load_config()
    init_db()

    client = snap7.client.Client()
    try:
        client.connect(
            cfg["plc"]["ip"], int(cfg["plc"].get("rack", 0)), int(cfg["plc"].get("slot", 1))
        )
    except Exception as e:
        raise SystemExit(f"PLC connect failed: {e}")

    try:
        while True:
            read_db(client, cfg)
            time.sleep(float(cfg.get("poll_interval_s", 2)))
    finally:
        client.destroy()


if __name__ == "__main__":
    main()
