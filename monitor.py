#!/usr/bin/env python3
"""Raspberry Pi-side PLC monitor using python-snap7 + SQLite."""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import snap7
from snap7.util import get_int, get_dword, get_real, get_string
from snap7.type import Areas


DB_PATH = Path(__file__).with_name("plc_log.db")
CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config():
    data = json.loads(CONFIG_PATH.read_text())
    data["plc"].setdefault("rack", 0)
    data["plc"].setdefault("slot", 1)
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


def read_db(client, db_number, start, size):
    raw = client.db_read(db_number, start, size)
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
            None,
        ),
    )
    conn.commit()
    return raw


def main():
    cfg = load_config()
    conn = init_db()

    client = snap7.client.Client()
    try:
        client.connect(cfg["plc"]["ip"], cfg["plc"]["rack"], cfg["plc"]["slot"])
    except Exception as e:
        raise SystemExit(f"PLC connect failed: {e}")

    try:
        while True:
            for item in cfg.get("watch", []):
                read_db(
                    client,
                    int(item["db"]),
                    int(item["start"]),
                    int(item["size"]),
                )
            time.sleep(float(cfg.get("poll_interval_s", 2)))
    finally:
        client.destroy()


if __name__ == "__main__":
    main()
