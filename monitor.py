#!/usr/bin/env python3
"""Raspberry Pi-side PLC monitor using python-snap7 + SQLite."""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import snap7


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
    data["plc"].setdefault("rack", 0)
    data["plc"].setdefault("slot", 1)
    data.setdefault("igt_id", 1)
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
    conn.commit()
    return conn


def _decode_note(raw_hex: str, start: int) -> str | None:
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError:
        return None
    if start not in (300, 304, 304 + 2, 332, 336, 342, 344, 346):
        return None
    # All protocol words here are INT16 at the specified DBW offset.
    if len(data) < 2:
        return None
    word = int.from_bytes(data[:2], byteorder="big")
    if word == 0:
        return None
    if start in (300,):
        return STATUS_TEST.get(word, f"StatusTest={word}")
    if start in (304, 336, 342, 344, 346):
        return ERR_CODE.get(word, f"ErrCode={word}")
    return None


def read_db(client, cfg):
    igt_id = int(cfg.get("igt_id", 1))
    db = 1000 + igt_id
    for item in cfg.get("watch", []):
        db_number = int(item.get("db", db))
        start = int(item["start"])
        size = int(item["size"])
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


def main():
    cfg = load_config()
    init_db()

    client = snap7.client.Client()
    try:
        client.connect(cfg["plc"]["ip"], cfg["plc"]["rack"], cfg["plc"]["slot"])
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
