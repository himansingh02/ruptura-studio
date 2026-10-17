"""
RUPTURA Studio -- a no-Python desktop GUI for the RUPTURA breakthrough simulator.

Tabs:
  Components       -- define the gas mixture + per-component isotherms (shared)
  Breakthrough     -- fixed-bed breakthrough simulation + plot + CSV export
  Mixture (IAST)   -- multicomponent isotherm / IAST prediction vs pressure
  Fit isotherm     -- fit any of the 14 models to pressure/loading data

Built on RUPTURA (Sharma, Vlugt, Dubbeldam et al., TU Delft / UvA / Shell).
Pure tkinter + matplotlib so it bundles into a single executable.
"""
import os, sys, csv, threading, queue, traceback
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

import core

PA_PER_BAR = 1e5
APP_TITLE = "RUPTURA Studio"


# --------------------------------------------------------------------------
# shared application state: the component list (used by Breakthrough & Mixture)
# --------------------------------------------------------------------------
class State:
    def __init__(self):
        self.components = [
            {"name": "CO2", "y": 0.10, "carrier": False,
             "isotherms": [["Langmuir", 2.0, 1e-5]], "mtc": 0.44, "disp": 0.0},
            {"name": "N2", "y": 0.90, "carrier": True,
             "isotherms": [], "mtc": 0.0, "disp": 0.0},
        ]


# --------------------------------------------------------------------------
# dialog to add / edit one component
# --------------------------------------------------------------------------
class ComponentDialog(tk.Toplevel):
    def __init__(self, master, comp=None):
        super().__init__(master)
        self.title("Component")
        self.resizable(False, False)
        self.result = None
        c = comp or {"name": "", "y": 0.0, "carrier": False,
                     "isotherms": [["Langmuir", 1.0, 1e-5]], "mtc": 0.0, "disp": 0.0}
        self.grab_set()

        frm = ttk.Frame(self, padding=12)
        frm.grid(sticky="nsew")
        ttk.Label(frm, text="Name").grid(row=0, column=0, sticky="w")
        self.e_name = ttk.Entry(frm, width=14); self.e_name.insert(0, c["name"])
        self.e_name.grid(row=0, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(frm, text="Mole fraction y").grid(row=1, column=0, sticky="w")
        self.e_y = ttk.Entry(frm, width=14); self.e_y.insert(0, repr(c["y"]))
        self.e_y.grid(row=1, column=1, sticky="w", padx=4, pady=3)
        self.v_carrier = tk.BooleanVar(value=c.get("carrier", False))
        ttk.Checkbutton(frm, text="Carrier (inert) gas", variable=self.v_carrier,
                        command=self._toggle).grid(row=2, column=0, columnspan=2, sticky="w", pady=3)

        self.iso_box = ttk.LabelFrame(frm, text="Isotherm", padding=8)
        self.iso_box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(self.iso_box, text="Model").grid(row=0, column=0, sticky="w")
        self.v_model = tk.StringVar()
        models = list(core.ISOTHERM_MODELS.keys())
        has_iso = bool(c.get("isotherms"))
        self.v_model.set(c["isotherms"][0][0] if has_iso else "Langmuir")
        self.cb_model = ttk.Combobox(self.iso_box, textvariable=self.v_model,
                                     values=models, state="readonly", width=18)
        self.cb_model.grid(row=0, column=1, sticky="w", padx=4)
        self.cb_model.bind("<<ComboboxSelected>>", lambda e: self._rebuild_params())
        self.param_frame = ttk.Frame(self.iso_box)
        self.param_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._init_params = c["isotherms"][0][1:] if has_iso else None
        self._rebuild_params()

        ttk.Label(frm, text="LDF k (1/s)").grid(row=4, column=0, sticky="w")
        self.e_mtc = ttk.Entry(frm, width=14); self.e_mtc.insert(0, repr(c.get("mtc", 0.0)))
        self.e_mtc.grid(row=4, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(frm, text="Axial disp. (m²/s)").grid(row=5, column=0, sticky="w")
        self.e_disp = ttk.Entry(frm, width=14); self.e_disp.insert(0, repr(c.get("disp", 0.0)))
        self.e_disp.grid(row=5, column=1, sticky="w", padx=4, pady=3)

        btns = ttk.Frame(frm); btns.grid(row=6, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._ok).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).grid(row=0, column=1, padx=4)
        self._toggle()

    def _toggle(self):
        state = "disabled" if self.v_carrier.get() else "normal"
        for w in (self.cb_model,):
            w.configure(state="disabled" if self.v_carrier.get() else "readonly")
        for child in self.param_frame.winfo_children():
            child.configure(state=state)

    def _rebuild_params(self):
        for w in self.param_frame.winfo_children():
            w.destroy()
        labels = core.ISOTHERM_MODELS[self.v_model.get()]
        self.param_entries = []
        defaults = {"q_sat": 1.0, "b": 1e-5, "nu": 1.0, "a": 1e-5, "c": 1.0,
                    "eta": 1.0, "sigma": 1.0}
        for i, lab in enumerate(labels):
            ttk.Label(self.param_frame, text=lab).grid(row=i, column=0, sticky="w")
            e = ttk.Entry(self.param_frame, width=14)
            val = (self._init_params[i] if self._init_params and i < len(self._init_params)
                   else defaults.get(lab, 1.0))
            e.insert(0, repr(val))
            e.grid(row=i, column=1, sticky="w", padx=4, pady=2)
            self.param_entries.append(e)
        self._init_params = None

    def _ok(self):
        try:
            name = self.e_name.get().strip()
            y = float(self.e_y.get())
            carrier = self.v_carrier.get()
            if carrier:
                isos = []
            else:
                model = self.v_model.get()
                isos = [[model] + [float(e.get()) for e in self.param_entries]]
            self.result = {"name": name, "y": y, "carrier": carrier,
                           "isotherms": isos, "mtc": float(self.e_mtc.get()),
                           "disp": float(self.e_disp.get())}
            self.destroy()
        except ValueError as ex:
            messagebox.showerror("Invalid value", str(ex), parent=self)


# --------------------------------------------------------------------------
# components panel (one shared instance, embedded in the Components tab)
# --------------------------------------------------------------------------
class ComponentsPanel(ttk.Frame):
    def __init__(self, master, state):
        super().__init__(master, padding=10)
        self.state = state
        ttk.Label(self, text="Gas mixture — define each component and its isotherm. "
                             "Exactly one component should be the carrier gas.",
                  wraplength=560).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        cols = ("name", "y", "carrier", "isotherm", "k")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=8)
        for cid, txt, w in (("name", "Name", 80), ("y", "y", 80),
                            ("carrier", "Carrier", 70), ("isotherm", "Isotherm", 240),
                            ("k", "k (1/s)", 80)):
            self.tree.heading(cid, text=txt); self.tree.column(cid, width=w, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda e: self.edit())
        bar = ttk.Frame(self); bar.grid(row=1, column=1, sticky="n", padx=8)
        ttk.Button(bar, text="Add", command=self.add).grid(row=0, column=0, pady=2, sticky="ew")
        ttk.Button(bar, text="Edit", command=self.edit).grid(row=1, column=0, pady=2, sticky="ew")
        ttk.Button(bar, text="Remove", command=self.remove).grid(row=2, column=0, pady=2, sticky="ew")
        self.columnconfigure(0, weight=1); self.rowconfigure(1, weight=1)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for c in self.state.components:
            iso = "— (carrier)" if c.get("carrier") else (
                ", ".join("%s(%s)" % (i[0], ", ".join("%g" % v for v in i[1:]))
                          for i in c["isotherms"]) or "—")
            self.tree.insert("", "end", values=(c["name"], "%g" % c["y"],
                             "yes" if c.get("carrier") else "", iso, "%g" % c.get("mtc", 0)))

    def add(self):
        d = ComponentDialog(self); self.wait_window(d)
        if d.result: self.state.components.append(d.result); self.refresh()

    def edit(self):
        idx = self._sel()
        if idx is None: return
        d = ComponentDialog(self, self.state.components[idx]); self.wait_window(d)
        if d.result: self.state.components[idx] = d.result; self.refresh()

    def remove(self):
        idx = self._sel()
        if idx is not None:
            del self.state.components[idx]; self.refresh()

    def _sel(self):
        s = self.tree.selection()
        if not s:
            messagebox.showinfo(APP_TITLE, "Select a component first."); return None
        return self.tree.index(s[0])


# --------------------------------------------------------------------------
# a reusable plot area with a matplotlib canvas + toolbar + export
# --------------------------------------------------------------------------
class PlotArea(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.fig = Figure(figsize=(6.2, 4.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(self.canvas, self)
        self._export = None

    def set_export(self, header, rows):
        self._export = (header, rows)

    def export_csv(self):
        if not self._export:
            messagebox.showinfo(APP_TITLE, "Run a simulation first."); return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path: return
        header, rows = self._export
        with open(path, "w", newline="") as f:
            w = csv.writer(f); w.writerow(header); w.writerows(rows)
        messagebox.showinfo(APP_TITLE, "Saved %d rows to\n%s" % (len(rows), path))


def labeled(master, text, default, width=12, row=0, col=0):
    ttk.Label(master, text=text).grid(row=row, column=col, sticky="w", padx=4, pady=3)
    e = ttk.Entry(master, width=width); e.insert(0, str(default))
    e.grid(row=row, column=col + 1, sticky="w", padx=4, pady=3)
    return e


# --------------------------------------------------------------------------
# Breakthrough tab
# --------------------------------------------------------------------------
class BreakthroughTab(ttk.Frame):
    def __init__(self, master, state, app):
        super().__init__(master, padding=10)
        self.state = state; self.app = app
        form = ttk.LabelFrame(self, text="Column & operating conditions", padding=8)
        form.grid(row=0, column=0, sticky="nw")
        self.e_T = labeled(form, "Temperature (K)", 298.15, row=0, col=0)
        self.e_P = labeled(form, "Total pressure (bar)", 1.01325, row=1, col=0)
        self.e_eps = labeled(form, "Bed voidage ε", 0.5, row=2, col=0)
        self.e_rhop = labeled(form, "Particle density (kg/m³)", 1000.0, row=3, col=0)
        self.e_v = labeled(form, "Interstitial velocity (m/s)", 0.02, row=4, col=0)
        self.e_L = labeled(form, "Column length (m)", 0.02, row=5, col=0)
        self.e_ngrid = labeled(form, "Grid points", 100, row=0, col=2)
        self.e_dt = labeled(form, "Time step (s)", 0.0005, row=1, col=2)
        self.e_write = labeled(form, "Store every N steps", 100, row=2, col=2)
        self.e_dpdz = labeled(form, "Pressure gradient (Pa/m)", 0.0, row=3, col=2)
        self.e_pulse = labeled(form, "Pulse time (s, blank=off)", "", row=4, col=2)
        self.v_iast = tk.StringVar(value="IAST")
        ttk.Label(form, text="Mixture method").grid(row=5, column=2, sticky="w", padx=4)
        ttk.Combobox(form, textvariable=self.v_iast, values=["IAST", "SIAST", "EI", "SEI"],
                     state="readonly", width=10).grid(row=5, column=3, sticky="w")

        bar = ttk.Frame(self); bar.grid(row=1, column=0, sticky="w", pady=8)
        self.btn = ttk.Button(bar, text="Run breakthrough", command=self.run)
        self.btn.grid(row=0, column=0)
        ttk.Button(bar, text="Export CSV", command=lambda: self.plot.export_csv()).grid(row=0, column=1, padx=6)
        self.status = ttk.Label(bar, text=""); self.status.grid(row=0, column=2, padx=10)

        self.plot = PlotArea(self); self.plot.grid(row=2, column=0, sticky="nsew")
        self.rowconfigure(2, weight=1); self.columnconfigure(0, weight=1)

    def run(self):
        try:
            s = dict(T=float(self.e_T.get()), P=float(self.e_P.get()) * PA_PER_BAR,
                     eps=float(self.e_eps.get()), rho_p=float(self.e_rhop.get()),
                     v=float(self.e_v.get()), L=float(self.e_L.get()),
                     ngrid=int(float(self.e_ngrid.get())), dt=float(self.e_dt.get()),
                     write_every=int(float(self.e_write.get())),
                     dpdz=float(self.e_dpdz.get()), iast=self.v_iast.get())
            pt = self.e_pulse.get().strip()
            if pt: s["pulse"] = float(pt)
        except ValueError as ex:
            messagebox.showerror("Invalid value", str(ex)); return
        comps = [dict(c) for c in self.state.components]
        self.btn.configure(state="disabled"); self.status.configure(text="running…")
        self.app.run_async(lambda: core.run_breakthrough(comps, s), self._done)

    def _done(self, ok, res):
        self.btn.configure(state="normal"); self.status.configure(text="" if ok else "error")
        if not ok:
            messagebox.showerror("RUPTURA error", res); return
        t = res["t_min"]; ax = self.plot.ax; ax.clear()
        rows = [["time_min"] ]  # header filled below
        header = ["time_min"]; cols = [t]
        for sdat in res["series"]:
            if sdat["carrier"]:
                continue
            ax.plot(t, sdat["cc"], label=sdat["name"])
            header.append("C/C0_" + sdat["name"]); cols.append(sdat["cc"])
        ax.set_xlabel("Time (min)"); ax.set_ylabel("C/C₀"); ax.set_ylim(-0.02, 1.05)
        ax.grid(alpha=0.3); ax.legend(); ax.set_title("Breakthrough")
        self.plot.fig.tight_layout(); self.plot.canvas.draw()
        self.plot.set_export(header, list(zip(*cols)))


# --------------------------------------------------------------------------
# Mixture / IAST tab
# --------------------------------------------------------------------------
class MixtureTab(ttk.Frame):
    def __init__(self, master, state, app):
        super().__init__(master, padding=10)
        self.state = state; self.app = app
        form = ttk.LabelFrame(self, text="Isotherm / IAST prediction", padding=8)
        form.grid(row=0, column=0, sticky="nw")
        self.e_T = labeled(form, "Temperature (K)", 298.15, row=0, col=0)
        self.e_ps = labeled(form, "Pressure start (Pa)", 1.0, row=1, col=0)
        self.e_pe = labeled(form, "Pressure end (Pa)", 1e6, row=2, col=0)
        self.e_np = labeled(form, "Points", 100, row=0, col=2)
        self.v_scale = tk.StringVar(value="log")
        ttk.Label(form, text="Scale").grid(row=1, column=2, sticky="w", padx=4)
        ttk.Combobox(form, textvariable=self.v_scale, values=["log", "linear"],
                     state="readonly", width=10).grid(row=1, column=3, sticky="w")
        self.v_iast = tk.StringVar(value="IAST")
        ttk.Label(form, text="Method").grid(row=2, column=2, sticky="w", padx=4)
        ttk.Combobox(form, textvariable=self.v_iast, values=["IAST", "SIAST", "EI", "SEI"],
                     state="readonly", width=10).grid(row=2, column=3, sticky="w")
        bar = ttk.Frame(self); bar.grid(row=1, column=0, sticky="w", pady=8)
        self.btn = ttk.Button(bar, text="Run prediction", command=self.run); self.btn.grid(row=0, column=0)
        self.status = ttk.Label(bar, text=""); self.status.grid(row=0, column=1, padx=10)
        self.plot = PlotArea(self); self.plot.grid(row=2, column=0, sticky="nsew")
        self.rowconfigure(2, weight=1); self.columnconfigure(0, weight=1)

    def run(self):
        try:
            s = dict(T=float(self.e_T.get()), p_start=float(self.e_ps.get()),
                     p_end=float(self.e_pe.get()), npoints=int(float(self.e_np.get())),
                     scale=self.v_scale.get(), iast=self.v_iast.get())
        except ValueError as ex:
            messagebox.showerror("Invalid value", str(ex)); return
        comps = [dict(c) for c in self.state.components]
        self.btn.configure(state="disabled"); self.status.configure(text="running…")
        self.app.run_async(lambda: core.run_mixture(comps, s), self._done)

    def _done(self, ok, res):
        self.btn.configure(state="normal"); self.status.configure(text="" if ok else "error")
        if not ok:
            messagebox.showerror("RUPTURA error", res); return
        raw = res["raw"]; ax = self.plot.ax; ax.clear()
        # raw columns: [P, y_i..., loading_i...] — plot total/first loadings vs P
        try:
            P = raw[:, 0]
            ncomp = len([c for c in self.state.components])
            for i in range(ncomp):
                ax.plot(P, raw[:, 1 + ncomp + i], label=self.state.components[i]["name"])
            ax.set_xscale("log" if self.v_scale.get() == "log" else "linear")
        except Exception:
            ax.plot(raw.reshape(raw.shape[0], -1)[:, 0])
        ax.set_xlabel("Pressure (Pa)"); ax.set_ylabel("Loading (mol/kg)")
        ax.grid(alpha=0.3); ax.legend(); ax.set_title("IAST prediction")
        self.plot.fig.tight_layout(); self.plot.canvas.draw()


# --------------------------------------------------------------------------
# Fitting tab
# --------------------------------------------------------------------------
class FitTab(ttk.Frame):
    def __init__(self, master, state, app):
        super().__init__(master, padding=10)
        self.app = app; self.data = None
        form = ttk.Frame(self); form.grid(row=0, column=0, sticky="w")
        ttk.Button(form, text="Load data (CSV: pressure_Pa, loading_mol/kg)",
                   command=self.load).grid(row=0, column=0, sticky="w", pady=3)
        self.lbl_data = ttk.Label(form, text="no data"); self.lbl_data.grid(row=0, column=1, padx=8)
        ttk.Label(form, text="Model").grid(row=1, column=0, sticky="w")
        self.v_model = tk.StringVar(value="Langmuir")
        ttk.Combobox(form, textvariable=self.v_model, values=list(core.ISOTHERM_MODELS.keys()),
                     state="readonly", width=20).grid(row=1, column=1, sticky="w")
        self.e_name = labeled(form, "Component name", "CO2", row=2, col=0)
        self.btn = ttk.Button(form, text="Fit", command=self.run); self.btn.grid(row=3, column=0, pady=6, sticky="w")
        self.out = ttk.Label(form, text=""); self.out.grid(row=3, column=1, sticky="w")
        self.plot = PlotArea(self); self.plot.grid(row=1, column=0, sticky="nsew")
        self.rowconfigure(1, weight=1); self.columnconfigure(0, weight=1)

    def load(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if not path: return
        try:
            d = np.genfromtxt(path, delimiter=",")
            d = d[~np.isnan(d).any(axis=1)]
            if d.ndim != 2 or d.shape[1] < 2:
                raise ValueError("need two columns: pressure, loading")
            self.data = d[:, :2]
            self.lbl_data.configure(text="%d points" % len(self.data))
            ax = self.plot.ax; ax.clear(); ax.plot(self.data[:, 0], self.data[:, 1], "o")
            ax.set_xlabel("Pressure (Pa)"); ax.set_ylabel("Loading (mol/kg)")
            ax.grid(alpha=0.3); self.plot.canvas.draw()
        except Exception as ex:
            messagebox.showerror("Load error", str(ex))

    def run(self):
        if self.data is None:
            messagebox.showinfo(APP_TITLE, "Load data first."); return
        model = self.v_model.get(); name = self.e_name.get().strip() or "gas"
        data = self.data.copy()
        self.btn.configure(state="disabled")
        self.app.run_async(lambda: core.run_fitting(name, 1.0, model, data), self._done)

    def _done(self, ok, res):
        self.btn.configure(state="normal")
        if not ok:
            messagebox.showerror("Fit error", res); return
        labels = core.ISOTHERM_MODELS[self.v_model.get()]
        params = res["params"]
        txt = "  ".join("%s=%.4g" % (l, p) for l, p in zip(labels, np.ravel(params)))
        self.out.configure(text=txt)


# --------------------------------------------------------------------------
# main application
# --------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x640")
        self.state_obj = State()
        self.q = queue.Queue()
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.comp_panel = ComponentsPanel(nb, self.state_obj)
        self.bt_tab = BreakthroughTab(nb, self.state_obj, self)
        self.mix_tab = MixtureTab(nb, self.state_obj, self)
        self.fit_tab = FitTab(nb, self.state_obj, self)
        nb.add(self.comp_panel, text="Components")
        nb.add(self.bt_tab, text="Breakthrough")
        nb.add(self.mix_tab, text="Mixture (IAST)")
        nb.add(self.fit_tab, text="Fit isotherm")
        self.after(80, self._poll)

    def run_async(self, fn, cb):
        def worker():
            try:
                self.q.put((cb, True, fn()))
            except Exception:
                self.q.put((cb, False, traceback.format_exc()))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                cb, ok, res = self.q.get_nowait()
                cb(ok, res)
        except queue.Empty:
            pass
        self.after(80, self._poll)


def _selftest():
    """Headless check that RUPTURA computes inside this (possibly frozen) build."""
    comps = [{"name": "CO2", "y": 0.10, "isotherms": [["Langmuir", 2.0, 1e-5]], "mtc": 0.44},
             {"name": "N2", "y": 0.90, "carrier": True}]
    s = dict(T=298.15, P=101325.0, eps=0.5, rho_p=1000.0, v=0.02, L=0.02,
             dt=0.002, ngrid=100, write_every=100)
    r = core.run_breakthrough(comps, s)
    t, cc = r["t_min"], r["series"][0]["cc"]
    i = int(np.argmin(np.abs(cc - 0.5)))
    print("SELFTEST OK: RUPTURA ran inside this build; t50 = %.3f min (expect ~0.74)" % t[i])


def main():
    if "--selftest" in sys.argv:
        _selftest(); return
    App().mainloop()


if __name__ == "__main__":
    main()
