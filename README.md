rapidsn7 PLC Monitor
====================
Runs on a Raspberry Pi (or any Linux box) on the same LAN as the PLC.
Uses snap7/python-snap7 to talk S7 and logs traffic to a local SQLite DB.

Quick start
-----------
1. Copy this folder to the Pi.
2. Install deps with uv:  ./setup.sh
   (or manually: uv venv .venv && uv pip install -r requirements.txt --python .venv/bin/python)
   On Pi:  sudo apt-get install build-essential libsnap7-dev
3. Copy config.example.json to config.json and edit PLC IP / DB list.
4. Run:
       python monitor.py          # console mode
       python viewer/app.py        # web dashboard on :5000

What it does
------------
- Connects to the PLC (CPU 1512SP-1 PN / ET 200SP)
- Reads the DBs/addresses you list in config.json
- Logs every read/write request and result to plc_log.db
- Optional: passive packet capture via tcpdump (requires sudo)
