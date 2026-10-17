# RUPTURA Studio

A no-Python desktop GUI for the **RUPTURA** fixed-bed breakthrough simulator
(Sharma, Ran, Balestra, Baur, Agarwal, Zuidema, Rigutto, Calero, Vlugt,
Dubbeldam — TU Delft / University of Amsterdam / Shell).

It wraps RUPTURA's three main capabilities in a point-and-click interface:

- **Components** — build a gas mixture; pick any of RUPTURA's 14 isotherm models
  per component (Langmuir, DSL via two sites, Toth, Sips, BET, Freundlich,
  Unilan, O'Brien–Myers, Quadratic, Temkin, …), with LDF rate and axial dispersion.
- **Breakthrough** — fixed-bed breakthrough simulation; plots C/C₀ vs time at the
  outlet and exports the curve to CSV.
- **Mixture (IAST)** — multicomponent isotherm / IAST prediction vs pressure.
- **Fit isotherm** — fit any model to pressure/loading data.

Units are RUPTURA's native SI (loading mol/kg, pressure Pa inside; the GUI takes
total pressure in bar, b in 1/Pa, velocity interstitial in m/s, length in m).

---

## Getting the Windows app (no Python needed)

**Option A — automatic cloud build (recommended).**
1. Put these files in a new GitHub repository (keep the folder layout, including
   `.github/workflows/build-windows.yml`).
2. Push to the `main` branch. The **Build Windows EXE** action runs automatically
   (or start it by hand from the repo's **Actions** tab → *Build Windows EXE* →
   *Run workflow*).
3. When it finishes (~3–5 min), open the run and download
   **RUPTURA-Studio-Windows** from the *Artifacts* section. Inside is
   `RUPTURA-Studio.exe` — **double-click to run**. Nothing else to install.

**Option B — build once on a Windows machine.**
```bat
pip install ruptura matplotlib numpy pyinstaller
pyinstaller --clean --noconfirm ruptura_studio.spec
```
The app appears at `dist\RUPTURA-Studio.exe`.

## Running from source (any OS with Python 3.10–3.12)
```bash
pip install ruptura matplotlib numpy
python app.py
```
On Linux you also need Tk: `sudo apt install python3-tk`.

---

## Files
| file | purpose |
|------|---------|
| `app.py` | the GUI |
| `core.py` | thin, testable wrapper around RUPTURA (all simulation calls) |
| `ruptura_studio.spec` | PyInstaller recipe → single executable |
| `.github/workflows/build-windows.yml` | cloud build of the Windows `.exe` |
| `requirements.txt` | dependencies |

## Note
This is an independent interface to RUPTURA; it does not modify RUPTURA.
Please cite the RUPTURA authors when you use results from it.
