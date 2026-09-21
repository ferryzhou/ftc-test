#!/usr/bin/env python3
"""
Two launcher simulations for the BIOBUZZ bot.

1. Flywheel dynamics: the 1:1 Yellow Jacket driving the 96 mm Hogback wheel under the FTC SDK
   velocity PIDF (P=40, F=12.5), spin-up from rest, the speed droop when a POLLEN or a NECTAR
   is launched, and the recovery time back above the minimum velocity. Gives the shot cadence.

2. Monte Carlo of the shot: exit speed, exit angle and ball diameter are jittered, the drag
   trajectory is integrated, and a hit is counted when the ball crosses the CELL opening plane
   while descending inside the CELL's 12 in depth. Gives hit probability against distance for
   both balls at three velocity settings.

    python3 shot_sim.py <out_dir>
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
BLUE_L, ORANGE_L = "#9ec5f4", "#f5b79b"

# ---- scoring elements (Section 9.8, AndyMark) ----
ELEMENTS = {"POLLEN": (0.0711, 0.0249), "NECTAR": (0.0919, 0.0413)}
RHO, CD, G = 1.20, 0.47, 9.81

# ---- launcher ----
WHEEL_R = 0.048                  # Hogback 96 mm
I_WHEEL = 1.6e-4                 # kg m^2, ASSUMED: ~0.14 kg wheel with most mass near the rim
I_ROTOR = 1.0e-5                 # kg m^2, ASSUMED: bare 5000-series rotor + hub
I_TOTAL = I_WHEEL + I_ROTOR
MOTOR_FREE_RPM = 6000            # 5203-2402-0019 is 312 rpm through 19.2:1 -> ~6000 rpm bare
MOTOR_STALL_NM = 0.124           # 24.3 kg cm / 19.2 at the bare motor
TICKS_PER_REV = 28
BALL_SPEED_RATIO = 0.5           # ball exit speed / wheel surface speed
SHOT_ENERGY_FACTOR = 1.5         # wheel energy taken per shot / ball kinetic energy (spin + slip)

# ---- SDK velocity controller: power = (F*target + P*(target - v)) / 32767, clipped to [-1, 1] ----
PIDF_P, PIDF_F = 40.0, 12.5
TARGETS = {"POLLEN": (1250, 1200), "NECTAR": (1250, 1200)}   # (target, minimum) ticks/s

# ---- HIVE ----
PIVOT_H = 1.1165
CELL_H = 1.45                    # ESTIMATED height of the upward CELL opening
CELL_DEPTH = 0.305               # 12 in
EXIT_HEIGHT = 0.30
EXIT_ANGLE = 50.0                # ASSUMED hood exit angle, degrees


def rpm_to_tps(rpm):
    return rpm / 60.0 * TICKS_PER_REV


def tps_to_omega(tps):
    return tps / TICKS_PER_REV * 2 * math.pi


def motor_torque(power, omega):
    """Linear DC motor: torque = stall * (power - omega/omega_free)."""
    w_free = MOTOR_FREE_RPM / 60 * 2 * math.pi
    return MOTOR_STALL_NM * (power - omega / w_free)


def controller_power(target_tps, v_tps):
    p = (PIDF_F * target_tps + PIDF_P * (target_tps - v_tps)) / 32767.0
    return max(-1.0, min(1.0, p))


def simulate_flywheel(name, dt=0.001, shots=4):
    """Spin up from rest, then launch `shots` elements as soon as the wheel is above minimum."""
    d, m = ELEMENTS[name]
    target, vmin = TARGETS[name]
    omega = 0.0
    t = 0.0
    ts, vs = [], []
    shot_times = []
    fired = 0
    settle = 0.0
    while t < 6.0 and fired < shots + 0:
        v_tps = omega / (2 * math.pi) * TICKS_PER_REV
        power = controller_power(target, v_tps)
        alpha = motor_torque(power, omega) / I_TOTAL
        omega += alpha * dt
        t += dt
        ts.append(t)
        vs.append(v_tps)
        # feed as soon as the wheel is above the minimum and 0.1 s after the previous shot
        if v_tps >= vmin and (not shot_times or t - shot_times[-1] > 0.1):
            v_ball = BALL_SPEED_RATIO * omega * WHEEL_R
            e = SHOT_ENERGY_FACTOR * 0.5 * m * v_ball ** 2
            omega = math.sqrt(max(0.0, omega ** 2 - 2 * e / I_TOTAL))
            shot_times.append(t)
            fired += 1
    return np.array(ts), np.array(vs), shot_times


def trajectory(v0, angle_deg, k, dt=0.002):
    vx, vy = v0 * math.cos(math.radians(angle_deg)), v0 * math.sin(math.radians(angle_deg))
    x, y = 0.0, EXIT_HEIGHT
    pts = [(x, y, vy)]
    while y >= 0 and x < 6:
        v = math.hypot(vx, vy)
        vx += -k * v * vx * dt
        vy += (-G - k * v * vy) * dt
        x += vx * dt
        y += vy * dt
        pts.append((x, y, vy))
    return np.array(pts)


def crossing_distance(pts, h):
    """Horizontal distance where the descending branch crosses height h, or None."""
    for i in range(1, len(pts)):
        x0, y0, vy0 = pts[i - 1]
        x1, y1, vy1 = pts[i]
        if vy0 < 0 and y0 >= h > y1:
            f = (y0 - h) / (y0 - y1)
            return x0 + f * (x1 - x0)
    return None


def monte_carlo(name, target_tps, distances, n=400, rng=None):
    d, m = ELEMENTS[name]
    rng = rng or np.random.default_rng(1)
    v_nom = BALL_SPEED_RATIO * tps_to_omega(target_tps) * WHEEL_R
    hits = np.zeros(len(distances))
    for _ in range(n):
        v = v_nom * (1 + rng.normal(0, 0.03))
        ang = EXIT_ANGLE + rng.normal(0, 2.0)
        dd = d * (1 + rng.normal(0, 0.02))
        k = 0.5 * RHO * CD * math.pi * (dd / 2) ** 2 / m
        xc = crossing_distance(trajectory(v, ang, k), CELL_H)
        if xc is None:
            continue
        hits += (np.abs(distances - xc) <= CELL_DEPTH / 2)
    return hits / n


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

    # ---- 1. flywheel ----
    fig, ax = plt.subplots(figsize=(10, 4.6), facecolor=SURFACE)
    style(ax)
    summary = {}
    for name, col in (("POLLEN", BLUE), ("NECTAR", ORANGE)):
        ts, vs, shots = simulate_flywheel(name)
        target, vmin = TARGETS[name]
        ax.plot(ts, vs, color=col, lw=2, label=name)
        ax.axhline(vmin, color=col, lw=0.8, ls=":")
        for s in shots:
            ax.axvline(s, color=col, lw=0.6, alpha=0.4)
        gaps = np.diff(shots)
        droop = None
        if len(shots) > 1:
            i = np.searchsorted(ts, shots[0])
            droop = vs[i - 1] - vs[min(i + 1, len(vs) - 1)]
        summary[name] = {"spinup_s": shots[0] if shots else None,
                         "shot_gap_s": float(np.mean(gaps)) if len(gaps) else None,
                         "droop_tps": float(droop) if droop is not None else None}
    ax.set_xlabel("time, s", color=INK2)
    ax.set_ylabel("launcher velocity, ticks/s", color=INK2)
    ax.set_title("Flywheel spin-up and four shots: the wheel must recover above the dotted minimum before each feed",
                 loc="left", color=INK, fontsize=11)
    ax.legend(frameon=False, loc="lower right")
    plt.tight_layout()
    plt.savefig(os.path.join(out, "sim_flywheel.png"), dpi=150, facecolor=SURFACE)
    plt.close(fig)

    # ---- 2. Monte Carlo hit probability ----
    distances = np.linspace(1.0, 3.8, 57)
    fig, ax = plt.subplots(figsize=(10, 4.6), facecolor=SURFACE)
    style(ax)
    best = {}
    for name, col, col_l in (("POLLEN", BLUE, BLUE_L), ("NECTAR", ORANGE, ORANGE_L)):
        target, _ = TARGETS[name]
        for scale, lw, c in ((0.9, 1.2, col_l), (1.0, 2.4, col), (1.1, 1.2, col_l)):
            p = monte_carlo(name, target * scale, distances)
            ax.plot(distances, p, color=c, lw=lw, label=f"{name} at {int(target * scale)} t/s" if scale == 1.0 else None,
                    ls="-" if scale == 1.0 else "--")
            if scale == 1.0:
                j = int(np.argmax(p))
                best[name] = (float(distances[j]), float(p[j]))
                ax.text(distances[j], p[j] + 0.03, f"{p[j]:.0%} at {distances[j]:.1f} m", color=INK2, fontsize=8, ha="center")
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("horizontal distance from launcher to the CELL centre, m", color=INK2)
    ax.set_ylabel("hit probability", color=INK2)
    ax.set_title("Monte Carlo (400 shots per point): speed ±3 %, angle ±2°, diameter ±2 %; thin lines are ±10 % velocity",
                 loc="left", color=INK, fontsize=11)
    ax.legend(frameon=False, loc="upper right")
    plt.tight_layout()
    plt.savefig(os.path.join(out, "sim_hit_probability.png"), dpi=150, facecolor=SURFACE)
    plt.close(fig)

    for name in ("POLLEN", "NECTAR"):
        s = summary[name]
        print(f"{name}: spin-up to minimum {s['spinup_s']:.2f} s, droop per shot {s['droop_tps']:.0f} t/s, "
              f"shot gap {s['shot_gap_s']:.2f} s, best hit {best[name][1]:.0%} at {best[name][0]:.1f} m")


if __name__ == "__main__":
    main()
