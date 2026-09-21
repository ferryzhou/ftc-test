#!/usr/bin/env python3
"""
Geometric simulation of the ball path through the modified StarterBot.

Opens the StarterBot STEP, applies the BIOBUZZ edits in memory (build_biobuzz_step.py), meshes
the parts around the ball path and then, with point-to-triangle distances on those meshes:

 1. sweeps the hood flap angle and measures the hood-to-Hogback gap, reporting the angle that
    gives the NECTAR gap;
 2. places POLLEN (71 mm), NECTAR (92 mm) and an oversize NECTAR (95 mm) at stations along the
    path (intake mouth, under the conveyor, on the ramp, hopper, exit guide) and reports the
    clearance to the nearest part, or the interference depth a compliant part must absorb;
 3. writes clearance_sim.json and a chart of gap versus flap angle.

    python3 clearance_sim.py <starterbot.step> <out_dir>
"""
import json
import math
import os
import sys
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_biobuzz_step as build  # noqa: E402
from render_step import mesh_shape  # noqa: E402

FLOOR = build.FLOOR
BALLS = {"POLLEN 71": 71.1, "NECTAR 92": 91.9, "NECTAR 95 (oversize)": 95.0}
NECTAR_GAP = 68.0
SURFACE, INK, INK2, GRID, AXIS, BLUE = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#2a78d6"


# ---------------------------------------------------------------- geometry kernel on meshes

def point_triangle_distance(p, a, b, c):
    """Distance from points p (Nx3) to triangles (a, b, c: Mx3): returns NxM. Ericson, RTCD 5.1.5."""
    ab = b - a
    ac = c - a
    ap = p[:, None, :] - a[None, :, :]
    d1 = np.einsum("nmk,mk->nm", ap, ab)
    d2 = np.einsum("nmk,mk->nm", ap, ac)
    bp = p[:, None, :] - b[None, :, :]
    d3 = np.einsum("nmk,mk->nm", bp, ab)
    d4 = np.einsum("nmk,mk->nm", bp, ac)
    cp = p[:, None, :] - c[None, :, :]
    d5 = np.einsum("nmk,mk->nm", cp, ab)
    d6 = np.einsum("nmk,mk->nm", cp, ac)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = 1.0 / np.maximum(va + vb + vc, 1e-12)
    v = vb * denom
    w = vc * denom
    # closest point on the face plane, then clamp to edges/vertices region by region
    closest = a[None] + v[..., None] * ab[None] + w[..., None] * ac[None]
    # region: vertex a
    m = (d1 <= 0) & (d2 <= 0)
    closest = np.where(m[..., None], a[None], closest)
    # vertex b
    m = (d3 >= 0) & (d4 <= d3)
    closest = np.where(m[..., None], b[None], closest)
    # vertex c
    m = (d6 >= 0) & (d5 <= d6)
    closest = np.where(m[..., None], c[None], closest)
    # edge ab
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = d1 / np.maximum(d1 - d3, 1e-12)
    closest = np.where(m[..., None], a[None] + t[..., None] * ab[None], closest)
    # edge ac
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = d2 / np.maximum(d2 - d6, 1e-12)
    closest = np.where(m[..., None], a[None] + t[..., None] * ac[None], closest)
    # edge bc
    m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)
    t = (d4 - d3) / np.maximum((d4 - d3) + (d5 - d6), 1e-12)
    closest = np.where(m[..., None], b[None] + t[..., None] * (c - b)[None], closest)
    return np.linalg.norm(p[:, None, :] - closest, axis=2)


class Mesh:
    def __init__(self, name, shape, deflection=0.4):
        self.name = name
        v, t = mesh_shape(shape, deflection)
        self.v = v.astype(np.float64)
        self.t = t
        self.a, self.b, self.c = self.v[t[:, 0]], self.v[t[:, 1]], self.v[t[:, 2]]
        self.centroid = (self.a + self.b + self.c) / 3
        self.lo, self.hi = self.v.min(0), self.v.max(0)

    def distance(self, p):
        """Distance from one point (3,) to the mesh surface."""
        p = np.asarray(p, dtype=np.float64)
        # bbox lower bound
        d_box = np.linalg.norm(np.maximum(0, np.maximum(self.lo - p, p - self.hi)))
        # candidate triangles: centroid within (nearest centroid + longest edge) radius
        dc = np.linalg.norm(self.centroid - p, axis=1)
        limit = dc.min() + 60.0
        idx = np.nonzero(dc <= limit)[0]
        best = np.inf
        for k in range(0, len(idx), 4000):
            sel = idx[k:k + 4000]
            d = point_triangle_distance(p[None, :], self.a[sel], self.b[sel], self.c[sel]).min()
            best = min(best, d)
        return max(best, d_box)

    def transformed(self, R, t):
        m = Mesh.__new__(Mesh)
        m.name = self.name
        m.v = self.v @ R.T + t
        m.t = self.t
        m.a, m.b, m.c = m.v[self.t[:, 0]], m.v[self.t[:, 1]], m.v[self.t[:, 2]]
        m.centroid = (m.a + m.b + m.c) / 3
        m.lo, m.hi = m.v.min(0), m.v.max(0)
        return m


def mesh_to_mesh_distance(m1, m2):
    """Min distance from the vertices of m1 to the surface of m2 (and vice versa)."""
    best = np.inf
    for src, dst in ((m1, m2), (m2, m1)):
        # only vertices near the other mesh's bbox matter
        d_box = np.linalg.norm(np.maximum(0, np.maximum(dst.lo - src.v, src.v - dst.hi)), axis=1)
        for i in np.argsort(d_box)[:400]:
            if d_box[i] >= best:
                break
            best = min(best, dst.distance(src.v[i]))
    return best


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------- main

def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    app, doc = build.open_doc(src)
    info = build.apply_edits(doc, hood_angle=0.0, verbose=False)
    st = info["shape_tool"]
    print(f"model loaded and edited, {time.time() - t0:.0f}s")

    # parts near the ball path (by name prefix); everything else cannot touch a ball on the path
    wanted = ("3626-0014-0096", "1117-", "3613-4008-0048", "3618-4008-0016", "1120-0010-0264",
              "1120-0015-0384", "1120-0008-0216", "1121-0005-0144", "1120-0002-0072", "2106-4008-2640",
              "2106-4008-2400", "1522-", "2000-0025-0002", "3217-0001-2501 w.Hardware (2.6):3",
              "1310-0016-4008", "5203-2402-0019:5", "1201-0043-0002", "1143-", "1121-0001-0048")
    meshes = []
    for o in info["occ"]:
        if o["name"].startswith(wanted):
            meshes.append(Mesh(o["name"], st.GetShape_s(o["label"])))
    print(f"meshed {len(meshes)} parts, {sum(len(m.t) for m in meshes):,} triangles, {time.time() - t0:.0f}s")
    by_name = {m.name: m for m in meshes}
    hood = by_name["1117-0216-0352 (3200-2627-0004_H):1"]
    wheel = by_name["3626-0014-0096:1"]
    hinge_y, hinge_z = info["hinge"]

    # ---- 1. hood gap vs flap angle ----
    gaps = []
    for deg in range(0, 16, 1):
        a = math.radians(deg)
        R = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
        pivot = np.array([0.0, hinge_y, hinge_z])
        rot = hood.transformed(R, pivot - R @ pivot)
        g = mesh_to_mesh_distance(rot, wheel)
        gaps.append((deg, round(float(g), 2)))
    print("hood flap angle sweep (Gridplate H to Hogback wheel):", ", ".join(f"{d}°:{g:.1f}" for d, g in gaps))
    nectar_angle = None
    for (a0, g0), (a1, g1) in zip(gaps, gaps[1:]):
        if min(g0, g1) <= NECTAR_GAP <= max(g0, g1) and g1 != g0:
            nectar_angle = a0 + (NECTAR_GAP - g0) / (g1 - g0) * (a1 - a0)
            break
    print(f"stock gap {gaps[0][1]:.1f} mm; {NECTAR_GAP} mm gap at flap angle "
          f"{'not reached' if nectar_angle is None else f'{nectar_angle:.1f} deg'}, {time.time() - t0:.0f}s")

    fig, ax = plt.subplots(figsize=(7, 4), facecolor=SURFACE)
    style(ax)
    ax.plot([d for d, _ in gaps], [g for _, g in gaps], color=BLUE, lw=2, marker="o", ms=4)
    ax.axhline(NECTAR_GAP, color=AXIS, ls="--", lw=1)
    ax.text(0.3, NECTAR_GAP + 1, "NECTAR gap 68 mm", color=INK2, fontsize=9)
    ax.axhline(gaps[0][1], color=AXIS, ls=":", lw=1)
    ax.text(0.3, gaps[0][1] + 1, f"stock POLLEN gap {gaps[0][1]:.0f} mm", color=INK2, fontsize=9)
    if nectar_angle is not None:
        ax.axvline(nectar_angle, color=AXIS, ls="--", lw=1)
        ax.text(nectar_angle + 0.3, gaps[0][1] - 6, f"{nectar_angle:.1f}°", color=INK2, fontsize=9)
    ax.set_xlabel("hood flap angle about its top hinge, degrees", color=INK2)
    ax.set_ylabel("gap to the Hogback wheel, mm", color=INK2)
    ax.set_title("Hood servo travel needed for NECTAR", loc="left", color=INK, fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(out, "sim_hood_gap.png"), dpi=150, facecolor=SURFACE)
    plt.close(fig)

    # ---- 2. ball stations ----
    def nearest(p, radius, exclude=()):
        best = (np.inf, "")
        for m in meshes:
            if any(m.name.startswith(e) for e in exclude):
                continue
            d_box = np.linalg.norm(np.maximum(0, np.maximum(m.lo - p, p - m.hi))) - radius
            if d_box >= best[0]:
                continue
            d = m.distance(p) - radius
            if d < best[0]:
                best = (d, m.name)
        return best

    def rest_height(x, y, radius, support):
        """Lowest ball-centre z at which the ball just clears the support parts (bisection)."""
        sup = [m for m in meshes if m.name.startswith(support)]
        lo, hi = FLOOR + radius - 5.0, FLOOR + radius + 150.0
        for _ in range(18):
            mid = (lo + hi) / 2
            d = min(m.distance(np.array([x, y, mid])) for m in sup) - radius
            if d >= 0:
                hi = mid
            else:
                lo = mid
        return hi

    stations = [
        ("intake mouth, on the tiles in front of the roller bar", 0.0, -160.0, ()),
        ("under the Gecko conveyor, on the tiles", 0.0, -185.5, ()),
        ("on the intake ramp E", 0.0, -60.0, ("1117-0088-0352 (3200-2627-0004_E)",)),
        ("hopper floor in front of the wheel", -5.0, -35.0, ("1117-0088-0352 (3200-2627-0004_E)", "1117-0088-0352 (3200-2627-0004_F)")),
        ("exit guide between the side walls", 0.0, 140.0, ("1117-0216-0352 cut G'", "1117-0088-0352 (3200-2627-0004_G)")),
    ]
    rows = []
    print("ball stations (clearance to the nearest part; negative = interference a compliant part must absorb):")
    for ball, dia in BALLS.items():
        r = dia / 2
        for label, x, y, support in stations:
            z = rest_height(x, y, r, support) if support else FLOOR + r
            d, name = nearest(np.array([x, y, z]), r, exclude=support)
            rows.append({"ball": ball, "station": label, "x": x, "y": y, "z_above_tiles": round(z - FLOOR, 1),
                         "clearance_mm": round(float(d), 1), "nearest": name})
            print(f"   {ball:<22} {label:<52} centre {z - FLOOR:6.1f} mm up  clearance {d:6.1f} mm  ({name})")
        for hood_name, gap in (("hood POLLEN position", gaps[0][1]), ("hood NECTAR position", NECTAR_GAP)):
            rows.append({"ball": ball, "station": f"launcher squeeze, {hood_name}", "clearance_mm": round(gap - dia, 1),
                         "nearest": "3626-0014-0096 / Gridplate H"})
            print(f"   {ball:<22} launcher squeeze, {hood_name:<32} gap {gap:5.1f} mm -> squeeze {dia - gap:5.1f} mm")

    json.dump({"hood_gap_vs_angle_deg_mm": gaps, "nectar_hood_angle_deg": nectar_angle, "stations": rows},
              open(os.path.join(out, "clearance_sim.json"), "w"), indent=1)
    print(f"wrote clearance_sim.json and sim_hood_gap.png, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
