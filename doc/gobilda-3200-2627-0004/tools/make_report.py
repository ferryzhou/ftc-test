#!/usr/bin/env python3
"""
Build BOM tables, charts and wireframe renders from the output of parse_step.py.

Usage:
    python3 make_report.py <parse_out_dir> <report_dir> [--no-render]

Reads  <parse_out_dir>/structure.json and geometry.npz plus sku_catalog.tsv
(next to this script). Writes CSV / Markdown tables, PNG figures and
assembly_tree.txt into <report_dir>.
"""
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- palette (validated categorical order, light surface) -------------------
SURFACE = "#fcfcfb"
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SEQ = "#2a78d6"
CATEGORIES = ["Structure", "Motion", "Actuators", "Wheels", "Fasteners", "Electronics", "Other"]
CAT_COLOR = {
    "Structure": "#2a78d6", "Motion": "#eb6834", "Actuators": "#1baf7a",
    "Wheels": "#eda100", "Fasteners": "#e87ba4", "Electronics": "#008300",
    "Other": "#898781",
}


def load_catalog():
    cat = {}
    with open(os.path.join(HERE, "sku_catalog.tsv")) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            cat[row["sku"]] = row
    return cat


def categorize(sku, name, label):
    n = (name or "").lower()
    l = (label or "").lower()
    series = sku[:4] if sku else ""
    if "motor" in n or "gearbox" in n or ("servo" in n and "servoblock" not in n and "hub shaft" not in n):
        return "Actuators"
    if any(k in n for k in ("wheel", "roller")):
        return "Wheels"
    if "battery" in n and "mount" not in n:
        return "Electronics"
    if any(k in n for k in ("bearing", "shaft", "hub", "collar", "gear", "sprocket", "pulley", "belt", "servoblock", "spline")):
        return "Motion"
    if any(k in n for k in ("screw", "nut", "washer", "zip tie", "strap", "e-clip", "shim")):
        return "Fasteners"
    if any(k in n for k in ("channel", "plate", "mount", "bracket", "standoff", "spacer", "block")):
        return "Structure"
    if series in ("5203", "5000", "5103", "2000"):
        return "Actuators"
    if series and series[0] == "1":
        return "Structure" if series < "1300" else "Motion"
    if series[:2] in ("28", "29"):
        return "Fasteners"
    if series[:2] in ("21", "22", "23"):
        return "Motion"
    if series[:2] == "36":
        return "Wheels"
    if series[:2] == "31":
        return "Electronics"
    # un-numbered internals: fall back to the CAD label
    if any(k in l for k in ("screw", "pin", "shim", "patch")):
        return "Fasteners"
    if any(k in l for k in ("roller", "tire", "core", "plate")):
        return "Wheels"
    if any(k in l for k in ("gearbox", "motor", "servo", "case", "encoder", "jst", "label", "wire")):
        return "Actuators"
    if l in ("or", "ir", "od", "id"):
        return "Motion"
    return "Other"


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    S = json.load(open(os.path.join(src, "structure.json")))
    P = S["products"]
    tree = S["tree"]
    for n in tree:
        n["product_key"] = str(n["product_key"])
    catalog = load_catalog()

    def name_of(sku):
        return catalog.get(sku, {}).get("name", "")

    def source_of(sku):
        return catalog.get(sku, {}).get("source", "unknown" if sku else "")

    def cat_of(key):
        p = P[key]
        return categorize(p["sku"], name_of(p["sku"]), p["label"])

    # ---- rebuild parent/child structure from the flattened tree ------------
    stack = []
    parent_of = [None] * len(tree)
    for i, n in enumerate(tree):
        d = n["depth"]
        stack = stack[:d]
        parent_of[i] = stack[-1] if stack else None
        stack.append(i)
    children_of = defaultdict(list)
    for i, p in enumerate(parent_of):
        if p is not None:
            children_of[p].append(i)

    # ---- 1. purchase-level BOM ----------------------------------------------
    # Walk from the root. A node that carries a goBILDA SKU is a purchasable
    # line. Nodes without a SKU (loose "Hardware" folders, zip-tie groups) are
    # expanded. Nodes labelled "w.Hardware"/"assembly" are counted AND expanded
    # because the designer modelled the extra hardware as separate SKUs.
    # SKUs sold as a kit whose modelled "w.Hardware" children ship in the box.
    KIT_SKUS = {"3217-0001-2501"}

    def is_group(n):
        l = n["label"].lower()
        if n["sku"] in KIT_SKUS:
            return False
        return (not n["sku"]) or ("w." in l) or ("assembly" in l)

    purchase = Counter()
    included_hw = Counter()   # SKU'd children inside non-expanded SKU nodes

    def count_included(i):
        for c in children_of.get(i, []):
            n = tree[c]
            if n["sku"]:
                included_hw[n["sku"]] += 1
            count_included(c)

    def walk(i):
        for c in children_of.get(i, []):
            n = tree[c]
            if n["sku"]:
                purchase[n["sku"]] += 1
            if is_group(n):
                walk(c)
            else:
                count_included(c)

    walk(0)
    # mecanum wheel halves are sold as a 4-wheel set
    if "3625-0001-0104" in purchase or "3625-0100-0104" in purchase:
        wheels = purchase.pop("3625-0001-0104", 0) + purchase.pop("3625-0100-0104", 0)
        purchase["3625-0202-0104"] = max(1, -(-wheels // 4))

    def pack_qty(name):
        m = re.search(r"(\d+)\s*Pack", name or "")
        return int(m.group(1)) if m else 1

    purchase_rows = []
    for sku, q in purchase.items():
        nm = name_of(sku)
        pk = pack_qty(nm)
        purchase_rows.append({
            "sku": sku, "name": nm or "(name not found)", "category": categorize(sku, nm, sku),
            "qty": q, "pack_size": pk, "packs_to_buy": -(-q // pk),
            "also_inside_subassemblies": included_hw.get(sku, 0),
            "name_source": source_of(sku),
            "url": catalog.get(sku, {}).get("url", ""),
        })
    purchase_rows.sort(key=lambda r: (CATEGORIES.index(r["category"]), -r["qty"], r["sku"]))
    write_csv(os.path.join(out, "bom_purchase.csv"), purchase_rows)

    # ---- 2. top-level BOM exactly as modelled ------------------------------
    top = Counter()
    for c in children_of[0]:
        top[tree[c]["product_key"]] += 1
    top_rows = []
    for key, q in top.items():
        p = P[key]
        top_rows.append({"label": p["label"], "sku": p["sku"], "name": name_of(p["sku"]),
                         "category": cat_of(key), "qty": q,
                         "type": "subassembly" if S["product_has_children"][key] else "part"})
    top_rows.sort(key=lambda r: (-r["qty"], r["label"]))
    write_csv(os.path.join(out, "bom_top_level.csv"), top_rows)

    # ---- 3. flattened leaf BOM ---------------------------------------------
    leaf = Counter()
    for n in tree:
        if n["is_leaf"]:
            leaf[n["product_key"]] += 1
    leaf_rows = []
    for key, q in leaf.items():
        p = P[key]
        leaf_rows.append({"label": p["label"], "sku": p["sku"], "name": name_of(p["sku"]),
                          "category": cat_of(key), "qty": q})
    leaf_rows.sort(key=lambda r: (-r["qty"], r["label"]))
    write_csv(os.path.join(out, "bom_flat_leaf_parts.csv"), leaf_rows)

    # ---- 4. fastener totals anywhere in the tree ----------------------------
    fast = Counter()
    fast_inside = Counter()
    for i, n in enumerate(tree):
        if n["sku"] and categorize(n["sku"], name_of(n["sku"]), n["label"]) == "Fasteners":
            fast[n["sku"]] += 1
            # inside a SKU'd, non-group ancestor?
            a = parent_of[i]
            inside = False
            while a is not None and a != 0:
                if tree[a]["sku"] and not is_group(tree[a]):
                    inside = True
                    break
                a = parent_of[a]
            if inside:
                fast_inside[n["sku"]] += 1
    fast_rows = [{"sku": k, "name": name_of(k), "total_in_model": v,
                  "inside_purchased_subassemblies": fast_inside[k],
                  "loose_or_designer_added": v - fast_inside[k]}
                 for k, v in fast.items()]
    fast_rows.sort(key=lambda r: -r["total_in_model"])
    write_csv(os.path.join(out, "fasteners.csv"), fast_rows)

    # ---- 5. subassembly breakdown -------------------------------------------
    # Fusion exports a separate PRODUCT for every duplicated component
    # ("5203-2402-0019_1", "_2", ...), so group by the cleaned label instead.
    sub_rows = []
    seen = set()
    label_instances = Counter(n["label"] for n in tree if not n["is_leaf"])
    for i, n in enumerate(tree):
        if n["is_leaf"] or i == 0 or n["label"] in seen:
            continue
        seen.add(n["label"])
        kids = Counter(tree[c]["label"] for c in children_of[i])
        inst = label_instances[n["label"]]
        sub_rows.append({"subassembly": n["label"], "sku": n["sku"], "name": name_of(n["sku"]),
                         "instances": inst, "depth": n["depth"],
                         "contents_per_instance": "; ".join(f"{v}x {k}" for k, v in kids.most_common())})
    sub_rows.sort(key=lambda r: (r["depth"], -r["instances"], r["subassembly"]))
    write_csv(os.path.join(out, "subassemblies.csv"), sub_rows)

    # ---- 6. assembly tree text ----------------------------------------------
    with open(os.path.join(out, "assembly_tree.txt"), "w") as f:
        for n in tree:
            nm = name_of(n["sku"])
            f.write("  " * n["depth"] + ("- " if n["depth"] else "") + n["label"]
                    + (f"  [{nm}]" if nm else "") + "\n")

    # ---- stats ---------------------------------------------------------------
    cat_top = Counter()
    for r in top_rows:
        cat_top[r["category"]] += r["qty"]
    cat_leaf = Counter()
    for r in leaf_rows:
        cat_leaf[r["category"]] += r["qty"]
    stats = dict(S["stats"])
    stats.update({
        "leaf_parts": sum(leaf.values()), "top_level_items": sum(top.values()),
        "top_level_lines": len(top_rows), "purchase_lines": len(purchase_rows),
        "purchase_units": sum(r["qty"] for r in purchase_rows),
        "fasteners_total": sum(fast.values()), "max_depth": max(n["depth"] for n in tree),
        "category_top_level": dict(cat_top), "category_leaf": dict(cat_leaf),
    })

    # ---- geometry -------------------------------------------------------------
    gpath = os.path.join(src, "geometry.npz")
    if os.path.exists(gpath):
        g = np.load(gpath)
        segs, pid = g["segs"], g["product"]
        pts = segs.reshape(-1, 3)
        mn, mx = pts.min(0), pts.max(0)
        stats["bbox_mm"] = {"min": mn.round(1).tolist(), "max": mx.round(1).tolist(),
                            "size": (mx - mn).round(1).tolist()}
        cat_idx = {c: i for i, c in enumerate(CATEGORIES)}
        key_cat = {int(k): cat_idx[cat_of(k)] for k in P}
        seg_cat = np.vectorize(key_cat.get)(pid)
        stats["wireframe_segments"] = int(len(segs))
        if "--no-render" not in sys.argv:
            render_wireframe(segs, seg_cat, out)
            render_exploded_by_category(segs, seg_cat, out)

    # ---- charts ------------------------------------------------------------------
    if "--no-render" not in sys.argv:
        chart_purchase(purchase_rows, out)
        chart_categories(cat_top, cat_leaf, out)
        chart_fasteners(fast_rows, out)

    json.dump(stats, open(os.path.join(out, "stats.json"), "w"), indent=1)
    write_markdown(out, purchase_rows, top_rows, fast_rows, sub_rows, stats)
    print(json.dumps(stats, indent=1))


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def style_axes(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)
    ax.title.set_color(INK)


def chart_purchase(rows, out):
    rows = sorted(rows, key=lambda r: -r["qty"])[:30]
    fig, ax = plt.subplots(figsize=(11, 9), facecolor=SURFACE)
    style_axes(ax)
    labels = [f'{r["sku"]}  {shorten(r["name"], 52)}' for r in rows][::-1]
    vals = [r["qty"] for r in rows][::-1]
    cols = [CAT_COLOR[r["category"]] for r in rows][::-1]
    ax.barh(labels, vals, color=cols, height=0.7)
    for i, v in enumerate(vals):
        ax.text(v + 0.3, i, str(v), va="center", fontsize=8, color=INK2)
    ax.set_xlabel("quantity used in the assembly")
    ax.set_title("Purchase-level BOM: 30 largest line items (colour = category)", loc="left", fontsize=12)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(handles=[Line2D([0], [0], marker="s", color="none", markerfacecolor=CAT_COLOR[c], markersize=9, label=c)
                       for c in CATEGORIES if any(r["category"] == c for r in rows)],
              loc="lower right", frameon=False, fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(out, "chart_bom_top30.png"), dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_categories(cat_top, cat_leaf, out):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), facecolor=SURFACE)
    for ax, data, title in zip(axes, (cat_top, cat_leaf),
                               ("Top-level items by category", "Leaf parts (every modelled body) by category")):
        style_axes(ax)
        cats = [c for c in CATEGORIES if data.get(c)]
        vals = [data[c] for c in cats]
        ax.barh(cats[::-1], vals[::-1], color=[CAT_COLOR[c] for c in cats][::-1], height=0.65)
        for i, v in enumerate(vals[::-1]):
            ax.text(v + max(vals) * 0.01, i, str(v), va="center", fontsize=9, color=INK2)
        ax.set_title(title, loc="left", fontsize=11)
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_xlim(0, max(vals) * 1.12)
    plt.tight_layout()
    plt.savefig(os.path.join(out, "chart_categories.png"), dpi=150, facecolor=SURFACE)
    plt.close(fig)


def chart_fasteners(rows, out):
    fig, ax = plt.subplots(figsize=(11, 5), facecolor=SURFACE)
    style_axes(ax)
    labels = [f'{r["sku"]}  {shorten(r["name"], 48)}' for r in rows][::-1]
    inside = np.array([r["inside_purchased_subassemblies"] for r in rows][::-1])
    loose = np.array([r["loose_or_designer_added"] for r in rows][::-1])
    ax.barh(labels, loose, color=SEQ, height=0.65, label="loose / added by the designer")
    ax.barh(labels, inside, left=loose, color="#9ec5f4", height=0.65, label="ships inside a purchased part")
    for i, v in enumerate(loose + inside):
        ax.text(v + 0.5, i, str(int(v)), va="center", fontsize=8, color=INK2)
    ax.set_title("Fasteners and small hardware in the model", loc="left", fontsize=12)
    ax.set_xlabel("count")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(out, "chart_fasteners.png"), dpi=150, facecolor=SURFACE)
    plt.close(fig)


def iso_project(pts, azim=-50, elev=28):
    a, e = np.radians(azim), np.radians(elev)
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    p = pts @ rz.T @ rx.T
    return p[..., [0, 2]], p[..., 1]


def render_wireframe(segs, seg_cat, out):
    colors = np.array([matplotlib.colors.to_rgba(CAT_COLOR[c]) for c in CATEGORIES])
    col = colors[seg_cat]
    col[:, 3] = 0.35
    fig = plt.figure(figsize=(16, 12), facecolor=SURFACE)
    views = [("Top view (X-Y)", (0, 1)), ("Front view (X-Z)", (0, 2)), ("Side view (Y-Z)", (1, 2))]
    for k, (title, (a, b)) in enumerate(views):
        ax = fig.add_subplot(2, 2, k + 1)
        ax.set_facecolor(SURFACE)
        ax.add_collection(LineCollection(segs[:, :, [a, b]], colors=col, linewidths=0.2))
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_title(title, loc="left", color=INK, fontsize=12)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ax.spines.values():
            s.set_color(GRID)
        ax.set_xlabel("mm", color=MUTED)
    ax = fig.add_subplot(2, 2, 4)
    ax.set_facecolor(SURFACE)
    p2, depth = iso_project(segs)
    order = np.argsort(depth.mean(1))[::-1]
    ax.add_collection(LineCollection(p2[order], colors=col[order], linewidths=0.2))
    ax.autoscale()
    ax.set_aspect("equal")
    ax.set_title("Isometric view", loc="left", color=INK, fontsize=12)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(GRID)
    fig.legend(handles=[Line2D([0], [0], color=CAT_COLOR[c], lw=3, label=c) for c in CATEGORIES],
               loc="lower center", ncol=len(CATEGORIES), frameon=False, fontsize=10)
    fig.suptitle("goBILDA 3200-2627-0004: wireframe of every edge in the STEP file, coloured by part category",
                 x=0.02, ha="left", fontsize=14, color=INK)
    plt.tight_layout(rect=(0, 0.04, 1, 0.97))
    plt.savefig(os.path.join(out, "assembly_wireframe.png"), dpi=130, facecolor=SURFACE)
    plt.close(fig)


def render_exploded_by_category(segs, seg_cat, out):
    """Small multiples: the isometric view with one category highlighted per panel."""
    p2, depth = iso_project(segs)
    cats = [c for i, c in enumerate(CATEGORIES) if (seg_cat == i).any()]
    n = len(cats)
    cols = 4
    rows = -(-n // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 4.2 * rows), facecolor=SURFACE)
    axes = np.array(axes).reshape(-1)
    for ax in axes:
        ax.axis("off")
    grey = matplotlib.colors.to_rgba(GRID)
    for ax, c in zip(axes, cats):
        i = CATEGORIES.index(c)
        mask = seg_cat == i
        ax.set_facecolor(SURFACE)
        ax.add_collection(LineCollection(p2[~mask], colors=[grey], linewidths=0.15))
        ax.add_collection(LineCollection(p2[mask], colors=[matplotlib.colors.to_rgba(CAT_COLOR[c], 0.6)], linewidths=0.3))
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_title(f"{c}  ({int(mask.sum()):,} edges)", loc="left", color=INK, fontsize=11)
    fig.suptitle("Where each category sits in the assembly (isometric, highlighted vs the rest)",
                 x=0.02, ha="left", fontsize=13, color=INK)
    plt.tight_layout(rect=(0, 0, 1, 0.96))
    plt.savefig(os.path.join(out, "assembly_by_category.png"), dpi=130, facecolor=SURFACE)
    plt.close(fig)


def shorten(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def md_table(rows, cols, headers=None):
    headers = headers or cols
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(r[c]).replace("|", "\\|") for c in cols) + " |")
    return "\n".join(lines)


def write_markdown(out, purchase_rows, top_rows, fast_rows, sub_rows, stats):
    L = []
    L.append("# Bill of materials: goBILDA 3200-2627-0004\n")
    L.append("Generated from `3200-2627-0004.step` (AP214, exported 2026-09-09 from Autodesk Fusion). "
             "Part names were looked up on gobilda.com by SKU; rows marked `inferred` follow the "
             "series numbering but had no exact product page, and `unknown` rows had no match.\n")
    L.append("## Purchase-level BOM\n")
    L.append("One row per goBILDA SKU that appears at the top of the assembly (loose hardware folders and "
             "\"w.Hardware\" groups expanded). `qty` is how many are used; `packs_to_buy` divides by the "
             "pack size in the product name. `also_inside_subassemblies` counts extra copies that the "
             "model shows shipping inside another purchased part (for example the two screws in each Sonic Hub).\n")
    L.append(md_table(purchase_rows, ["sku", "name", "category", "qty", "pack_size", "packs_to_buy",
                                      "also_inside_subassemblies", "name_source"]))
    L.append("\n## Fasteners anywhere in the model\n")
    L.append(md_table(fast_rows, ["sku", "name", "total_in_model", "inside_purchased_subassemblies",
                                  "loose_or_designer_added"]))
    L.append("\n## Top-level items exactly as modelled\n")
    L.append(md_table(top_rows, ["label", "name", "category", "qty", "type"]))
    L.append("\n## Subassemblies\n")
    L.append(md_table(sub_rows, ["subassembly", "name", "instances", "contents_per_instance"]))
    with open(os.path.join(out, "BOM.md"), "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
