#!/usr/bin/env python3
"""Results CSVs -> plots.

  python3 scripts/plot.py

results/steady.svg      loop flow and core temperature rise vs core power: the 1D and the 2D
                        model and the experiment
results/2d/fields.svg   2D model at step 5: temperature in the vessel, velocity in the two plena
results/transient.svg   the transient runs through the power history, with the steady end states
Needs matplotlib.
"""
import csv
import math
import pathlib
import re

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "sp3"   # the same SVG for the same data
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.tri as mtri  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Colour-blind-safe colours (Okabe-Ito); open circle and x, so both models show.
MODELS = [("1d", "1D model", dict(color="#D55E00", marker="o", ms=7, zorder=3)),   # circle on top
          ("2d", "2D model", dict(color="#009E73", marker="x", ms=7))]
EXP = dict(fmt="_", color="black", ms=12, mew=1.5, capsize=3, elinewidth=1.2)   # tick at the value
SOURCE = ("Experiment: IAEA-TECDOC-1733 (OSU-MASLWR test SP-3), error bars ±u; "
          "step 1 (grey): table value, the flow oscillated. Details: README.")


def read(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def num(s):
    return float(s) if s not in ("", None) else None


def steady_plot():
    exp = read(ROOT / "experiment/sp3_experiment.csv")
    q_e = [float(r["Q_nominal_kW"]) for r in exp]

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    panels = [("mdot_kg_s", "mdot_u_kg_s", "loop mass flow rate [kg/s]"),
              ("dT_core_K", "dT_core_u_K", "core temperature rise [K]")]
    for ax, (col, ucol, label) in zip(axes, panels):
        for name, text, style in MODELS:
            path = ROOT / f"results/{name}/steady.csv"
            if path.exists():
                rows = read(path)
                ax.plot([float(r["Q_W"]) / 1e3 for r in rows], [float(r[col]) for r in rows],
                        ls="none", mfc="none", mew=1.5, label=text, **style)
        with_u = [(q, float(r[col]), num(r[ucol])) for q, r in zip(q_e, exp) if num(r[ucol])]
        ax.errorbar([a for a, _, _ in with_u], [b for _, b, _ in with_u],
                    yerr=[c for _, _, c in with_u], label="experiment", **EXP)
        no_u = [(q, float(r[col])) for q, r in zip(q_e, exp) if not num(r[ucol])]
        ax.errorbar([a for a, _ in no_u], [b for _, b in no_u], label="experiment, step 1",
                    **{**EXP, "color": "0.6"})
        ax.set_xlabel("core power [kW]")
        ax.set_ylabel(label)
        ax.set_xlim(0, 340)
        ax.set_ylim(bottom=0)
        ax.grid(color="0.9", lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[0].legend(frameon=False, loc="lower right")
    fig.text(0.01, 0.01, SOURCE, fontsize=7.5, color="0.35", va="bottom")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(ROOT / "results/steady.svg", dpi=150, metadata={"Date": None})
    print("wrote results/steady.svg")


def parameters():
    text = re.sub(r"//.*", "", (ROOT / "model/parameters").read_text())
    return {k: float(v) for k, v in re.findall(r"^(\w+)\s+([-+0-9.eE]+);", text, re.M)}


def fields_plot():
    path = ROOT / "results/2d/fields.csv"
    if not path.exists():
        return
    rows = [{k: float(v) for k, v in r.items()} for r in read(path)]
    p = parameters()
    r_low, r_up = (math.sqrt(p[a] / math.pi) for a in ("A_riser_low", "A_riser_up"))

    def wall(z):   # radius of the riser wall at height z
        if z <= p["z_cone_bot"]:
            return r_low
        if z >= p["z_cone_top"]:
            return r_up
        return r_low + (r_up - r_low) * (z - p["z_cone_bot"]) / (p["z_cone_top"] - p["z_cone_bot"])

    def side(inner):
        """The cells of one side of the riser wall (the plena belong to both), as triangles."""
        pts = [c for c in rows if not p["z_bot"] < c["z_m"] < p["z_riser_top"]
               or (c["r_m"] < wall(c["z_m"])) == inner]
        tri = mtri.Triangulation([c["r_m"] for c in pts], [c["z_m"] for c in pts])
        # no triangles across the space next to the riser or the downcomer (5 = radial stretch)
        r, z = tri.x[tri.triangles], tri.y[tri.triangles]
        edge = lambda i, j: ((5 * (r[:, i] - r[:, j])) ** 2 + (z[:, i] - z[:, j]) ** 2) ** 0.5
        tri.set_mask((edge(0, 1) > 0.15) | (edge(1, 2) > 0.15) | (edge(2, 0) > 0.15))
        return tri, pts

    def draw(ax, column, cmap, zoom=None):   # arrows only in a zoom
        for inner in (True, False):
            tri, pts = side(inner)
            values = [column(c) for c in pts]
            mesh = ax.tripcolor(tri, values, cmap=cmap, shading="gouraud", vmin=lo, vmax=hi,
                                rasterized=True)   # an image inside the SVG
        if zoom:
            sel = [c for c in rows if zoom[0] < c["z_m"] < zoom[1]]
            ax.quiver([c["r_m"] for c in sel], [c["z_m"] for c in sel],
                      [c["U_r_m_s"] for c in sel], [c["U_z_m_s"] for c in sel], color="white",
                      angles="xy", scale_units="xy", scale=8, width=0.006)
        zs = [p["z_bot"], p["z_cone_bot"], p["z_cone_top"], p["z_riser_top"]]
        ax.plot([wall(z) for z in zs], zs, color="black", lw=2)
        ax.set_xlabel("radius [m]")
        return mesh

    speed = lambda c: math.hypot(c["U_r_m_s"], c["U_z_m_s"])
    fig, axes = plt.subplots(1, 3, figsize=(11, 7.5), gridspec_kw=dict(width_ratios=[1, 1.5, 1.5]))
    lo, hi = min(c["T_K"] for c in rows), max(c["T_K"] for c in rows)
    m = draw(axes[0], lambda c: c["T_K"], "inferno")
    fig.colorbar(m, ax=axes[0], label="temperature [K]",
                 ticks=matplotlib.ticker.MaxNLocator(integer=True))
    axes[0].set_ylabel("height [m]")
    axes[0].set_title("vessel: temperature")
    lo, hi = 0, max(speed(c) for c in rows)
    for ax, zoom, title in [(axes[1], (p["z_top"] - 0.15, p["z_plenum_top"]), "upper plenum"),
                            (axes[2], (p["z_plenum_bot"], p["z_bot"] + 0.25), "lower plenum")]:
        m = draw(ax, speed, "viridis", zoom=zoom)
        ax.set_ylim(*zoom)
        ax.set_title(title + ": velocity")
        fig.colorbar(m, ax=ax, label="velocity [m/s]")
    fig.suptitle("2D model, step 5 (199 kW). Black: riser wall. Arrows: velocity.",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(ROOT / "results/2d/fields.svg", dpi=150, metadata={"Date": None})
    print("wrote results/2d/fields.svg")


def transient_plot():
    have = [(n, t, s) for n, t, s in MODELS if (ROOT / f"results/{n}/transient.csv").exists()]
    if not have:
        return
    fig, axes = plt.subplots(3, 1, figsize=(9, 7.5), sharex=True)
    for k, (name, text, style) in enumerate(have):
        rows = read(ROOT / f"results/{name}/transient.csv")
        # without the first 300 s: every run starts with the water at rest
        series = [r for r in rows if r["kind"] == "series" and float(r["time_s"]) >= 300]
        ends = [r for r in rows if r["kind"] == "plateau_end"]
        steady = {r["step"]: r for r in read(ROOT / f"results/{name}/steady.csv")}
        if k == 0:
            axes[0].step([0.0] + [float(r["time_s"]) for r in ends],
                         [float(r["Q_W"]) / 1e3 for r in ends] + [float(ends[-1]["Q_W"]) / 1e3],
                         where="post", color="0.3", lw=1.5)
        t = [float(r["time_s"]) for r in series]
        for ax, col in [(axes[1], "mdot_kg_s"), (axes[2], "dT_core_K")]:
            # solid lines, 1D wide below 2D, so both show where they coincide
            ax.plot(t, [float(r[col]) for r in series], color=style["color"], lw=3.5 - 2 * k,
                    label=f"{text}, transient")
            ax.plot([float(r["time_s"]) for r in ends],
                    [float(steady[r["step"]][col]) for r in ends], ls="none",
                    marker=style["marker"], ms=style["ms"], mfc="none", mec=style["color"],
                    mew=1.5, label=f"{text}, steady run")
    axes[0].set_ylabel("core power [kW]")
    axes[1].set_ylabel("loop mass flow rate [kg/s]")
    axes[2].set_ylabel("core temperature rise [K]")
    axes[1].legend(frameon=False, loc="lower right", fontsize=8)
    axes[2].set_xlabel("time [s] (test starts at 2000 s)")
    axes[2].set_xlim(left=300)
    for ax in axes:
        ax.grid(color="0.9", lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.text(0.01, 0.01, "Models only. Power history: IAEA-TECDOC-1733 Table 3-9, after a 2000 s "
             "start-up at the first power; its first 300 s (start from rest) are not shown.",
             fontsize=7.5, color="0.35", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(ROOT / "results/transient.svg", dpi=150, metadata={"Date": None})
    print("wrote results/transient.svg")


if __name__ == "__main__":
    steady_plot()
    fields_plot()
    transient_plot()
