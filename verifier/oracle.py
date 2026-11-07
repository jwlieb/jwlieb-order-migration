"""Independent relational projection from pinned legacy records."""

import json


def expected(raw):
    if raw["scenario"] == "invalid":
        return {"rejected": True, "state_unchanged": True}
    lines = []
    orders = []
    for oid, customer, encoded in raw["orders"]:
        orders.append([oid, customer])
        for number, item in enumerate(json.loads(encoded)):
            lines.append([oid, number, item["sku"], item["quantity"], item["unit_cents"]])
    return {
        "state": {
            "version": 2,
            "rows": {"customers": raw["customers"], "orders": sorted(orders), "order_items": sorted(lines)},
            "columns": {
                "customers": [["id", "INTEGER", 0, 1], ["name", "TEXT", 1, 0]],
                "orders": [["id", "INTEGER", 0, 1], ["customer_id", "INTEGER", 1, 0]],
                "order_items": [
                    ["order_id", "INTEGER", 1, 1],
                    ["line_no", "INTEGER", 1, 2],
                    ["sku", "TEXT", 1, 0],
                    ["quantity", "INTEGER", 1, 0],
                    ["unit_cents", "INTEGER", 1, 0],
                ],
            },
            "foreign_key_errors": [],
        },
        "first_error": None,
        "rerun_identical": True,
        "constraints": [True] * 5 if raw["orders"] else [],
        "interruption_atomic": True,
        "recovered": True,
    }
