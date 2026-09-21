#!/usr/bin/env python3
"""
Lightweight STEP (AP214) assembly parser.

Streams a STEP file, extracts the product / assembly-occurrence graph, rolls
up quantities into a bill of materials, and (optionally) pulls a wireframe
(vertices + edges) for every leaf part together with the assembly transforms
so the whole assembly can be drawn without a CAD kernel.

Usage:
    python3 parse_step.py <file.step> <out_dir>

Outputs (in out_dir):
    structure.json   products, occurrences, tree, per-product quantities
    geometry.npz     transformed wireframe segments per occurrence (if any)
"""
import json
import math
import re
import sys
from collections import defaultdict, Counter

import numpy as np

REF_RE = re.compile(r"#(\d+)")
STR_RE = re.compile(r"'((?:[^']|'')*)'")

# Entity types we keep. Everything else (surfaces, b-splines, styling detail)
# is dropped at parse time to keep memory in check.
KEEP = {
    "PRODUCT", "PRODUCT_DEFINITION_FORMATION", "PRODUCT_DEFINITION",
    "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE",
    "NEXT_ASSEMBLY_USAGE_OCCURRENCE", "PRODUCT_DEFINITION_SHAPE",
    "SHAPE_DEFINITION_REPRESENTATION", "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION",
    "ITEM_DEFINED_TRANSFORMATION", "AXIS2_PLACEMENT_3D", "DIRECTION",
    "CARTESIAN_POINT", "SHAPE_REPRESENTATION", "ADVANCED_BREP_SHAPE_REPRESENTATION",
    "MANIFOLD_SOLID_BREP", "CLOSED_SHELL", "OPEN_SHELL", "ADVANCED_FACE", "FACE_BOUND",
    "FACE_OUTER_BOUND", "EDGE_LOOP", "ORIENTED_EDGE", "EDGE_CURVE",
    "VERTEX_POINT", "LINE", "CIRCLE", "SHELL_BASED_SURFACE_MODEL",
    "STYLED_ITEM", "PRESENTATION_STYLE_ASSIGNMENT", "SURFACE_STYLE_USAGE",
    "SURFACE_SIDE_STYLE", "SURFACE_STYLE_FILL_AREA", "FILL_AREA_STYLE",
    "FILL_AREA_STYLE_COLOUR", "COLOUR_RGB", "DRAUGHTING_PRE_DEFINED_COLOUR",
    "SHAPE_REPRESENTATION_RELATIONSHIP", "REPRESENTATION_RELATIONSHIP",
    "GEOMETRICALLY_BOUNDED_SURFACE_SHAPE_REPRESENTATION",
    "MANIFOLD_SURFACE_SHAPE_REPRESENTATION",
}


def iter_entities(path):
    """Yield (id, body) for each '#id=...;' entity in the DATA section."""
    buf = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not buf:
                if not line.startswith("#"):
                    continue
            buf.append(line)
            if line.endswith(";"):
                text = "".join(buf)
                buf = []
                eq = text.index("=")
                yield int(text[1:eq]), text[eq + 1:-1]


def parse(path):
    ents = {}   # id -> (type, refs tuple, strings tuple, raw-or-None)
    points = {}  # id -> (x, y, z)  for CARTESIAN_POINT / DIRECTION
    complex_rel = {}  # id -> (rep1, rep2, transform)
    n = 0
    for eid, body in iter_entities(path):
        n += 1
        if body.startswith("("):
            # complex entity, e.g. (REPRESENTATION_RELATIONSHIP(...)
            #   REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#t)
            #   SHAPE_REPRESENTATION_RELATIONSHIP())
            if "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION" in body:
                m = re.search(r"REPRESENTATION_RELATIONSHIP\(([^)]*)\)", body)
                refs = [int(x) for x in REF_RE.findall(m.group(1))]
                mt = re.search(r"WITH_TRANSFORMATION\(#(\d+)\)", body)
                complex_rel[eid] = (refs[0], refs[1], int(mt.group(1)))
            elif "PRODUCT_DEFINITION_FORMATION" in body and "PRODUCT_DEFINITION_FORMATION(" in body:
                m = re.search(r"PRODUCT_DEFINITION_FORMATION\(([^)]*)\)", body)
                refs = tuple(int(x) for x in REF_RE.findall(m.group(1)))
                ents[eid] = ("PRODUCT_DEFINITION_FORMATION", refs, (), None)
            continue
        p = body.index("(")
        typ = body[:p]
        if typ not in KEEP:
            continue
        args = body[p + 1:-1]
        if typ == "CARTESIAN_POINT" or typ == "DIRECTION":
            m = re.search(r"\(([^()]*)\)\s*$", args)
            nums = [float(x) for x in m.group(1).split(",")]
            while len(nums) < 3:
                nums.append(0.0)
            points[eid] = tuple(nums[:3])
            continue
        refs = tuple(int(x) for x in REF_RE.findall(args))
        strs = tuple(s.replace("''", "'") for s in STR_RE.findall(args))
        raw = args if typ in ("EDGE_CURVE", "ORIENTED_EDGE", "SURFACE_STYLE_USAGE", "CIRCLE") else None
        ents[eid] = (typ, refs, strs, raw)
    return ents, points, complex_rel, n


SKU_RE = re.compile(r"\d{4}-\d{4}-\d{4}")


def clean_label(pid):
    """Strip the CAD-generated '_N' duplicate suffix from a product id."""
    return re.sub(r"_\d+$", "", pid).strip()


def extract_sku(pid, pname):
    for s in (pid, pname):
        m = SKU_RE.search(s)
        if m:
            return m.group(0)
    return ""


def build_structure(ents, complex_rel):
    products = {}
    for eid, (typ, refs, strs, _) in ents.items():
        if typ == "PRODUCT":
            # STEP: PRODUCT(id, name, description, frame_of_reference)
            # Fusion 360 export: id = unique component name (may carry a
            # '_N' duplicate suffix or an auto timestamp), name = part number.
            pid = strs[0]
            pname = strs[1] if len(strs) > 1 else ""
            label = clean_label(pname) if pname.strip() else clean_label(pid)
            products[eid] = {"id": pid, "name": pname, "label": label,
                             "sku": extract_sku(pname, pid),
                             "desc": strs[2] if len(strs) > 2 else ""}
    formation_to_product = {eid: refs[-1] for eid, (t, refs, s, _) in ents.items()
                            if t == "PRODUCT_DEFINITION_FORMATION"}
    pd_to_product = {}
    for eid, (typ, refs, strs, _) in ents.items():
        if typ == "PRODUCT_DEFINITION":
            pd_to_product[eid] = formation_to_product[refs[0]]
    nauo = {}
    children = defaultdict(list)
    for eid, (typ, refs, strs, _) in ents.items():
        if typ == "NEXT_ASSEMBLY_USAGE_OCCURRENCE":
            parent, child = refs[0], refs[1]
            nauo[eid] = {"name": strs[0], "parent": parent, "child": child}
            children[parent].append(eid)
    # shape links
    pds_of = {}  # definition (PD or NAUO) -> PDS id
    for eid, (typ, refs, strs, _) in ents.items():
        if typ == "PRODUCT_DEFINITION_SHAPE":
            pds_of[refs[0]] = eid
    pd_shape_rep = {}
    for eid, (typ, refs, strs, _) in ents.items():
        if typ == "SHAPE_DEFINITION_REPRESENTATION":
            pd_shape_rep[refs[0]] = refs[1]  # PDS -> rep
    nauo_transform = {}  # nauo id -> (rep1, rep2, transform)
    for eid, (typ, refs, strs, _) in ents.items():
        if typ == "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION":
            rel, pds = refs
            pds_ent = ents[pds]
            definition = pds_ent[1][0]
            if definition in nauo and rel in complex_rel:
                nauo_transform[definition] = complex_rel[rel]
    return products, pd_to_product, nauo, children, pds_of, pd_shape_rep, nauo_transform


def axis_matrix(ents, points, axis_id):
    """4x4 matrix for an AXIS2_PLACEMENT_3D."""
    typ, refs, _, _ = ents[axis_id]
    loc = np.array(points[refs[0]])
    z = np.array(points[refs[1]]) if len(refs) > 1 else np.array([0, 0, 1.0])
    x = np.array(points[refs[2]]) if len(refs) > 2 else None
    z = z / np.linalg.norm(z)
    if x is None:
        x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = x - np.dot(x, z) * z
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    m = np.eye(4)
    m[:3, 0] = x
    m[:3, 1] = y
    m[:3, 2] = z
    m[:3, 3] = loc
    return m


def occurrence_matrix(ents, points, rel, child_rep):
    """Matrix taking child coordinates into the parent's frame."""
    rep1, rep2, t = rel
    _, trefs, _, _ = ents[t]
    a1 = axis_matrix(ents, points, trefs[0])
    a2 = axis_matrix(ents, points, trefs[1])
    # ITEM_DEFINED_TRANSFORMATION(transform_item_1, transform_item_2):
    # item_1 is in rep1's space, item_2 in rep2's space. The child's shape rep
    # is one of rep1/rep2; map child frame -> parent frame.
    if rep1 == child_rep:
        return a2 @ np.linalg.inv(a1)
    return a1 @ np.linalg.inv(a2)


def build_srr_map(ents):
    """rep -> reps linked by a plain (non-transforming) SHAPE_REPRESENTATION_RELATIONSHIP."""
    m = defaultdict(list)
    for eid, (typ, refs, strs, _) in ents.items():
        if typ == "SHAPE_REPRESENTATION_RELATIONSHIP" and len(refs) >= 2:
            m[refs[0]].append(refs[1])
            m[refs[1]].append(refs[0])
    return m


def collect_wireframe(ents, points, rep_id, srr_map):
    """Return segments (Mx2x3) approximating the edges of a shape representation."""
    segs = []
    reps = [rep_id]
    seen = set()
    solids = []
    while reps:
        r = reps.pop()
        if r in seen or r not in ents:
            continue
        seen.add(r)
        typ, refs, strs, _ = ents[r]
        reps.extend(srr_map.get(r, ()))
        for item in refs:
            if item in ents and ents[item][0] in ("MANIFOLD_SOLID_BREP", "SHELL_BASED_SURFACE_MODEL"):
                solids.append(item)
    for s in solids:
        typ, refs, _, _ = ents[s]
        shells = [refs[0]] if typ == "MANIFOLD_SOLID_BREP" else list(refs)
        for shell in shells:
            if shell not in ents:
                continue
            for face in ents[shell][1]:
                if face not in ents:
                    continue
                for bound in ents[face][1]:
                    if bound not in ents or ents[bound][0] not in ("FACE_BOUND", "FACE_OUTER_BOUND"):
                        continue
                    loop = ents[bound][1][0]
                    if loop not in ents:
                        continue
                    for oe in ents[loop][1]:
                        if oe not in ents:
                            continue
                        ec = ents[oe][1][-1]
                        if ec not in ents or ents[ec][0] != "EDGE_CURVE":
                            continue
                        _, erefs, _, eraw = ents[ec]
                        v1, v2, curve = erefs[0], erefs[1], erefs[2]
                        p1 = np.array(points[ents[v1][1][0]])
                        p2 = np.array(points[ents[v2][1][0]])
                        ctyp = ents[curve][0] if curve in ents else None
                        if ctyp == "CIRCLE":
                            _, crefs, _, craw = ents[curve]
                            radius = float(craw.rsplit(",", 1)[1])
                            m = axis_matrix(ents, points, crefs[0])
                            c = m[:3, 3]
                            ex, ey = m[:3, 0], m[:3, 1]
                            same = ".T." in eraw.rsplit(",", 1)[1]
                            def ang(p):
                                d = p - c
                                return math.atan2(np.dot(d, ey), np.dot(d, ex))
                            a1, a2 = ang(p1), ang(p2)
                            if np.linalg.norm(p1 - p2) < 1e-6:
                                a1, a2 = 0.0, 2 * math.pi
                            else:
                                if not same:
                                    a1, a2 = a2, a1
                                while a2 <= a1:
                                    a2 += 2 * math.pi
                            nseg = max(4, int((a2 - a1) / (2 * math.pi) * 24))
                            angs = np.linspace(a1, a2, nseg + 1)
                            pts = c[None, :] + radius * (np.cos(angs)[:, None] * ex[None, :] + np.sin(angs)[:, None] * ey[None, :])
                            for i in range(nseg):
                                segs.append((pts[i], pts[i + 1]))
                        else:
                            segs.append((p1, p2))
    if segs:
        segs = np.array(segs)
    else:
        segs = np.zeros((0, 2, 3))
    return segs


def main():
    path, out_dir = sys.argv[1], sys.argv[2]
    ents, points, complex_rel, n = parse(path)
    print(f"parsed {n} entities, kept {len(ents)} + {len(points)} points")
    (products, pd_to_product, nauo, children, pds_of,
     pd_shape_rep, nauo_transform) = build_structure(ents, complex_rel)
    print(f"products={len(products)} product_definitions={len(pd_to_product)} occurrences={len(nauo)}")

    # root(s): product definitions never used as a child
    child_pds = {o["child"] for o in nauo.values()}
    roots = [pd for pd in pd_to_product if pd not in child_pds]
    print("roots:", [products[pd_to_product[r]]["name"] for r in roots])
    root = roots[0]

    # quantity roll-up + flattened tree + geometry
    qty_by_pd = Counter()
    tree = []
    occ_records = []  # (pd, path, matrix)
    # leaf shape reps
    def shape_rep_of(pd):
        pds = pds_of.get(pd)
        return pd_shape_rep.get(pds)

    srr_map = build_srr_map(ents)
    wire_cache = {}
    all_segs = []
    all_pd = []

    def visit(pd, depth, mat, path_name):
        qty_by_pd[pd] += 1
        prod = products[pd_to_product[pd]]
        kids = children.get(pd, [])
        tree.append({"depth": depth, "pd": pd, "product_key": pd_to_product[pd], "label": prod["label"],
                     "sku": prod["sku"], "occurrence": path_name, "is_leaf": not kids})
        rep = shape_rep_of(pd)
        if rep is not None:
            if pd not in wire_cache:
                wire_cache[pd] = collect_wireframe(ents, points, rep, srr_map)
            segs = wire_cache[pd]
            if len(segs):
                pts = segs.reshape(-1, 3)
                pts = (mat[:3, :3] @ pts.T).T + mat[:3, 3]
                all_segs.append(pts.reshape(-1, 2, 3))
                all_pd.append(np.full(len(segs), pd_to_product[pd]))
        for o in kids:
            occ = nauo[o]
            child = occ["child"]
            m = mat
            if o in nauo_transform:
                child_rep = shape_rep_of(child)
                m = mat @ occurrence_matrix(ents, points, nauo_transform[o], child_rep)
            visit(child, depth + 1, m, occ["name"])

    visit(root, 0, np.eye(4), "")

    # product-level BOM: quantity of each product across the whole assembly
    qty_by_product = Counter()
    for pd, q in qty_by_pd.items():
        qty_by_product[pd_to_product[pd]] += q
    product_children = {pd_to_product[pd]: bool(children.get(pd)) for pd in pd_to_product}

    # direct children of root (top-level BOM)
    top_level = Counter()
    for o in children.get(root, []):
        top_level[pd_to_product[nauo[o]["child"]]] += 1

    structure = {
        "root": products[pd_to_product[root]],
        "products": {str(k): v for k, v in products.items()},
        "product_has_children": {str(k): v for k, v in product_children.items()},
        "qty_by_product": {str(k): v for k, v in qty_by_product.items()},
        "top_level": {str(k): v for k, v in top_level.items()},
        "tree": tree,
        "stats": {"entities": n, "products": len(products), "occurrences": len(nauo),
                  "tree_nodes": len(tree)},
    }
    with open(f"{out_dir}/structure.json", "w") as f:
        json.dump(structure, f, indent=1)
    if all_segs:
        segs = np.concatenate(all_segs)
        pids = np.concatenate(all_pd)
        np.savez_compressed(f"{out_dir}/geometry.npz", segs=segs.astype(np.float32), product=pids)
        print(f"geometry: {len(segs)} segments, bbox min={segs.reshape(-1,3).min(0)} max={segs.reshape(-1,3).max(0)}")
    print("tree nodes:", len(tree))


if __name__ == "__main__":
    main()
