#!/usr/bin/env python3
"""
Combine the StarterBot purchase BOM (doc/gobilda-3200-2627-0004/bom_purchase.csv) with the
BIOBUZZ delta (bom_delta.csv) into bom_biobuzz_bot.csv.

    python3 make_bom.py
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STARTER = os.path.join(ROOT, "..", "gobilda-3200-2627-0004", "bom_purchase.csv")
DELTA = os.path.join(ROOT, "bom_delta.csv")
OUT = os.path.join(ROOT, "bom_biobuzz_bot.csv")

# Nothing from the kit is removed: the towers simply move two holes outboard on the base rails.
REMOVED = {}


def main():
    rows = {}
    with open(STARTER) as f:
        for r in csv.DictReader(f):
            rows[r["sku"]] = {"sku": r["sku"], "name": r["name"], "category": r["category"],
                              "starter_kit_qty": int(r["qty"]), "added_qty": 0, "removed_qty": 0,
                              "purpose": "", "source": r["name_source"]}
    with open(DELTA) as f:
        for r in csv.DictReader(f):
            row = rows.setdefault(r["sku"], {"sku": r["sku"], "name": r["name"], "category": "",
                                             "starter_kit_qty": 0, "added_qty": 0, "removed_qty": 0,
                                             "purpose": "", "source": r["source"]})
            row["added_qty"] += int(r["qty"])
            row["purpose"] = r["purpose"]
    for sku, q in REMOVED.items():
        rows[sku]["removed_qty"] += q
        rows[sku]["purpose"] = "removed"
    for row in rows.values():
        row["total_qty"] = row["starter_kit_qty"] + row["added_qty"] - row["removed_qty"]
    order = ["sku", "name", "category", "starter_kit_qty", "added_qty", "removed_qty", "total_qty", "purpose", "source"]
    out = sorted(rows.values(), key=lambda r: (r["added_qty"] == 0, r["sku"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=order)
        w.writeheader()
        w.writerows(out)
    added = [r for r in out if r["added_qty"]]
    print(f"{len(out)} lines, {len(added)} with additions, {sum(r['total_qty'] for r in out)} units total")


if __name__ == "__main__":
    main()
