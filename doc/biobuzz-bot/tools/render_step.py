#!/usr/bin/env python3
"""
Shaded render of a STEP (or cached .xbf) assembly with OpenCascade meshing and matplotlib.

Every top-level component is meshed, triangles are projected for four views (three
orthographic, one isometric), depth-sorted and drawn with flat Lambert shading in the
component's STEP colour (grey when it has none).

    python3 render_step.py <model.step|model.xbf> <out.png> [--title "..."]
"""
import math
import sys
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_Color
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDF import TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_DocumentTool

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
LIGHT = np.array([0.4, -0.6, 0.7])
LIGHT /= np.linalg.norm(LIGHT)


def open_doc(path):
    app = XCAFApp_Application.GetApplication_s()
    BinXCAFDrivers.DefineFormat_s(app)
    doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    if path.lower().endswith(".xbf"):
        app.Open(TCollection_ExtendedString(path), doc)
    else:
        app.InitDocument(doc)
        r = STEPCAFControl_Reader()
        r.SetNameMode(True)
        r.SetColorMode(True)
        assert r.ReadFile(path) == IFSelect_RetDone
        r.Transfer(doc)
    return doc


def face_colour(color_tool, label, face_shape, default):
    c = Quantity_Color()
    for ct in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen):
        if color_tool.GetColor(face_shape, ct, c):
            return (c.Red(), c.Green(), c.Blue())
    for ct in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen):
        if color_tool.GetColor(label, ct, c):
            return (c.Red(), c.Green(), c.Blue())
    return default


def mesh_shape(shape, deflection=0.6):
    """Return (Nx3 vertices, Mx3 triangle indices) for the shape."""
    BRepMesh_IncrementalMesh(shape, deflection, False, 0.5, True)
    verts, tris = [], []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            base = len(verts)
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            rev = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                if rev:
                    b, c = c, b
                tris.append((base + a - 1, base + b - 1, base + c - 1))
        exp.Next()
    return np.array(verts, dtype=np.float32), np.array(tris, dtype=np.int64)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    title = sys.argv[sys.argv.index("--title") + 1] if "--title" in sys.argv else src
    t0 = time.time()
    doc = open_doc(src)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    root = roots.Value(1)
    comps = TDF_LabelSequence()
    shape_tool.GetComponents_s(root, comps)
    all_v, all_t, all_c = [], [], []
    offset = 0
    for i in range(1, comps.Length() + 1):
        lab = comps.Value(i)
        shape = shape_tool.GetShape_s(lab)
        v, t = mesh_shape(shape)
        if not len(t):
            continue
        col = face_colour(color_tool, lab, shape, (0.72, 0.72, 0.72))
        all_v.append(v)
        all_t.append(t + offset)
        all_c.append(np.tile(np.array(col, dtype=np.float32), (len(t), 1)))
        offset += len(v)
    V = np.concatenate(all_v)
    T = np.concatenate(all_t)
    C = np.concatenate(all_c)
    print(f"meshed {comps.Length()} components: {len(V):,} vertices, {len(T):,} triangles, {time.time() - t0:.0f}s")

    # face normals for shading (computed in model space)
    p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(p1 - p0, p2 - p0)
    nn = np.linalg.norm(n, axis=1)
    keep = nn > 1e-9
    T, C, n = T[keep], C[keep], n[keep] / nn[keep][:, None]
    p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]

    def view(R):
        """Project with rotation matrix R (rows = screen x, screen y, depth)."""
        q0, q1, q2 = p0 @ R.T, p1 @ R.T, p2 @ R.T
        depth = (q0[:, 2] + q1[:, 2] + q2[:, 2]) / 3
        nv = n @ R.T
        # cull back faces (looking down -depth) and shade
        front = nv[:, 2] > -0.05
        lam = np.clip(nv @ np.array([0.3, 0.5, 0.81]), 0, 1)
        shade = 0.45 + 0.55 * lam
        cols = np.clip(C * shade[:, None], 0, 1)
        order = np.argsort(depth[front])
        polys = np.stack([q0[front][order][:, :2], q1[front][order][:, :2], q2[front][order][:, :2]], axis=1)
        return polys, cols[front][order]

    def rot_x(a):
        a = math.radians(a)
        return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])

    def rot_z(a):
        a = math.radians(a)
        return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])

    # screen axes: rows are (screen x, screen y, towards viewer)
    views = [
        ("Front (looking at the intake, -Y)", np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]])),
        ("Right side (+X)", np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]])),
        ("Top (+Z)", np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]])),
        ("Isometric", None),
    ]
    iso = rot_x(-62) @ rot_z(-35)          # tilt then turn
    R_iso = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]]) @ rot_x(-28) @ rot_z(-40)
    fig, axes = plt.subplots(2, 2, figsize=(16, 13), facecolor=SURFACE)
    for ax, (name, R) in zip(axes.reshape(-1), views):
        if R is None:
            R = R_iso
        polys, cols = view(R)
        ax.set_facecolor(SURFACE)
        ax.add_collection(PolyCollection(polys, facecolors=cols, edgecolors="none", antialiased=False))
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_title(name, loc="left", color=INK, fontsize=12)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(GRID)
    fig.suptitle(title, x=0.02, ha="left", fontsize=15, color=INK)
    plt.tight_layout(rect=(0, 0, 1, 0.97))
    plt.savefig(dst, dpi=110, facecolor=SURFACE)
    print(f"wrote {dst}, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
