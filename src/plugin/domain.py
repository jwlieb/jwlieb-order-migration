"""Transactional SQLite order normalization."""

import json
import sqlite3
from pathlib import Path
from plugin.worker import run

STARTER = {
    "migration.py": """import json

def migrate(conn, checkpoint):
    # TODO: migrate version 1 to 2 atomically, preserve IDs, and support reruns.
    conn.execute("CREATE TABLE IF NOT EXISTS order_items(order_id INTEGER, line_no INTEGER, sku TEXT)")
    conn.commit()
"""
}
RESULT_FILES = ["results/orders.sqlite"]
SPEC = """Write migration.py exposing migrate(conn, checkpoint) for the supplied SQLite connection. Start at PRAGMA user_version=1: customers(id INTEGER PRIMARY KEY,name TEXT NOT NULL), orders(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL REFERENCES customers(id),items_json TEXT NOT NULL).
Version 2 will preserve customers and orders IDs/customer_id, drop orders.items_json, create order_items(order_id INTEGER NOT NULL REFERENCES orders(id),line_no INTEGER NOT NULL,sku TEXT NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>0),unit_cents INTEGER NOT NULL CHECK(unit_cents>=0),PRIMARY KEY(order_id,line_no)), then set user_version=2.
Each JSON array element has sku, quantity and unit_cents; line_no is its zero-based position, including repeated SKUs. Empty arrays are valid. Invalid JSON, empty SKU, non-integer/bool or out-of-range quantities/prices, or orphan customer references will abort the whole migration leaving both schema and records unchanged. A version-2 rerun will be a no-op. All DDL/DML must be one transaction. Call checkpoint() after each inserted line; injected failure must roll back, and a subsequent rerun must work. Do not catch and suppress injected RuntimeError.
Only migration.py is editable. Use json/typing imports; the connection is supplied. No filesystem/process/network access, connection creation, executescript, authorizer/progress changes, or reflection. assess checks a fresh database, rerun, and injected interruption; standard data has at least two lines. Submit the final assessment exactly."""


def fixture(scenario, seed):
    customers = [[1, "Acme"], [2, "North Supply"], [3, f"Customer {seed}"]]
    orders = []
    count = 0 if scenario == "empty" else 12
    for i in range(count):
        items = [
            {"sku": f"SKU-{(seed + i + j) % 5}", "quantity": (i + j) % 4 + 1, "unit_cents": seed * 3 + 100 + j}
            for j in range(i % 4)
        ]
        orders.append([100 + i, i % 3 + 1, json.dumps(items)])
    if scenario == "boundary":
        orders += [
            [
                999,
                1,
                json.dumps(
                    [
                        {"sku": "duplicate", "quantity": 1, "unit_cents": 0},
                        {"sku": "duplicate", "quantity": 2**20, "unit_cents": 2**20},
                    ]
                ),
            ]
        ]
    if scenario == "invalid":
        orders[2][2] = "not valid JSON"
    return {"scenario": scenario, "seed": seed, "customers": customers, "orders": orders}


def initialize(path, raw):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE customers(id INTEGER PRIMARY KEY,name TEXT NOT NULL); CREATE TABLE orders(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL REFERENCES customers(id),items_json TEXT NOT NULL); PRAGMA user_version=1;"
    )
    conn.executemany("INSERT INTO customers VALUES (?,?)", raw["customers"])
    conn.executemany("INSERT INTO orders VALUES (?,?,?)", raw["orders"])
    conn.commit()
    conn.close()


def snapshot(path):
    c = sqlite3.connect(path)
    version = c.execute("PRAGMA user_version").fetchone()[0]
    tables = [
        r[0]
        for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    rows = {t: [list(r) for r in c.execute(f'SELECT * FROM "{t}" ORDER BY 1,2')] for t in tables}
    columns = {t: [[r[1], r[2], r[3], r[5]] for r in c.execute(f'PRAGMA table_info("{t}")')] for t in tables}
    fks = [list(r) for r in c.execute("PRAGMA foreign_key_check")]
    c.close()
    return {"version": version, "rows": rows, "columns": columns, "foreign_key_errors": fks}


def execute(source, path, fail):
    return run(
        source,
        {"db_path": str(path), "fail": fail},
        """
allowed_db = request["db_path"]
conn = sqlite3.connect(allowed_db)
conn.execute("PRAGMA foreign_keys=ON")
def authorizer(action, arg1, arg2, database, trigger):
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) or action == sqlite3.SQLITE_FUNCTION and arg2 in ("load_extension","readfile","writefile"):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK
conn.set_authorizer(authorizer)
checkpoint_count = [0]
def checkpoint():
    checkpoint_count[0] += 1
    if request["fail"] and checkpoint_count[0] == 1:
        raise RuntimeError("injected interruption")
""",
        """
error = None
try:
    namespace["migrate"](conn, checkpoint)
except Exception as failure:
    error = type(failure).__name__
conn.close()
print(json.dumps({"error":error,"checkpoints":checkpoint_count[0]}))
""",
    )


def constraint_checks(path):
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys=ON")
    checks = []
    for row in [
        (999999, 0, "x", 1, 1),
        (100, 999, "x", 0, 1),
        (100, 999, "x", 1, -1),
        (100, 999, None, 1, 1),
        (100, 999, "x", None, 1),
    ]:
        c.execute("SAVEPOINT probe")
        try:
            c.execute("INSERT INTO order_items VALUES (?,?,?,?,?)", row)
            checks.append(False)
        except sqlite3.IntegrityError:
            checks.append(True)
        c.execute("ROLLBACK TO probe")
        c.execute("RELEASE probe")
    c.close()
    return checks


def measure(files, raw, workspace):
    results = Path(workspace) / "results"
    results.mkdir(exist_ok=True)
    path = results / "orders.sqlite"
    if path.exists():
        path.unlink()
    initialize(path, raw)
    before = snapshot(path)
    first = execute(files["migration.py"], path, False)
    after = snapshot(path)
    invalid = raw["scenario"] == "invalid"
    if invalid:
        return {"rejected": first["error"] is not None, "state_unchanged": after == before}
    rerun = execute(files["migration.py"], path, False)
    after_rerun = snapshot(path)
    interrupted = results / "interrupted.sqlite"
    if interrupted.exists():
        interrupted.unlink()
    initialize(interrupted, raw)
    original = snapshot(interrupted)
    interrupted_result = execute(files["migration.py"], interrupted, bool(raw["orders"]))
    interrupted_state = snapshot(interrupted)
    recovered = execute(files["migration.py"], interrupted, False)
    return {
        "state": after,
        "first_error": first["error"],
        "rerun_identical": rerun["error"] is None and after_rerun == after,
        "constraints": constraint_checks(path) if raw["orders"] else [],
        "interruption_atomic": (interrupted_result["error"] == "RuntimeError" and interrupted_state == original)
        if raw["orders"]
        else True,
        "recovered": recovered["error"] is None and snapshot(interrupted) == after,
    }
