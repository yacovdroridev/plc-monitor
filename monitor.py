#!/usr/bin/env python3
"""Raspberry Pi-side PLC monitor with embedded web viewer.

- Polls the PLC using python-snap7
- Logs reads/writes to SQLite (plc_log.db)
- Serves a dark register dashboard on http://<host>:5000 by default

Usage:
    python monitor.py
"""

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import snap7
from flask import Flask, render_template_string, g, jsonify, request

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
    return datetime.now(timezone.utc).isoformat()


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
                items.append(
                    {"db": db_number, "start": start, "size": size, "note": note}
                )
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
    --input-bg:#0a101a;
  }
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--text);font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono",monospace}
  header{
    display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;
    padding:16px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#0f1620,#0b0f14);
    position:sticky;top:0;z-index:5;
  }
  header h1{margin:0;font-size:16px;letter-spacing:.08em;text-transform:uppercase;color:var(--text)}
  .status{display:flex;gap:10px;align-items:center}
  .pill{font-size:11px;padding:4px 8px;border-radius:999px;background:#0b2a16;color:var(--accent);border:1px solid #174e2b}
  .pill.dead{background:#2a0f0f;color:var(--danger);border-color:#4f1f1f}
  .wrap{max-width:1200px;margin:0 auto;padding:16px}
  .toolbar{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
  button,form button{
    background:#111820;color:var(--text);border:1px solid var(--line);padding:8px 12px;border-radius:8px;cursor:pointer;
  }
  button:hover,form button:hover{border-color:#2a3647}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:middle}
  th{color:var(--muted);font-weight:500;font-size:11px;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
  tr:hover td{background:#0c1320}
  .addr{color:#a5b4fc}
  .name{color:#e5e7eb}
  .desc{color:#9aa3b2}
  .value{font-weight:700}
  input[type="number"]{
    background:var(--input-bg);color:var(--text);border:1px solid var(--line);
    padding:6px 8px;border-radius:6px;width:110px;font-family:inherit;
  }
  input[type="number"]:focus{outline:none;border-color:#334155}
  .row-actions{display:flex;gap:6px}
  .row-actions button{padding:4px 8px;font-size:11px}
  .muted{color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <div class="toolbar">
    <form method="post" action="/clear" style="display:inline">
      <button type="submit">Clear log</button>
    </form>
    <button onclick="location.reload()">Refresh</button>
  </div>

  <h2 style="margin-top:0">PLC Registers (read from PLC)</h2>
  <div class="status">
    <div class="pill" id="alive-pill">ALIVE</div>
    <div class="pill" id="db-pill">DB {{ db }}</div>
  </div>
  <p class="muted" style="margin-top:6px">PLC: {{ plc_ip }}</p>

  <h2 style="margin-top:16px">Register Map</h2>
  <table>
    <thead>
      <tr>
        <th>Address</th>
        <th>Name</th>
        <th>Description</th>
        <th>Value</th>
        <th>Set</th>
      </tr>
    </thead>
    <tbody>
    {% for item in registers %}
    <tr>
      <td class="addr">DBW{{ item.start }}</td>
      <td class="name">{{ item.name }}</td>
      <td class="desc">{{ item.desc }}</td>
      <td class="value" id="val-{{ item.start }}">{{ item.value if item.value is not none else '—' }}</td>
      <td>
        <form method="post" action="/write" style="display:inline">
          <input type="hidden" name="start" value="{{ item.start }}" />
          <input type="number" name="value" value="{{ item.value if item.value is not none else 0 }}" />
          <button type="submit">Write</button>
        </form>
      </td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<script>
  fetch('/api/status').then(r=>r.json()).then(d=>{
    const pill=document.getElementById('alive-pill');
    if(d.recent_error){
      pill.classList.add('dead'); pill.textContent='ERROR';
    }
  });
</script>
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
    cfg = load_config()
    db = get_db()

    default_db = int(cfg.get("db", 1001))
    row = db.execute(
        "SELECT db FROM events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    active_db = row["db"] if row else default_db

    register_map = [
        {"start": 200, "name": "RTC_sec", "desc": "PLC heartbeat / live connection", "scale": None},
        {"start": 202, "name": "Port_Enable", "desc": "0=disable / 1=enable test start", "scale": None},
        {"start": 204, "name": "Port_Status", "desc": "0=---- / 1=enable / 2=disable / 3=limit / 4=missing", "scale": None},
        {"start": 208, "name": "GlvPressSP", "desc": "Glove pressure SP (Pa)", "scale": None},
        {"start": 210, "name": "GlvPressThold", "desc": "Glove pressure threshold (Pa)", "scale": None},
        {"start": 212, "name": "GlvPressDropSet", "desc": "Glove pressure drop setting (Pa)", "scale": None},
        {"start": 214, "name": "GlvStabilSec", "desc": "Glove stabilization time (Sec)", "scale": None},
        {"start": 216, "name": "GlvLeakSec", "desc": "Glove leak test time (Sec)", "scale": None},
        {"start": 218, "name": "GlvBuildSec", "desc": "Glove max build time (Sec)", "scale": None},
        {"start": 220, "name": "SealPressSP", "desc": "Seal pressure SP (Bar/10)", "scale": "÷10"},
        {"start": 222, "name": "SealPressDropSet", "desc": "Seal pressure drop setting (Bar/10)", "scale": "÷10"},
        {"start": 224, "name": "SealPressThold", "desc": "Seal pressure threshold (Bar/10)", "scale": "÷10"},
        {"start": 226, "name": "SealLeakSec", "desc": "Seal leak test time (Sec)", "scale": None},
        {"start": 228, "name": "SealBuildSec", "desc": "Seal max build time (Sec)", "scale": None},
        {"start": 230, "name": "BatchID", "desc": "Run number / batch", "scale": None},
        {"start": 232, "name": "TestMode", "desc": "0=PRF / 1=POST", "scale": None},
    ]

    latest = {}
    rows = db.execute(
        "SELECT db, start, raw_hex FROM events ORDER BY id DESC"
    ).fetchall()
    for r in rows:
        key = (int(r["db"]), int(r["start"]))
        if key not in latest:
            latest[key] = r["raw_hex"]
    for item in register_map:
        key = (active_db, item["start"])
        raw = latest.get(key)
        if raw and len(bytes.fromhex(raw)) >= 2:
            item["value"] = int.from_bytes(bytes.fromhex(raw)[:2], "big")
        else:
            item["value"] = None

    return render_template_string(
        INDEX_HTML, registers=register_map, db=active_db, plc_ip=cfg["plc"]["ip"]
    )


@app.route("/api/status")
def api_status():
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM errors ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return jsonify({"recent_error": bool(row)})


@app.route("/write", methods=["POST"])
def write():
    cfg = load_config()
    igt_id = int(cfg.get("igt_id", 1))
    db_number = int(cfg.get("db", 1000 + igt_id))
    start = int(request.form.get("start", "0"))
    value = int(request.form.get("value", "0"))

    client = snap7.client.Client()
    try:
        client.connect(
            cfg["plc"]["ip"],
            int(cfg["plc"].get("rack", 0)),
            int(cfg["plc"].get("slot", 1)),
        )
        payload = value.to_bytes(2, byteorder="big")
        client.db_write(db_number, start, payload)
        ok = True
        err = None
    except Exception as e:
        ok = False
        err = str(e)
    finally:
        client.destroy()

    if not ok:
        return jsonify({"ok": False, "error": err}), 500
    return index()


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
