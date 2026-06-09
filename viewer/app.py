#!/usr/bin/env python3
"""Minimal web dashboard for PLC monitor logs."""

from flask import Flask, render_template_string, g
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_PATH = BASE / "plc_log.db"

app = Flask(__name__)


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


INDEX_HTML = """
<!doctype html>
<title>PLC Monitor</title>
<h1>PLC Monitor</h1>
<form method="post" action="/clear">
  <button type="submit">Clear log</button>
</form>
<table border="1" cellpadding="4" cellspacing="0">
  <tr>
    <th>Time</th>
    <th>Direction</th>
    <th>DB</th>
    <th>Start</th>
    <th>Size</th>
    <th>Hex</th>
  </tr>
{% for row in rows %}
  <tr>
    <td>{{ row['ts'] }}</td>
    <td>{{ row['direction'] }}</td>
    <td>{{ row['db'] }}</td>
    <td>{{ row['start'] }}</td>
    <td>{{ row['size'] }}</td>
    <td>{{ row['raw_hex'] }}</td>
  </tr>
{% endfor %}
</table>
"""


@app.route("/", methods=["GET"])
def index():
    db = get_db()
    rows = db.execute(
        "SELECT ts, direction, db, start, size, raw_hex FROM events ORDER BY id DESC LIMIT 200"
    ).fetchall()
    return render_template_string(INDEX_HTML, rows=rows)


@app.route("/clear", methods=["POST"])
def clear():
    db = get_db()
    db.execute("DELETE FROM events")
    db.commit()
    return index()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=True)
