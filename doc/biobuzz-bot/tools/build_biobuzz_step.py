#!/usr/bin/env python3
"""
Build the BIOBUZZ bot STEP file from the goBILDA StarterBot 3200-2627-0004 STEP.

The StarterBot assembly is opened with OpenCascade XDE (names, colours and the assembly tree
are kept) and edited in place:

  * the two vertical tower channels and everything bolted to them move 16 mm outboard
    (two holes on the 8 mm pattern), so the launcher bay between them grows from 88 to 120 mm;
  * the curved exit guide (Gridplate G) is re-cut 112 mm wide (scaled in X);
  * the launcher motor, hub and Hogback wheel stay centred (re-mounted two holes inboard on
    the moved arm);
  * new parts are added as simplified solids: hood hinges, hood servo + ServoBlock (copies of the
    kit's own servo and ServoBlock), crank and pushrod beams, two intake springs, a colour sensor.

Usage:
    python3 build_biobuzz_step.py <starterbot.step> <out.step> [--hood-angle DEG] [--pcurves]

`--hood-angle` rotates the hood flap open about its hinge (the NECTAR position; see
clearance_sim.py for the angle that gives the required gap).
Requires cadquery (pip install cadquery), which brings the OCP OpenCascade bindings.
"""
import math
import sys
import time

from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform, BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_GTrsf, gp_Mat, gp_Pnt, gp_Trsf, gp_Vec, gp_XYZ
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_DocumentTool, XCAFDoc_Location

FLOOR = -52.0          # model z of the tile surface (bottom of the mecanum wheels)
TOWER_SHIFT = 16.0     # mm outboard per side
GUIDE_SCALE = 112.0 / 88.0

# ---------------------------------------------------------------- document helpers


def open_doc(path):
    app = XCAFApp_Application.GetApplication_s()
    BinXCAFDrivers.DefineFormat_s(app)
    doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    if path.lower().endswith(".xbf"):
        app.Open(TCollection_ExtendedString(path), doc)
    else:
        app.InitDocument(doc)
        reader = STEPCAFControl_Reader()
        reader.SetNameMode(True)
        reader.SetColorMode(True)
        assert reader.ReadFile(path) == IFSelect_RetDone
        reader.Transfer(doc)
    return app, doc


def name_of(label):
    n = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), n):
        return n.Get().ToExtString()
    return ""


def bbox(shape):
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b, False)
    if b.IsVoid():
        return None
    return b.Get()


def center(shape):
    x0, y0, z0, x1, y1, z1 = bbox(shape)
    return (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2


def translation(dx, dy, dz):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    return t


def rotation(axis_point, axis_dir, degrees):
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(*axis_point), gp_Dir(*axis_dir)), math.radians(degrees))
    return t


def box(x0, y0, z0, x1, y1, z1):
    return BRepPrimAPI_MakeBox(gp_Pnt(min(x0, x1), min(y0, y1), min(z0, z1)),
                               gp_Pnt(max(x0, x1), max(y0, y1), max(z0, z1))).Shape()


def cylinder_between(p0, p1, radius):
    v = gp_Vec(gp_Pnt(*p0), gp_Pnt(*p1))
    length = v.Magnitude()
    ax = gp_Ax2(gp_Pnt(*p0), gp_Dir(v))
    return BRepPrimAPI_MakeCylinder(ax, radius, length).Shape()


def beam_between(p0, p1, width=8.0, thick=4.0):
    """A flat beam (1102 series look-alike) from p0 to p1, built as a box then rotated."""
    v = gp_Vec(gp_Pnt(*p0), gp_Pnt(*p1))
    length = v.Magnitude()
    raw = box(0, -width / 2, -thick / 2, length, width / 2, thick / 2)
    d = gp_Dir(v)
    # rotate the +X box axis onto d
    x = gp_Dir(1, 0, 0)
    t = gp_Trsf()
    if abs(x.Dot(d)) < 0.9999:
        axis = x.Crossed(d)
        t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), axis), math.acos(x.Dot(d)))
    elif x.Dot(d) < 0:
        t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), math.pi)
    shape = BRepBuilderAPI_Transform(raw, t, True).Shape()
    return BRepBuilderAPI_Transform(shape, translation(*p0), True).Shape()


# ---------------------------------------------------------------- the edit


def apply_edits(doc, hood_angle=0.0, verbose=True):
    """Edit the StarterBot document in place. Returns a dict of the key labels/shapes."""
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    root = roots.Value(1)
    comps = TDF_LabelSequence()
    shape_tool.GetComponents_s(root, comps)
    log = print if verbose else (lambda *a, **k: None)
    log(f"root '{name_of(root)}' with {comps.Length()} top-level components")

    occ = []
    for i in range(1, comps.Length() + 1):
        lab = comps.Value(i)
        shp = shape_tool.GetShape_s(lab)
        occ.append({"label": lab, "name": name_of(lab), "shape": shp, "bbox": bbox(shp)})

    def find(name_prefix, pred=lambda o: True):
        return [o for o in occ if o["name"].startswith(name_prefix) and pred(o)]

    def cx(o):
        return (o["bbox"][0] + o["bbox"][3]) / 2

    def cy(o):
        return (o["bbox"][1] + o["bbox"][4]) / 2

    moved = []

    def move(o, dx):
        loc = shape_tool.GetLocation_s(o["label"])
        XCAFDoc_Location.Set_s(o["label"], TopLoc_Location(translation(dx, 0, 0)) * loc)
        moved.append((o["name"], dx))

    # ---- 1. everything that rides on a tower moves outboard ----
    towers = find("1120-0010-0264")
    assert len(towers) == 2, [o["name"] for o in towers]
    for o in towers:
        move(o, math.copysign(TOWER_SHIFT, cx(o)))
    # tower feet and quad blocks in the tower footprint (not the launcher motor's at x ~ 26)
    for o in find("1201-0043-0002", lambda o: 40 < abs(cx(o)) < 100 and cy(o) > -60):
        move(o, math.copysign(TOWER_SHIFT, cx(o)))
    # forward arms (5-hole low channels), the 2-hole channel, the windmill servo and its ServoBlock
    for prefix in ("1121-0005-0144", "1120-0002-0072", "3217-0001-2501", "2000-0025-0002"):
        for o in find(prefix, lambda o: 40 < abs(cx(o)) < 110 and cy(o) > -60):
            move(o, math.copysign(TOWER_SHIFT, cx(o)))
    # the four windmill paddles (Gridplate A) turn on the windmill servo, left side
    for o in find("1117-0040-0352 (3200-2627-0004_A)"):
        move(o, -TOWER_SHIFT)
    # guide side walls C ride on the tower inner faces; plate B sits on the guide's edge
    for o in find("1117-0040-0352 (3200-2627-0004_C)"):
        move(o, math.copysign(TOWER_SHIFT, cx(o)))
    for o in find("1117-0040-0352 (3200-2627-0004_B)"):
        move(o, math.copysign(44.0 * (GUIDE_SCALE - 1.0), cx(o)))
    log("moved: " + ", ".join(f"{n} {dx:+.0f}" for n, dx in moved))

    # ---- 2. re-cut the exit guide G wider: scale its referred shape in X about its centre ----
    g = find("1117-0088-0352 (3200-2627-0004_G)")[0]
    ref = TDF_Label()
    shape_tool.GetReferredShape_s(g["label"], ref)
    ref_shape = shape_tool.GetShape_s(ref)
    gx = center(ref_shape)[0]
    gt = gp_GTrsf()
    gt.SetVectorialPart(gp_Mat(GUIDE_SCALE, 0, 0, 0, 1, 0, 0, 0, 1))
    gt.SetTranslationPart(gp_XYZ(gx * (1 - GUIDE_SCALE), 0, 0))
    wide = BRepBuilderAPI_GTransform(ref_shape, gt, True).Shape()
    shape_tool.SetShape(ref, wide)
    TDataStd_Name.Set_s(ref, TCollection_ExtendedString("1117-0216-0352 cut G' 14x35 (112 mm guide)"))
    log(f"guide G scaled x{GUIDE_SCALE:.3f}")

    # ---- 3. hood as a flap hinged along the top-front edge of Gridplate H ----
    h = find("1117-0216-0352 (3200-2627-0004_H)")[0]
    hx0, hy0, hz0, hx1, hy1, hz1 = h["bbox"]
    hinge_y, hinge_z = hy0, hz1
    if abs(hood_angle) > 1e-6:
        loc = shape_tool.GetLocation_s(h["label"])
        XCAFDoc_Location.Set_s(h["label"], TopLoc_Location(rotation((0, hinge_y, hinge_z), (1, 0, 0), hood_angle)) * loc)
        log(f"hood rotated {hood_angle:+.1f} deg about its top edge")

    new_parts = []

    def add(shape, name, rgb):
        lab = shape_tool.AddComponent(root, shape, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(name))
        color_tool.SetColor(lab, Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorGen)
        new_parts.append(name)
        return lab

    steel = (0.75, 0.75, 0.78)
    black = (0.15, 0.15, 0.15)
    green = (0.10, 0.55, 0.25)
    for x in (-70.0, 70.0):
        add(box(x - 19, hinge_y - 6, hinge_z, x + 19, hinge_y + 6, hinge_z + 4), "2902-0005-0038 hinge (hood)", steel)

    # ---- 4. hood servo + ServoBlock: copies of the kit's own parts on the right tower's outer face ----
    right_tower = max(towers, key=cx)
    tx0, ty0, tz0, tx1, ty1, tz1 = bbox(shape_tool.GetShape_s(right_tower["label"]))
    servo_src = find("2000-0025-0002")[0]
    block_src = find("3217-0001-2501", lambda o: abs(cx(o)) < 110)[0]
    servo_target = (tx1 + 14.0, hy1 - 20.0, hz0 + 60.0)
    for src_o, label in ((block_src, "3217-0001-2501 Compact ServoBlock (hood)"),
                         (servo_src, "2000-0025-0002 torque servo (hood)")):
        sc = center(src_o["shape"])
        t = translation(servo_target[0] - sc[0], servo_target[1] - sc[1], servo_target[2] - sc[2])
        add(BRepBuilderAPI_Transform(src_o["shape"], t, True).Shape(), label, black)
    crank_root = (servo_target[0] + 22.0, servo_target[1], servo_target[2])
    crank_tip = (crank_root[0], crank_root[1] - 20.0, crank_root[2] - 69.0)
    add(beam_between(crank_root, crank_tip), "1102-0009-0072 flat beam (hood crank)", steel)
    hood_link = (hx1 - 6.0, hy1 - 8.0, hz0 + 8.0)
    add(beam_between(crank_tip, hood_link), "1102-0009-0072 flat beam (hood pushrod)", steel)

    # ---- 5. intake springs: from the conveyor carrier down to the side rails ----
    carriers = find("1120-0008-0216")
    if carriers:
        c = carriers[0]["bbox"]
        for x in (c[0] + 10.0, c[3] - 10.0):
            top = (x, c[1] + 8.0, c[2] + 6.0)
            bottom = (math.copysign(150.0, x), c[1] + 8.0, FLOOR + 60.0)
            add(cylinder_between(top, bottom, 3.25), "2915-0001-0003 extension spring (floating intake)", steel)

    # ---- 6. colour sensor on the inner face of the left guide wall ----
    walls = find("1117-0040-0352 (3200-2627-0004_C)")
    if walls:
        left = min(walls, key=cx)
        wb = bbox(shape_tool.GetShape_s(left["label"]))
        add(box(wb[3], wb[1] + 20.0, wb[2] + 8.0, wb[3] + 8.0, wb[1] + 50.0, wb[2] + 28.0),
            "REV-31-1557 Color Sensor V3 (element sensor)", green)

    shape_tool.UpdateAssemblies()
    TDataStd_Name.Set_s(root, TCollection_ExtendedString("biobuzz-bot (from 3200-2627-0004)"))
    log("added: " + ", ".join(new_parts))
    return {"root": root, "shape_tool": shape_tool, "hood": h["label"], "hinge": (hinge_y, hinge_z),
            "wheel": find("3626-0014-0096")[0]["label"], "towers": [o["label"] for o in towers],
            "guide": g["label"], "walls": [o["label"] for o in walls], "occ": occ}


def main():
    src, dst = sys.argv[1], sys.argv[2]
    hood_angle = float(sys.argv[sys.argv.index("--hood-angle") + 1]) if "--hood-angle" in sys.argv else 0.0
    t0 = time.time()
    app, doc = open_doc(src)
    print(f"opened {src}, {time.time() - t0:.0f}s")
    apply_edits(doc, hood_angle)
    # Leave the parametric (p-)curves out of the file: readers rebuild them, and the file is
    # roughly half the size. Pass --pcurves to keep them.
    Interface_Static.SetIVal_s("write.surfacecurve.mode", 1 if "--pcurves" in sys.argv else 0)
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    writer.Transfer(doc, STEPControl_AsIs)
    status = writer.Write(dst)
    print(f"wrote {dst}: {status}, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
