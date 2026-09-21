#!/usr/bin/env python3
"""
Launch physics for POLLEN and NECTAR from the StarterBot Hogback launcher.

Integrates a point-mass trajectory with quadratic air drag for both scoring
elements and draws them on one chart, together with the estimated HIVE CELL
target band.  Also prints the numbers quoted in README.md.

    python3 trajectory.py <out_dir>
"""
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"

RHO = 1.20          # kg/m^3
CD = 0.47           # smooth sphere, sub-critical Reynolds number
G = 9.81

ELEMENTS = {
    # name: (diameter m, mass kg)  — Section 9.8 / AndyMark am-5851, am-5852
    "POLLEN": (0.0711, 0.0249),
    "NECTAR": (0.0919, 0.0413),
}

# StarterBot launcher: 96 mm Hogback wheel, goBILDA target 1250 ticks/s at 28 ticks/rev.
WHEEL_D = 0.096
TICKS_PER_REV = 28
TARGET_TPS = 1250
BALL_SPEED_RATIO = 0.5      # single wheel + fixed hood: ball leaves at ~half the surface speed

EXIT_HEIGHT = 0.30          # m above the tiles, top of the hood (plate H reaches 307 mm)
LAUNCH_ANGLE_DEG = 50       # assumed hood exit angle; measure on the real robot

# HIVE: pivot axis 43.95 in above the tiles (9.6.1); the upward CELL opening sits above it.
PIVOT_H = 1.1165
TARGET_LOW, TARGET_HIGH = PIVOT_H + 0.20, PIVOT_H + 0.45   # estimated band, verify on a field


def ballistic_coefficient(d, m):
    area = math.pi * (d / 2) ** 2
    return 0.5 * RHO * CD * area / m      # 1/m : deceleration = k v^2


def trajectory(v0, angle_deg, k, dt=0.002, tmax=3.0):
    vx, vy = v0 * math.cos(math.radians(angle_deg)), v0 * math.sin(math.radians(angle_deg))
    x, y = 0.0, EXIT_HEIGHT
    xs, ys = [x], [y]
    t = 0
    while y >= 0 and t < tmax:
        v = math.hypot(vx, vy)
        ax = -k * v * vx
        ay = -G - k * v * vy
        vx += ax * dt
        vy += ay * dt
        x += vx * dt
        y += vy * dt
        t += dt
        xs.append(x)
        ys.append(y)
    return np.array(xs), np.array(ys)


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)

    surface = TARGET_TPS / TICKS_PER_REV * math.pi * WHEEL_D
    v_ball = surface * BALL_SPEED_RATIO
    print(f"wheel {TARGET_TPS} t/s = {TARGET_TPS / TICKS_PER_REV * 60:.0f} rpm, surface {surface:.1f} m/s, ball ~{v_ball:.1f} m/s")
    for name, (d, m) in ELEMENTS.items():
        k = ballistic_coefficient(d, m)
        e = 0.5 * m * v_ball ** 2
        print(f"{name}: k = {k:.4f} /m, kinetic energy per shot at {v_ball:.1f} m/s = {e:.2f} J, momentum {m * v_ball:.3f} kg m/s")

    fig, ax = plt.subplots(figsize=(10, 5.2), facecolor=SURFACE)
    style(ax)
    ax.axhspan(TARGET_LOW, TARGET_HIGH, color=GRID, alpha=0.8, lw=0)
    ax.text(0.05, TARGET_HIGH + 0.03, "upward CELL opening, estimated 1.3-1.55 m (pivot at 1.12 m)",
            color=INK2, fontsize=9)
    ax.axhline(PIVOT_H, color=AXIS, lw=1, ls="--")
    speeds = [v_ball * 0.85, v_ball, v_ball * 1.15]
    for (name, (d, m)), col in zip(ELEMENTS.items(), (BLUE, ORANGE)):
        k = ballistic_coefficient(d, m)
        for i, v in enumerate(speeds):
            xs, ys = trajectory(v, LAUNCH_ANGLE_DEG, k)
            # POLLEN is drawn wide underneath, NECTAR narrow on top: the two paths coincide.
            wide = name == "POLLEN"
            ax.plot(xs, ys, color=col, lw=(4 if wide else 1.6) if i == 1 else (2.4 if wide else 1.0),
                    alpha=1 if i == 1 else 0.55, ls="-" if i == 1 else "--",
                    label=name if i == 1 else None, zorder=2 if wide else 3)
            if name == "NECTAR":
                j = int(len(xs) * 0.45)
                ax.text(xs[j], ys[j] + 0.04, f"{v:.1f} m/s", color=INK2, fontsize=8, ha="center")
    ax.set_xlim(0, 4.0)
    ax.set_ylim(0, 2.2)
    ax.set_xlabel("horizontal distance from the launcher, m", color=INK2)
    ax.set_ylabel("height above tiles, m", color=INK2)
    ax.set_title(f"POLLEN and NECTAR fly the same path: {LAUNCH_ANGLE_DEG}° exit, drag included",
                 loc="left", color=INK, fontsize=12)
    ax.legend(frameon=False, loc="upper right")
    plt.tight_layout()
    plt.savefig(os.path.join(out, "trajectory.png"), dpi=150, facecolor=SURFACE)
    print("wrote", os.path.join(out, "trajectory.png"))


if __name__ == "__main__":
    main()
