#!/usr/bin/env python3
"""Minimal write API for BatchID / DBW230 writes."""
from flask import Flask, request, jsonify
import snap7
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE / "config.json"

app = Flask(__name__)


def load_config():
    import json
    return json.loads(CONFIG_PATH.read_text())


@app.route("/set", methods=["POST", "GET"])
def set_batchid():
    cfg = load_config()
    value = request.args.get("batchid") or request.values.get("batchid")
    if value is None:
        return jsonify({"error": "missing batchid"}), 400
    try:
        batch_id = int(value)
    except ValueError:
        return jsonify({"error": "batchid must be integer"}), 400

    igt_id = int(cfg.get("igt_id", 1))
    db_number = int(cfg.get("db", 1000 + igt_id))
    client = snap7.client.Client()
    try:
        client.connect(cfg["plc"]["ip"], cfg["plc"].get("rack", 0), cfg["plc"].get("slot", 1))
        payload = batch_id.to_bytes(2, byteorder="big")
        client.db_write(db_number, 230, payload)
        return jsonify({"ok": True, "batchid": batch_id, "db": db_number, "offset": 230})
    finally:
        client.destroy()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
