#!/usr/bin/env python3
"""Raspberry Pi-side PLC monitor with embedded web viewer.

- Polls the PLC using python-snap7
- Logs reads/writes to SQLite (plc_log.db)
- Serves a minimal web dashboard on http://<host>:5000 by default

Usage:
    python monitor.py
"""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import snap7
from flask import Flask, render_template_string, g

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

app = Flask(__name__)


def load_config():
    data = json.loads(CONFIG_PATH.read_text())
    data["plc"].setdefault("rack", 0)
    data["plc"].setdefault("slot", 1)
    data.setdefault("igt_id", 1)
    data.setdefault("db", 1000 + int(data["igt_id"]))
    if "candidate_dbs" not in data:
        data["candidate_dbs"] = [int(data["db"])]
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


def _now():
    return datetime.utcnow().isoformat() + "Z"


def _decode_note(raw_hex: str, start: int):
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    word = int.from_bytes(data[:2], byteorder="big")
    if word == 0:
        return None
    if start in (300, 302):
        return STATUS_TEST.get(word, f"StatusTest={word}")
    if start in (
        304,
        306,
        308,
        310,
        332,
        334,
        336,
        338,
        340,
        342,
        344,
        346,
        348,
    ):
        return ERR_CODE.get(word, f"ErrCode={word}")
    return None


def read_db(client, cfg):
    items = []
    default_db = int(cfg["db"])
    for item in cfg.get("watch", []):
        start = int(item["start"])
        size = int(item["size"])
        pattern_db = int(item.get("db", default_db))
        dbs = [pattern_db] + [d for d in cfg["candidate_dbs"] if d != pattern_db]

        for db_number in dbs:
            try:
                raw = client.db_read(db_number, start, size)
                note = _decode_note(raw.hex(), start)
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "INSERT INTO events (ts, direction, db, start, size, raw_hex, note) VALUES (?,?,?,?,?,?,?)",
                    (
                        _now(),
                        "read",
                        db_number,
                        start,
                        size,
                        raw.hex(),
                        note,
                    ),
                )
                conn.commit()
                items.append({"db": db_number, "start": start, "size": size, "note": note})
                break
            except Exception as e:
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "INSERT INTO errors (ts, db, start, size, error) VALUES (?,?,?,?,?)",
                    (
                        _now(),
                        db_number,
                        start,
                        size,
                        str(e),
                    ),
                )
                conn.commit()
                continue
    return items


# =============================================================================
# Web viewer
# =============================================================================

INDEX_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>PLC Monitor</title>
<style>
  :root{
    --bg:#0b0f14;
    --panel:#111820;
    --line:#1f2937;
    --text:#e5e7eb;
    --muted:#9aa3b2;
    --accent:#22c55e;
    --danger:#ef4444;
    --warn:#f59e0b;
  }
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--text);font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace}
  header{
    display:flex;align-items:center;justify-content:space-between;
    padding:16px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#0f1620,#0b0f14);
    position:sticky;top:0;z-index:5;
  }
  header h1{margin:0;font-size:16px;letter-spacing:.08em;text-transform:uppercase;color:var(--text)}
  header .pill{font-size:11px;padding:4px 8px;border-radius:999px;background:#0b2a16;color:var(--accent);border:1px solid #174e2b}
  .wrap{max-width:1200px;margin:0 auto;padding:16px}
  .toolbar{display:flex;gap:8px;margin-bottom:12px}
  button,form button{
    background:#111820;color:var(--text);border:1px solid var(--line);padding:8px 12px;border-radius:8px;cursor:pointer;
  }
  button:hover,form button:hover{border-color:#2a3647}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--muted);font-weight:500;font-size:11px;letter-spacing:.1em;text-transform:uppercase}
  tr:hover td{background:#0c1320}
  .event .ts{color:#b8c0cc}
  .event .dir{color:#93c5fd}
  .event .addr{color:#a5b4fc}
  .event .note{color:#fcd34d}
  .error .ts{color:#b8c0cc}
  .error .msg{color:#fca5a5}
  .pill{display:inline-block;font-size:11px;padding:2px 8px;border-radius:999px;background:#0b2a16;color:var(--accent);border:1px solid #174e2b}
</style>
</head>
<body>
<div class="wrap">
  <div class="toolbar">
    <form method="post" action="/clear" style="display:inline">
      <button type="submit">Clear log</button>
    </form>
  </div>
  <h2 style="margin-top:0">Events</h2>
  <table>
    <thead><tr><th>Time</th><th>Direction</th><th>DB</th><th>Start</th><th>Size</th><th>Note</th></tr></thead>
    <tbody>
    {% for row in events %}
    <tr class="event">
      <td class="ts">{{ row['ts'] }}</td>
      <td class="dir">{{ row['direction'] }}</td>
      <td class="addr">{{ row['db'] }}:{{ row['start'] }}</td>
      <td>{{ row['size'] }}</td>
      <td class="note">{{ row['note'] or '' }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6" style="color:var(--muted)">No events yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2 style="margin-top:16px">Errors</h2>
  <table>
    <thead><tr><th>Time</th><th>DB</th><th>Start</th><th>Size</th><th>Error</th></tr></thead>
    <tbody>
    {% for row in errors %}
    <tr class="error">
      <td class="ts">{{ row['ts'] }}</td>
      <td class="addr">{{ row['db'] }}:{{ row['start'] }}</td>
      <td>{{ row['size'] }}</td>
      <td class="msg">{{ row['error'] }}</td>
    </tr>
    {% else %}
    <tr><td colspan="5" style="color:var(--muted)">No errors.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div>
</body>
</html>
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.route("/", methods=["GET"])
def index():
    db = get_db()
    events = db.execute(
        "SELECT ts, direction, db, start, size, note FROM events ORDER BY id DESC LIMIT 200"
    ).fetchall()
    errors = db.execute(
        "SELECT ts, db, start, size, error FROM errors ORDER BY id DESC LIMIT 200"
    ).fetchall()
    return render_template_string(INDEX_HTML, events=events, errors=errors)


@app.route("/clear", methods=["POST"])
def clear():
    db = get_db()
    db.execute("DELETE FROM events")
    db.execute("DELETE FROM errors")
    db.commit()
    return index()


# =============================================================================
# Main
# =============================================================================

def main():
    cfg = load_config()
    init_db()

    plc_client = snap7.client.Client()
    try:
        plc_client.connect(
            cfg["plc"]["ip"],
            int(cfg["plc"].get("rack", 0)),
            int(cfg["plc"].get("slot", 1)),
        )
    except Exception as e:
        raise SystemExit(f"PLC connect failed: {e}")

    host = cfg.get("web", {}).get("host", "0.0.0.0")
    port = int(cfg.get("web", {}).get("port", 5000))

    # Start Flask in a background thread.
    import threading

    threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
        daemon=True,
    ).start()

    try:
        while True:
            read_db(plc_client, cfg)
            time.sleep(float(cfg.get("poll_interval_s", 2)))
    finally:
        plc_client.destroy()


if __name__ == "__main__":
    main()
