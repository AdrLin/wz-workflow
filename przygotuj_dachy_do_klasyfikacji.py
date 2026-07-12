#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
przygotuj_dachy_do_klasyfikacji.py  —  WERSJA POD NOWY MODEL CNN
================================================================
Rasteryzuje budynki DOKŁADNIE tak, jak przy treningu nowego modelu
(96x96, turbo RGB, binning max-Z + dofill KDTree, podłoga zakresu 0.6 m),
zapisuje PNG-i do <projekt>/prediction_data/ i uruchamia headless_classifier.py
(nowy model) w tle.

Architektura wtyczki bez zmian: ten skrypt = preparator + launcher,
headless_classifier.py = predyktor, roof_classification.py = konsument CSV.
Kontrakt wyjścia (building_predictions.csv) pozostaje identyczny.

Uruchamiany przez wtyczkę przez exec() WEWNĄTRZ QGIS (jak dotąd).
Wymaga w środowisku QGIS: numpy, pandas, scipy, matplotlib, pillow (są w geoworkspace).
"""
import os
import sys
import json
import threading
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
from scipy.spatial import cKDTree
from PIL import Image
from qgis.core import QgsProject

project_path = QgsProject.instance().fileName()
project_directory = Path(project_path).parent
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# KONFIGURACJA
# ============================================================
WARSTWA  = "Classification_6_with_IDs"     # warstwa punktowa z X, Y, Z, ID_BUDYNKU
HEADLESS = "headless_classifier.py"        # predyktor uruchamiany w tle

# Interpreter Pythona z TensorFlow do uruchomienia klasyfikatora.
# Domyślnie ten sam, pod którym chodzi QGIS (sys.executable).
# Jeśli TF jest w INNYM środowisku (np. ml-cnn), wpisz tu pełną ścieżkę do jego pythona, np.:
#   PYTHON_EXE = "/home/adrian/miniconda3/envs/ml-cnn/bin/python"
PYTHON_EXE = sys.executable

# Parametry rasteryzacji — MUSZĄ być identyczne jak przy budowie datasetu treningowego!
GRID, PAD = 96, 4
MIN_RANGE_M, FILL_RADIUS = 0.6, 2.2
DATA_FLOOR, BG_VALUE = 0.12, 0.0
CMAP = "turbo"
MIN_PKT = 4                                # budynki z mniejszą liczbą punktów pomijamy
# ============================================================


def build_dsm(pts):
    """Rasteryzacja DSM per budynek — IDENTYCZNA jak przy treningu (binning max-Z)."""
    xy, z = pts[:, :2], pts[:, 2]
    xmin, xmax = xy[:, 0].min(), xy[:, 0].max()
    ymin, ymax = xy[:, 1].min(), xy[:, 1].max()
    w, h = xmax - xmin, ymax - ymin
    s = (GRID - 2 * PAD) / max(w, h, 1e-6)
    ox = (GRID - 2 * PAD - w * s) / 2.0
    oy = (GRID - 2 * PAD - h * s) / 2.0
    cols = np.clip((PAD + ox + (xy[:, 0] - xmin) * s).astype(int), 0, GRID - 1)
    rws  = np.clip((PAD + oy + (ymax - xy[:, 1]) * s).astype(int), 0, GRID - 1)

    R = np.full((GRID, GRID), np.nan)
    flat = rws * GRID + cols
    o = np.argsort(flat); flat, zz = flat[o], z[o]
    u, st = np.unique(flat, return_index=True)
    for k, c in enumerate(u):
        seg = zz[st[k]: st[k + 1] if k + 1 < len(st) else None]
        R.flat[c] = seg.max()
    m = ~np.isnan(R)
    occ = np.argwhere(m); tree = cKDTree(occ); emp = np.argwhere(~m)
    if len(emp):
        d, idx = tree.query(emp, k=1)
        for (er, ec), nn, ok in zip(emp, idx, d <= FILL_RADIUS):
            if ok:
                sr, sc = occ[nn]; R[er, ec] = R[sr, sc]
    m = ~np.isnan(R)
    out = np.full((GRID, GRID), BG_VALUE)
    zd = R[m]; rng = max(zd.max() - zd.min(), MIN_RANGE_M)
    out[m] = DATA_FLOOR + (1 - DATA_FLOOR) * np.clip((R[m] - zd.min()) / rng, 0, 1)
    return out


def to_turbo_rgb(norm):
    """Mapa [0,1] -> obraz turbo RGB uint8 [0,255] — identycznie jak PNG treningowy."""
    rgb = matplotlib.colormaps[CMAP](norm)[:, :, :3] * 255.0
    return rgb.astype(np.uint8)


def get_prediction_data_dir():
    """Katalog prediction_data w folderze projektu QGIS (ten sam, na który czeka roof_classification)."""
    d = project_directory / "prediction_data"
    d.mkdir(parents=True, exist_ok=True)
    print(f"📁 Katalog predykcji: {d}")
    return str(d)


def run_script_bg(script_path, args=None, python_exe=None):
    """Uruchamia skrypt w tle (subprocess w osobnym wątku)."""
    def run_in_thread():
        try:
            command = [python_exe or sys.executable, script_path]
            if args:
                command.extend(args)
            result = subprocess.run(command, capture_output=True, text=True,
                                    cwd=os.path.dirname(script_path))
            print(f"Klasyfikator zakończony, rc={result.returncode}")
            if result.stdout:
                print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
        except Exception as e:
            print(f"Błąd uruchamiania klasyfikatora: {e}")

    threading.Thread(target=run_in_thread).start()
    print(f"Klasyfikator wystartował w tle: {script_path}  (python: {python_exe or sys.executable})")


def run_classifier():
    """Odpala nowy headless_classifier.py z nowym modelem CNN."""
    run_script_bg(os.path.join(SCRIPTS_PATH, HEADLESS),
                  args=[project_path], python_exe=PYTHON_EXE)


# ============================================================
# WŁAŚCIWY PRZEBIEG (wykonywany przez exec() w QGIS)
# ============================================================

# 1) wczytaj punkty z warstwy
warstwa = QgsProject.instance().mapLayersByName(WARSTWA)
if not warstwa:
    raise ValueError(f"Nie znaleziono warstwy o nazwie: {WARSTWA}")
layer = warstwa[0]

nazwy_pol = [f.name() for f in layer.fields()]
dane = [feat.attributes() for feat in layer.getFeatures()]
df = pd.DataFrame(dane, columns=nazwy_pol)[["X", "Y", "Z", "ID_BUDYNKU"]]
df = df.dropna(subset=["X", "Y", "Z", "ID_BUDYNKU"])
df[["X", "Y", "Z"]] = df[["X", "Y", "Z"]].astype(float)   # gdyby pola przyszły jako tekst

OUTPUT_DIR = get_prediction_data_dir()

# 2) sprzątanie po poprzednim uruchomieniu — żeby wait_for_file() w roof_classification
#    nie złapał STAREGO building_predictions.csv ani starych rastrów innej działki
for f in os.listdir(OUTPUT_DIR):
    if f.lower().endswith(".png") or f == "building_predictions.csv":
        try:
            os.remove(os.path.join(OUTPUT_DIR, f))
        except OSError:
            pass

# 3) rasteryzacja per budynek -> turbo 96x96 PNG
print("Rasteryzacja dachów (96x96, turbo)...")
mapping = {}
ok = skipped = 0
for bid, g in df.groupby("ID_BUDYNKU"):
    pts = g[["X", "Y", "Z"]].to_numpy(float)
    if len(pts) < MIN_PKT:
        skipped += 1
        continue
    img = to_turbo_rgb(build_dsm(pts))                       # 96x96x3 uint8
    # konwencja nazwy IDENTYCZNA jak w starym pipeline (zgodność z join w roof_classification)
    safe_id = str(bid).replace("/", "_").replace(" ", "_")
    fname = os.path.join(OUTPUT_DIR, f"{safe_id}.png")
    Image.fromarray(img, mode="RGB").save(fname)
    mapping[str(bid)] = os.path.basename(fname)
    ok += 1

with open(os.path.join(OUTPUT_DIR, "building_file_mapping.json"), "w", encoding="utf-8") as f:
    json.dump(mapping, f, indent=2, ensure_ascii=False)

print(f"✓ Zrasteryzowano {ok} budynków (pominięto rzadkich: {skipped}) -> {OUTPUT_DIR}")

# 4) odpal klasyfikator (nowy model) w tle; roof_classification.py poczeka na CSV
run_classifier()
