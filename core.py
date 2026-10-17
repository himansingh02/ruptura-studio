"""
core.py -- thin, GUI-independent wrapper around the RUPTURA package.

All RUPTURA calls live here so the logic can be tested without a display.
Units are RUPTURA's native SI:  loading mol/kg, pressure Pa, b in 1/Pa,
velocity m/s (interstitial), length m, particle density kg/m3, temperature K.

RUPTURA: Sharma, Ran, Balestra, Baur, ... Vlugt, Dubbeldam (TU Delft / UvA / Shell).
"""
import numpy as np
import ruptura

# 14 isotherm models and their parameter labels (from RUPTURA itself)
ISOTHERM_MODELS = {k: v["labels"] for k, v in ruptura.isothermMeta.items()}

# ---- Components ---------------------------------------------------------

def build_components(comps):
    """comps: list of dicts, each:
        {name, y (mol fraction), carrier (bool),
         isotherms: list of [model_name, p1, p2, ...],
         mtc (1/s), disp (m2/s)}
    Returns a ruptura.Components instance."""
    C = ruptura.Components()
    for c in comps:
        C.addComponent(
            c["name"], float(c["y"]),
            isotherms=[[iso[0]] + [float(x) for x in iso[1:]] for iso in c.get("isotherms", [])],
            MassTransferCoefficient=float(c.get("mtc", 0.0)),
            AxialDispersionCoefficient=float(c.get("disp", 0.0)),
            CarrierGas=bool(c.get("carrier", False)),
        )
    return C

# ---- Breakthrough ------------------------------------------------------
# Output array shape: (n_snapshots, n_grid+1, 17)
#   col 1 = time [min], col 2 = position [m], col 3 = interstitial velocity,
#   col 4 = total pressure [Pa]; then 6 columns per component, the component's
#   partial pressure is column (7 + 6*i), its equilibrium loading col (6 + 6*i).

def run_breakthrough(comps, settings):
    C = build_components(comps)
    bt = ruptura.Breakthrough(
        C,
        DisplayName=settings.get("name", "column"),
        Temperature=float(settings["T"]),
        NumberOfTimeSteps=settings.get("nsteps", "auto"),
        NumberOfGridPoints=int(settings.get("ngrid", 100)),
        PrintEvery=10**9,
        WriteEvery=int(settings.get("write_every", 100)),
        TotalPressure=float(settings["P"]),
        ColumnVoidFraction=float(settings["eps"]),
        PressureGradient=float(settings.get("dpdz", 0.0)),
        ParticleDensity=float(settings["rho_p"]),
        ColumnEntranceVelocity=float(settings["v"]),   # interstitial, m/s
        ColumnLength=float(settings["L"]),
        TimeStep=float(settings.get("dt", 5e-4)),
        PulseTime=settings.get("pulse", None),
        MixturePredictionMethod=settings.get("iast", "IAST"),
    )
    out = np.array(bt.compute())
    t_min = out[:, 0, 1]
    P = float(settings["P"])
    series = []
    for i, c in enumerate(comps):
        y = float(c["y"])
        pp = out[:, -1, 7 + 6 * i]           # outlet partial pressure
        cc = pp / (y * P) if y > 0 else np.zeros_like(pp)
        series.append({"name": c["name"], "y": y, "cc": cc,
                       "carrier": bool(c.get("carrier", False))})
    return {"t_min": t_min, "series": series, "raw": out}

# ---- Mixture (IAST) prediction ----------------------------------------

def run_mixture(comps, settings):
    C = build_components(comps)
    mp = ruptura.MixturePrediction(
        C,
        DisplayName=settings.get("name", "mixture"),
        Temperature=float(settings["T"]),
        PressureStart=float(settings["p_start"]),
        PressureEnd=float(settings["p_end"]),
        NumberOfPressurePoints=int(settings.get("npoints", 100)),
        PressureScale=settings.get("scale", "log"),
        MixturePredictionMethod=settings.get("iast", "IAST"),
        IASTMethod=settings.get("iast_method", "FastIAST"),
    )
    out = np.array(mp.compute())
    return {"raw": out}

# ---- Isotherm fitting --------------------------------------------------

def run_fitting(name, y, model, data_pq, scale="log"):
    """data_pq: Nx2 array of [pressure_Pa, loading_mol_per_kg]."""
    C = ruptura.Components()
    C.addComponent(name, float(y), isotherms=[[model] + [1.0] * len(ISOTHERM_MODELS[model])])
    fit = ruptura.Fitting(C, PressureScale=scale, DisplayName=name)
    data = np.asarray(data_pq, dtype=float)
    try:
        params = fit.compute(data)
    except TypeError:
        params = fit.compute()
    return {"params": np.array(params).tolist()}


if __name__ == "__main__":
    # self-test: reproduce the cross-validation case (should match Sorbent Lab)
    comps = [
        {"name": "CO2", "y": 0.10, "isotherms": [["Langmuir", 2.0, 1e-5]], "mtc": 0.44},
        {"name": "N2", "y": 0.90, "carrier": True},
    ]
    settings = dict(T=298.15, P=101325.0, eps=0.5, rho_p=1000.0, v=0.02,
                    L=0.02, dt=0.002, ngrid=100, write_every=100)
    r = run_breakthrough(comps, settings)
    t = r["t_min"]
    cc = r["series"][0]["cc"]
    i50 = int(np.argmin(np.abs(cc - 0.5)))
    print("self-test breakthrough: t50 = %.3f min  (expect ~0.74)" % t[i50])
    for tt in (0.6, 0.74, 0.9):
        j = int(np.argmin(np.abs(t - tt)))
        print("   t=%.2f min  C/C0=%.4f" % (t[j], cc[j]))
