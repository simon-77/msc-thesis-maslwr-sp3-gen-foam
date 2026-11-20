#!/usr/bin/env python3
"""Liquid water for GeN-Foam: density, heat capacity, viscosity and thermal conductivity as
polynomials in the temperature (degree 7), fitted to IAPWS-IF97 at 8.718 MPa, the pressure of
the test (viscosity: IAPWS R12-08; thermal conductivity: IAPWS R15-11, with the critical
enhancement). Range 420 K to 2 K below saturation.

  python3 model/make_water.py        writes model/water (needs iapws and numpy)
"""
import pathlib
from types import SimpleNamespace

import numpy as np
from iapws._iapws import _ThCond, _Viscosity
from iapws.iapws97 import _Region1, _TSat_P

P = 8.718                                   # MPa
T = np.linspace(420.0, _TSat_P(P) - 2.0, 1524)


def props(t):
    r = _Region1(t, P)
    rho = 1.0 / r["v"]
    mu = _Viscosity(rho, t)
    fase = SimpleNamespace(drhodP_T=rho * r["kt"], cp=r["cp"], cp_cv=r["cp"] / r["cv"], mu=mu)
    return rho, r["cp"] * 1e3, mu, _ThCond(rho, t, fase)   # with fase: critical enhancement


rows = np.array([props(t) for t in T])
text = ("// Liquid water, IAPWS-IF97 at 8.718 MPa: polynomials in T [K], sum of c_i T^i, valid from\n"
        f"// {T[0]:.0f} to {T[-1]:.0f} K. Written by make_water.py.\n")
for name, y in zip(("rho", "Cp", "mu", "kappa"), rows.T):
    c = np.polynomial.Polynomial.fit(T, y, 7).convert().coef
    err = np.abs(np.polynomial.polynomial.polyval(T, c) / y - 1).max()
    text += f"// {name}: largest fit error {err:.1e} (relative)\n{name}Coeffs\n(\n"
    text += "".join(f"    {x:.16e}\n" for x in c) + ");\n"
(pathlib.Path(__file__).parent / "water").write_text(text)
