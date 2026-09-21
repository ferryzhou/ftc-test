#!/usr/bin/env python3
"""
Geometric simulation of the ball path through the modified StarterBot.

Opens the StarterBot document, applies the BIOBUZZ edits in memory (build_biobuzz_step.py),
then:

 1. sweeps the hood flap angle and measures the hood-to-Hogback gap with exact B-rep distance
    queries, reporting the angle that gives the NECTAR gap;
 2. places POLLEN (71 mm), NECTAR (92 mm) and an oversize NECTAR (95 mm) at stations along the
    path (intake mouth, under the conveyor, on the ramp, hopper, launcher squeeze, exit guide)
    and reports the clearance to the nearest part, or the interference depth.

    python3 clearance_sim.py <starterbot.xbf | starterbot.step> <out_dir>
"""
import json
import math
import os
import sys

from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex, BRepBuilderAPI_Transform
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt
from OCP.TopoDS import TopoDS_Compound

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_biobuzz_step as build  # noqa: E402

FLOOR = build.FLOOR
BALLS = {"POLLEN 71": 71.1, "NECTAR 92": 91.9, "NECTAR 95 (oversize)": 95.0}
POLLEN_GAP, NECTAR_GAP = 47.0, 68.0


def dist(a, b):
    d = BRepExtrema_DistShapeShape(a, b)
    d.Perform()
    return d.Value() if d.IsDone() else float("nan")


def point_shape(x, y, z):
    return BRepBuilderAPI_MakeVertex(gp_Pnt(x, y, z)).Shape()


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    app, doc = build.open_doc(src)
    info = build.apply_edits(doc, hood_angle=0.0, verbose=False)
    st = info["shape_tool"]
    wheel = st.GetShape_s(info["wheel"])
    hood = st.GetShape_s(info["hood"])
    hinge_y, hinge_z = info["hinge"]

    # ---- 1. hood gap vs flap angle ----
    print("hood flap angle sweep (gap between Gridplate H and the Hogback wheel):")
    gaps = []
    for deg in [0, 2, 4, 6, 8, 10, 12, 14]:
        rotated = BRepBuilderAPI_Transform(hood, build.rotation((0, hinge_y, hinge_z), (1, 0, 0), deg), True).Shape()
        g = dist(rotated, wheel)
        gaps.append((deg, g))
        print(f"   {deg:3d} deg -> gap {g:5.1f} mm")
    # linear interpolation for the NECTAR gap
    nectar_angle = None
    for (a0, g0), (a1, g1) in zip(gaps, gaps[1:]):
        if g0 <= NECTAR_GAP <= g1 or g0 >= NECTAR_GAP >= g1:
            nectar_angle = a0 + (NECTAR_GAP - g0) / (g1 - g0) * (a1 - a0)
            break
    print(f"   stock gap {gaps[0][1]:.1f} mm; NECTAR gap {NECTAR_GAP} mm at {nectar_angle if nectar_angle is None else round(nectar_angle, 1)} deg")

    # ---- 2. ball stations ----
    # structure = everything except the hood (tested separately) and the ball
    parts = []
    for o in info["occ"]:
        parts.append((o["name"], st.GetShape_s(o["label"])))
    wheel_c = build.center(wheel)

    def nearest(cx, cy, cz, radius, exclude=()):
        best = (float("inf"), "")
        p = point_shape(cx, cy, cz)
        for name, shp in parts:
            if any(name.startswith(e) for e in exclude):
                continue
            b = build.bbox(shp)
            if b is None:
                continue
            # cheap reject: bbox further than the best so far
            dx = max(b[0] - cx, 0, cx - b[3])
            dy = max(b[1] - cy, 0, cy - b[4])
            dz = max(b[2] - cz, 0, cz - b[5])
            if math.sqrt(dx * dx + dy * dy + dz * dz) - radius >= best[0]:
                continue
            d = dist(p, shp) - radius
            if d < best[0]:
                best = (d, name)
        return best

    def rest_height(cx, cy, radius, support_prefixes):
        """Lowest z for the ball centre such that it clears the named support parts."""
        z = FLOOR + radius
        for _ in range(60):
            d, _n = nearest(cx, cy, z, radius, exclude=[n for n, _ in parts if not any(n.startswith(s) for s in support_prefixes)])
            if d >= -0.05:
                break
            z += max(0.5, -d)
        return z

    stations = [
        ("intake mouth, floor, in front of the roller bar", 0.0, -160.0, ()),
        ("under the Gecko conveyor (floating roller)", 0.0, -185.5, ()),
        ("on the intake ramp E", 0.0, -60.0, ("1117-0088-0352 (3200-2627-0004_E)",)),
        ("hopper in front of the wheel", -5.0, -40.0, ("1117-0088-0352 (3200-2627-0004_E)", "1117-0088-0352 (3200-2627-0004_F)")),
        ("exit guide between the side walls", 0.0, 140.0, ("1117-0088-0352 (3200-2627-0004_G)",)),
    ]
    rows = []
    print("\nball stations (clearance to the nearest part; negative = interference the part must absorb):")
    for ball, dia in BALLS.items():
        r = dia / 2
        for label, x, y, support in stations:
            z = rest_height(x, y, r, support) if support else FLOOR + r
            d, name = nearest(x, y, z, r, exclude=support)
            rows.append({"ball": ball, "station": label, "x": x, "y": y, "z": round(z, 1), "clearance_mm": round(d, 1), "nearest": name})
            print(f"   {ball:<22} {label:<46} z={z - FLOOR:6.1f} mm  clearance {d:6.1f} mm  ({name})")
        # launcher squeeze: ball centred in the gap above/in front of the wheel
        for hood_name, gap in (("hood POLLEN position", gaps[0][1]), ("hood NECTAR position", NECTAR_GAP)):
            squeeze = dia - gap
            rows.append({"ball": ball, "station": f"launcher squeeze, {hood_name}", "clearance_mm": round(-squeeze, 1), "nearest": "3626-0014-0096 / Gridplate H"})
            print(f"   {ball:<22} launcher squeeze, {hood_name:<26} gap {gap:5.1f} mm -> squeeze {squeeze:5.1f} mm")

    json.dump({"hood_gap_vs_angle": gaps, "nectar_hood_angle_deg": nectar_angle, "stations": rows},
              open(os.path.join(out, "clearance_sim.json"), "w"), indent=1)
    print("wrote", os.path.join(out, "clearance_sim.json"))


if __name__ == "__main__":
    main()
