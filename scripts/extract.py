#!/usr/bin/env python3
"""Run output -> results CSVs.

  python3 scripts/extract.py 1d|2d     reads runs/<case>/steady/step*/ and runs/<case>/transient/ (if present)

Writes results/<case>/steady.csv (end state of each step) and results/<case>/transient.csv (every
written time, 10 s apart, and the end of each power plateau).
For the 2D case also results/2d/fields.csv: temperature and velocity in every cell at the end of
step 5.
Checks; the results are written only if all pass:
  - steady runs: the run reached its end time and the flow changed by less than 0.01 % over
    the last 300 s;
  - transient: one finished plateau per step;
  - energy balance: the SG takes the core power to 0.1 % at each steady end state.
Core inlet and outlet temperature: the lowest cells of the downcomer and of the riser.
Standard library only.
"""
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
STEADY_TOL = 1e-4    # 0.01 % in 300 s
BALANCE_TOL = 1e-3   # 0.1 %
COLS = ["Q_W", "mdot_kg_s", "T_core_in_K", "T_core_out_K", "dT_core_K", "Q_sink_W", "T_sec_K"]


def fmt(x):
    return f"{x:.10g}"


def numbers(path, name):
    """A list of numbers from an OpenFOAM file: 'name nonuniform List<scalar> N ( v v v )'."""
    m = re.search(name + r"\s+nonuniform\s+List<scalar>\s*\d+\s*\(([^)]*)\)", path.read_text())
    return [float(v) for v in m.group(1).split()]


def vectors(path, name):
    """A list of (x, y, z) from an OpenFOAM file: 'name ... N ( (x y z) (x y z) )'."""
    m = re.search(name + r"\s+nonuniform\s+List<vector>\s*\d+\s*\((.*?)\)\s*;", path.read_text(), re.S)
    return [tuple(float(v) for v in t.split()) for t in re.findall(r"\(([^()]*)\)", m.group(1))]


def setting(path, name):
    """A value 'name value;' or 'name #eval{ numbers };' from a dictionary file."""
    text = re.sub(r"//.*", "", path.read_text())
    value = re.search(rf"^\s*{name}\s+(?:#eval{{)?([-+*/0-9.eE ]+)}}?;", text, re.M).group(1)
    return float(eval(value))


def zone(case, name):
    """Cell numbers of a zone, in mesh order."""
    text = (case / "constant/fluid/polyMesh/cellZones").read_text()
    m = re.search(name + r"\s*\{[^}]*?cellLabels\s+List<label>\s*\d+\s*\(([^)]*)\)", text)
    return [int(v) for v in m.group(1).split()]


def flow(case):
    """(time, mass flow) at every time step."""
    rows = []
    for f in sorted(case.glob("postProcessing/fluid/mdot/*/massFlow*.dat"),
                    key=lambda f: float(f.parent.name)):
        for line in f.read_text().splitlines():
            if line and not line.startswith("#"):
                t, m = line.split()[:2]
                rows.append((float(t), abs(float(m))))
    return rows


def at(rows, t):
    """Mass flow at time t (the time step that covers it)."""
    return next(m for time, m in rows if time >= t - 1e-9)


def mean(values, vol, cells):
    """Mean of a field over some cells, weighted with the cell volumes."""
    return sum(values[c] * vol[c] for c in cells) / sum(vol[c] for c in cells)


def lowest(case, name):
    """The lowest cells of a zone (one cell in 1D, one row of cells in 2D)."""
    z = numbers(case / "0/fluid/Cz", "internalField")
    cells = zone(case, name)
    z_min = min(z[c] for c in cells)
    return [c for c in cells if z[c] < z_min + 1e-6]


def state(case, time_dir, mdot, power, t_sec):
    """The result columns from the temperature field of one written time."""
    par = case / "constant/parameters"
    temp = numbers(time_dir / "fluid/T", "internalField")
    vol = numbers(case / "0/fluid/V", "internalField")
    t_in = mean(temp, vol, lowest(case, "dc_low"))
    t_out = mean(temp, vol, lowest(case, "riser_low"))
    # heat to the tubes: U * tube area * (T - T_sec), averaged over the volume of the SG zone
    mean_dt = mean(temp, vol, zone(case, "sg")) - t_sec
    q_sink = setting(par, "U_sg") * setting(par, "A_tubes") * mean_dt
    return dict(zip(COLS, map(fmt, [power, mdot, t_in, t_out, t_out - t_in, q_sink, t_sec])))


def times(case):
    return sorted((d for d in case.iterdir() if re.fullmatch(r"[0-9.e+-]+", d.name) and d.name != "0"),
                  key=lambda d: float(d.name))


def steady(name, problems):
    out = []
    with open(ROOT / "model/steps.csv") as fh:
        steps = [r["step"] for r in csv.DictReader(fh)]
    for step in steps:
        case = ROOT / f"runs/{name}/steady/step{step}"
        if not case.exists() or not times(case):
            problems.append(f"step {step}: no run in runs/{name}/steady/ (run ./run.sh {name} steady)")
            continue
        rows = flow(case)
        end, mdot = rows[-1]
        if end < setting(case / "system/controlDict", "endTime") - 1e-6:
            problems.append(f"step {step}: run not finished (ends at {end:.0f} s)")
            continue
        drift = abs(mdot - at(rows, end - 300)) / mdot
        if drift > STEADY_TOL:
            problems.append(f"step {step}: not steady, flow changed by {100 * drift:.3f} % in the last 300 s")
        power, t_sec = (setting(case / "constant/step", k) for k in ("power", "T_sec"))
        r = state(case, times(case)[-1], mdot, power, t_sec)
        if abs(float(r["Q_sink_W"]) - float(r["Q_W"])) > BALANCE_TOL * float(r["Q_W"]):
            problems.append(f"step {step}: energy balance off by {float(r['Q_sink_W']) - float(r['Q_W']):.1f} W")
        out.append(dict(step=step, t_end_s=fmt(end), **r))
    return out


def transient(name, problems):
    """Every written time (10 s), and the end of each power plateau (run.sh writes plateaus.csv)."""
    case = ROOT / f"runs/{name}/transient"
    if not case.exists():
        print(f"no transient run in runs/{name}/transient/: results/{name}/transient.csv not updated")
        return []
    if not (case / "plateaus.csv").exists():
        problems.append(f"transient: no runs/{name}/transient/plateaus.csv (run not finished)")
        return []
    rows = flow(case)
    with open(case / "plateaus.csv") as fh:
        plateaus = [{k: float(v) for k, v in r.items()} for r in csv.DictReader(fh)]
    out = []
    for d in times(case):
        t = float(d.name)
        p = next((p for p in plateaus if t <= p["end_s"] + 1e-6), None)
        if p is None:
            problems.append(f"transient: time {d.name} s lies after the last plateau")
            return []
        r = state(case, d, at(rows, t), p["power_W"], p["T_sec_K"])
        out.append(dict(kind="series", step="", time_s=fmt(t), **r))
    ends = [dict(r, kind="plateau_end", step=f"{p['step']:.0f}") for p in plateaus
            for r in out if abs(float(r["time_s"]) - p["end_s"]) < 1e-6]
    with open(ROOT / "model/steps.csv") as fh:
        n_steps = len(list(csv.DictReader(fh)))
    if len(plateaus) != n_steps or len(ends) != n_steps:
        problems.append(f"transient: {len(ends)} of {n_steps} plateau ends written (run not finished)")
    return ends + out


def fields(name, step):
    """Temperature and velocity in every cell at the end of a steady step (2D case)."""
    case = ROOT / f"runs/{name}/steady/step{step}"
    last = times(case)[-1]
    x, z = (numbers(case / f"0/fluid/{c}", "internalField") for c in ("Cx", "Cz"))
    temp = numbers(last / "fluid/T", "internalField")
    vel = vectors(last / "fluid/U", "internalField")
    return [dict(r_m=fmt(a), z_m=fmt(b), T_K=fmt(t), U_r_m_s=fmt(u[0]), U_z_m_s=fmt(u[2]))
            for a, b, t, u in zip(x, z, temp, vel)]


def write(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path.relative_to(ROOT)}")


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not (ROOT / "model" / name / "system").is_dir():
        sys.exit("usage: python3 scripts/extract.py 1d|2d")
    problems = []
    steady_rows, transient_rows = steady(name, problems), transient(name, problems)
    for p in problems:
        print("CHECK:", p)
    if problems:
        sys.exit(f"{len(problems)} check(s) failed, nothing written")
    write(ROOT / f"results/{name}/steady.csv", steady_rows)
    if name == "2d":
        write(ROOT / "results/2d/fields.csv", fields(name, 5))
    write(ROOT / f"results/{name}/transient.csv", transient_rows)


if __name__ == "__main__":
    main()
