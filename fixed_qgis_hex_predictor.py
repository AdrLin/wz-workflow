#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import processing
import os
import math
import warnings
warnings.filterwarnings('ignore')
from qgis.core import (QgsProject, QgsField, QgsVectorLayer, QgsFields, QgsPointXY, QgsFeature, QgsGeometry)
from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsVectorFileWriter, QgsCoordinateTransformContext

# Ciezkie biblioteki naukowe wymagane przez klasyfikator PBC.
# Jesli ktorejs brak (albo srodowisko ma niespojne numpy/scipy), zglaszamy
# czytelny komunikat zamiast surowego bledu importu w polowie przetwarzania.
try:
    import numpy as np
    import pandas as pd
    import joblib
except ImportError as _exc:
    raise ImportError(
        "Klasyfikacja PBC wymaga bibliotek: numpy, pandas, joblib (oraz "
        "scikit-learn i scipy dla samego modelu).\\n"
        "Zainstaluj je w srodowisku Pythona QGIS, np.:\\n"
        "    python3 -m pip install numpy pandas scipy scikit-learn joblib\\n\\n"
        f"Szczegoly: {_exc}"
    ) from _exc

# Wyłącz ostrzeżenia XCB
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.xcb.warning=false'
os.environ['QT_X11_NO_MITSHM'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '0'
os.environ['QT_SCREEN_SCALE_FACTORS'] = '1'

warnings.filterwarnings('ignore', category=UserWarning, module='PyQt5')

SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))
project = QgsProject.instance()
project_crs = project.crs()
project_path = QgsProject.instance().fileName()
project_directory = os.path.dirname(project_path)


# ── Nowy model Random Forest (bundle z joblib) ──
# Bundle to słownik zapisany przez pbc_train_rf.py:
#   {'model', 'feature_order', 'class_names', 'pbc_classes', 'hex_size'}
MODEL_PATH = os.path.join(SCRIPTS_PATH, "rf_pbc_ostrow.pkl")
HEX_SIZE = 0.36

# ⚠️ Promień sąsiedztwa dla cech geometrycznych — MUSI być identyczny jak w treningu!
# Maska cięcia jest o tyle buforowana, żeby heksagony przy granicy działki
# miały PEŁNE otoczenie (inaczej cecha liczyłaby się inaczej niż w treningu).
NEIGHBOR_RADIUS = 1.5
MIN_NEIGHBORS   = 8

# ⚠️ PRÓG DECYZYJNY PBC
# Heksagon jest uznany za PBC tylko gdy P(PBC) > PBC_THRESHOLD, gdzie
#   P(PBC) = suma prawdopodobieństw klas PBC {0,1,2,3,4,11,12}
#
# 0.50 → zachowanie symetryczne (jak argmax) — model nieobciążony
# 0.60 → model musi być pewniejszy, by uznać coś za PBC; wątpliwe idą
#        do nie-PBC → wskaźnik NIŻSZY
#
# KIERUNEK (wskaźnik liczony z działek SĄSIEDNICH = wymóg dla inwestora):
#   zawyżony PBC → ostrzejszy wymóg → inwestor może nie zbudować  ← unikamy
#   zaniżony PBC → łagodniejszy wymóg → inwestor dostaje zgodę    ← akceptowalne
# Podnoszenie progu przesuwa błąd w stronę zaniżania.
#
# Dobierz wartość skryptem pbc_threshold_sweep.py — pokaże, ile
# zawyżania kupujesz za ile zaniżania.
#
# UWAGA: to NIE to samo co kolumna `confidence` (max proba po 13 klasach).
# Heksagon może mieć confidence=0.35 (model waha się trawnik/ruderalna/pole),
# ale P(PBC)=0.85, bo wszystkie te klasy są PBC.
PBC_THRESHOLD = 0.65

# Klasy PBC (biologicznie czynne) — do sumowania prawdopodobieństwa
PBC_CLASSES = {0, 1, 2, 3, 4, 11, 12}

# Kolumny wejściowe potrzebne do policzenia cech (nazwy atrybutów w warstwie punktów)
INPUT_FEATURES = ['Red', 'Green', 'Blue', 'Z', 'Intensity', 'ReturnNumber', 'NumberOfReturns']

# 14 klas → PBC (0) / nie-PBC (1). PBC = biologicznie czynne.
# Zgodne z bundlem: PBC_CLASSES = {0,1,2,3,4,11,12}
MULTICLASS_TO_BINARY = {
    0: 0,   # Trawnik zadbany       → PBC
    1: 0,   # Roślinność ruderalna  → PBC
    2: 0,   # Pole uprawne          → PBC
    3: 0,   # Zaorane pole          → PBC
    4: 0,   # Droga gruntowa        → PBC
    5: 1,   # Asfalt                → nie-PBC
    6: 1,   # Beton                 → nie-PBC
    7: 1,   # Kostka czerwona       → nie-PBC
    8: 1,   # Kostka niebieska      → nie-PBC
    9: 1,   # Kort tenisowy         → nie-PBC
    10: 1,  # Beton cień            → nie-PBC
    11: 0,  # Trawa cień            → PBC
    12: 0,  # Gleba cień            → PBC
    13: 1,  # Boisko                → nie-PBC
}

CLASS_NAMES = {
    0: "Trawnik zadbany", 1: "Roślinność ruderalna", 2: "Pole uprawne",
    3: "Zaorane pole", 4: "Droga gruntowa", 5: "Asfalt", 6: "Beton",
    7: "Kostka czerwona", 8: "Kostka niebieska", 9: "Kort tenisowy",
    10: "Beton cień", 11: "Trawa cień", 12: "Gleba cień", 13: "Boisko",
}

# Kolejność cech — MUSI być identyczna jak w treningu (pbc_train_rf.py / v3).
FEATURE_ORDER = [
    'mean_chroma_r', 'std_chroma_r',
    'mean_chroma_g', 'std_chroma_g',
    'mean_chroma_b', 'std_chroma_b',
    'mean_gri', 'std_gri',
    'mean_gbi', 'std_gbi',
    'mean_rbi', 'std_rbi',
    'cv_R', 'cv_G', 'cv_B',
    'mean_brightness', 'std_brightness', 'cv_brightness',
    'mean_I', 'std_I', 'cv_I',
    'std_Z', 'mean_return_ratio',
    # cechy sąsiedztwa (v4) — dają modelowi GEOMETRIĘ, która rozdziela
    # gładki beton od chropowatej drogi gruntowej
    'nb_planarity', 'nb_std_Z', 'nb_std_I', 'nb_std_brightness', 'nb_I_contrast',
]


# === Model heksagonalny ===

def axial_to_cartesian(q, r, hex_size):
    """Flat-top: axial (q, r) → współrzędne kartezjańskie centroidu."""
    x = hex_size * 1.5 * q
    y = hex_size * (math.sqrt(3)/2 * q + math.sqrt(3) * r)
    return x, y

def hex_grid_coordinates(x, y, hex_size):
    q = (2/3 * x) / hex_size
    r = (-1/3 * x + math.sqrt(3)/3 * y) / hex_size
    q_round = round(q)
    r_round = round(r)
    s_round = round(-q - r)
    q_diff = abs(q_round - q)
    r_diff = abs(r_round - r)
    s_diff = abs(s_round - (-q - r))
    if q_diff > r_diff and q_diff > s_diff:
        q_round = -r_round - s_round
    elif r_diff > s_diff:
        r_round = -q_round - s_round
    return (q_round, r_round)


def create_hexagon_features(points_data):
    """
    Liczy 23 CECHY ODPORNE — IDENTYCZNIE jak w treningu (pbc_extract_features_v3).
    Chromatyczność, indeksy ratio, cv barw, jasność, surowa intensywność,
    std_Z, return ratio. Bez normalizacji per-kafel (spójne z modelem Ostrowa).
    """
    print("Grupowanie punktów w heksagony (wektoryzowane)...")

    # Współrzędne z GEOMETRII (geom_x/geom_y) — CRS geometrii, nie atrybutów X/Y
    if 'geom_x' in points_data.columns and 'geom_y' in points_data.columns:
        X = points_data['geom_x'].values
        Y = points_data['geom_y'].values
    else:
        X = points_data['X'].values
        Y = points_data['Y'].values

    h = HEX_SIZE
    eps = 1e-8

    # Przypisanie punktów do heksagonów (cube rounding)
    q_f = (2/3 * X) / h
    r_f = (-1/3 * X + math.sqrt(3)/3 * Y) / h
    q_r = np.round(q_f).astype(int)
    r_r = np.round(r_f).astype(int)
    s_r = np.round(-q_f - r_f).astype(int)
    q_diff = np.abs(q_r - q_f)
    r_diff = np.abs(r_r - r_f)
    s_diff = np.abs(s_r - (-q_f - r_f))
    mask_q = (q_diff > r_diff) & (q_diff > s_diff)
    q_r[mask_q] = -r_r[mask_q] - s_r[mask_q]
    mask_r = (~mask_q) & (r_diff > s_diff)
    r_r[mask_r] = -q_r[mask_r] - s_r[mask_r]

    d = points_data.copy()
    d['hex_q'] = q_r
    d['hex_r'] = r_r

    R = d['Red'].astype(float)
    G = d['Green'].astype(float)
    B = d['Blue'].astype(float)

    # --- Cechy per-punkt liczone PRZED grupowaniem (wektoryzowane) ---
    total = R + G + B + eps
    d['chroma_r'] = R / total
    d['chroma_g'] = G / total
    d['chroma_b'] = B / total
    d['gri'] = (G - R) / (G + R + eps)
    d['gbi'] = (G - B) / (G + B + eps)
    d['rbi'] = (R - B) / (R + B + eps)
    d['brightness'] = (R + G + B) / 3.0
    d['return_ratio'] = d['ReturnNumber'] / (d['NumberOfReturns'] + eps)

    grouped = d.groupby(['hex_q', 'hex_r'])

    # Agregacja (bez filtrowania — w produkcji KAŻDY heksagon dostaje predykcję)
    agg = grouped.agg(
        mean_chroma_r=('chroma_r', 'mean'), std_chroma_r=('chroma_r', 'std'),
        mean_chroma_g=('chroma_g', 'mean'), std_chroma_g=('chroma_g', 'std'),
        mean_chroma_b=('chroma_b', 'mean'), std_chroma_b=('chroma_b', 'std'),
        mean_gri=('gri', 'mean'), std_gri=('gri', 'std'),
        mean_gbi=('gbi', 'mean'), std_gbi=('gbi', 'std'),
        mean_rbi=('rbi', 'mean'), std_rbi=('rbi', 'std'),
        mean_R=('Red', 'mean'), std_R=('Red', 'std'),
        mean_G=('Green', 'mean'), std_G=('Green', 'std'),
        mean_B=('Blue', 'mean'), std_B=('Blue', 'std'),
        mean_brightness=('brightness', 'mean'), std_brightness=('brightness', 'std'),
        mean_I=('Intensity', 'mean'), std_I=('Intensity', 'std'),
        std_Z=('Z', 'std'),
        mean_return_ratio=('return_ratio', 'mean'),
    )
    agg = agg.fillna(0)  # std z 1 punktu → NaN → 0

    # Współczynniki zmienności (bezwymiarowe)
    agg['cv_R'] = agg['std_R'] / (agg['mean_R'] + eps)
    agg['cv_G'] = agg['std_G'] / (agg['mean_G'] + eps)
    agg['cv_B'] = agg['std_B'] / (agg['mean_B'] + eps)
    agg['cv_brightness'] = agg['std_brightness'] / (agg['mean_brightness'] + eps)
    agg['cv_I'] = agg['std_I'] / (agg['mean_I'] + eps)

    hex_features_df = agg[[
        'mean_chroma_r', 'std_chroma_r', 'mean_chroma_g', 'std_chroma_g',
        'mean_chroma_b', 'std_chroma_b', 'mean_gri', 'std_gri',
        'mean_gbi', 'std_gbi', 'mean_rbi', 'std_rbi',
        'cv_R', 'cv_G', 'cv_B',
        'mean_brightness', 'std_brightness', 'cv_brightness',
        'mean_I', 'std_I', 'cv_I', 'std_Z', 'mean_return_ratio',
    ]].copy()

    # ========================================================
    # CECHY SĄSIEDZTWA (v4) — liczone z PEŁNEJ chmury w promieniu
    # NEIGHBOR_RADIUS. To one dają modelowi geometrię: gładki beton
    # vs chropowata droga gruntowa.
    # ========================================================
    from scipy.spatial import cKDTree

    hex_coords = [tuple(i) for i in agg.index]
    centroids = np.array([axial_to_cartesian(q, r, HEX_SIZE) for q, r in hex_coords])

    print(f"   Buduję KDTree ({len(X):,} punktów), promień {NEIGHBOR_RADIUS} m...")
    tree = cKDTree(np.column_stack([X, Y]))

    Zc  = d['Z'].values.astype(float)
    Ic  = d['Intensity'].values.astype(float)
    Brc = d['brightness'].values.astype(float)

    n_hex = len(centroids)
    planarity = np.zeros(n_hex)
    nb_std_Z  = np.zeros(n_hex)
    nb_std_I  = np.zeros(n_hex)
    nb_std_br = np.zeros(n_hex)
    nb_contr  = np.ones(n_hex)

    hex_mean_I = agg['mean_I'].values
    neighbor_idx = tree.query_ball_point(centroids, r=NEIGHBOR_RADIUS, workers=-1)

    for i, idxs in enumerate(neighbor_idx):
        if len(idxs) < MIN_NEIGHBORS:
            continue
        idxs = np.asarray(idxs)
        nx, ny, nz = X[idxs], Y[idxs], Zc[idxs]
        nI, nB = Ic[idxs], Brc[idxs]

        # dopasowanie płaszczyzny z = a·x + b·y + c → RMS reszt
        n = len(nz)
        x0, y0, z0 = nx.mean(), ny.mean(), nz.mean()
        A = np.column_stack([nx - x0, ny - y0, np.ones(n)])
        try:
            coef, *_ = np.linalg.lstsq(A, nz - z0, rcond=None)
            resid = (nz - z0) - (A @ coef)
            planarity[i] = float(np.sqrt(np.mean(resid ** 2)))
        except Exception:
            planarity[i] = 0.0

        nb_std_Z[i]  = np.std(nz)
        nb_std_I[i]  = np.std(nI)
        nb_std_br[i] = np.std(nB)
        nb_contr[i]  = hex_mean_I[i] / (np.mean(nI) + eps)

    hex_features_df['nb_planarity']      = planarity
    hex_features_df['nb_std_Z']          = nb_std_Z
    hex_features_df['nb_std_I']          = nb_std_I
    hex_features_df['nb_std_brightness'] = nb_std_br
    hex_features_df['nb_I_contrast']     = nb_contr

    hex_features = hex_features_df[FEATURE_ORDER].values

    print(f"Utworzono {len(hex_coords)} heksagonów z {len(d)} punktów")
    return hex_features, hex_coords, {}, d

class QGISHexLidarPredictor:
    def __init__(self):
        self.model = None
        self.hex_size = HEX_SIZE

    def load_model(self, model_path):
        try:
            bundle = joblib.load(model_path)
            # bundle to słownik z pbc_train_rf.py; obsłuż też goły model
            if isinstance(bundle, dict) and 'model' in bundle:
                self.model = bundle['model']
                saved_order = bundle.get('feature_order')
                if saved_order and list(saved_order) != FEATURE_ORDER:
                    print("⚠️ UWAGA: kolejność cech w modelu różni się od FEATURE_ORDER!")
            else:
                self.model = bundle
            print(f"✅ Model Random Forest załadowany z {model_path}")
            return True
        except Exception as e:
            print(f"Błąd ładowania modelu: {e}")
            return False

    def predict_hexagons(self, points_df):
        try:
            X_hex, hex_coords, hex_groups, _ = create_hexagon_features(points_df)
            if len(X_hex) == 0:
                print("Brak heksagonów do predykcji!")
                return pd.DataFrame()
            print(f"Utworzono {len(X_hex)} heksagonów o wymiarach {X_hex.shape}")

            predictions = self.model.predict(X_hex)

            # --- Prawdopodobieństwa: pewność klasy + P(PBC) ---
            try:
                proba = self.model.predict_proba(X_hex)
                confidence = proba.max(axis=1)
                # P(PBC) = suma prawdopodobieństw klas biologicznie czynnych
                pbc_cols = [j for j, c in enumerate(self.model.classes_)
                            if int(c) in PBC_CLASSES]
                p_pbc = proba[:, pbc_cols].sum(axis=1)
            except Exception:
                confidence = np.ones(len(predictions))
                p_pbc = np.array([1.0 if MULTICLASS_TO_BINARY.get(int(p), 1) == 0 else 0.0
                                  for p in predictions])

            hex_df = pd.DataFrame({
                'hex_q': [c[0] for c in hex_coords],
                'hex_r': [c[1] for c in hex_coords],
                'center_x': [axial_to_cartesian(c[0], c[1], HEX_SIZE)[0] for c in hex_coords],
                'center_y': [axial_to_cartesian(c[0], c[1], HEX_SIZE)[1] for c in hex_coords],
                'predicted_label_multi': predictions.astype(int),
                'confidence': np.round(confidence, 3),
                'p_pbc': np.round(p_pbc, 3),
            })

            # ⚠️ DECYZJA BINARNA NA PROGU, nie na argmax.
            # PBC (0) tylko gdy P(PBC) > PBC_THRESHOLD; inaczej nie-PBC (1).
            hex_df['predicted_label'] = np.where(p_pbc > PBC_THRESHOLD, 0, 1)

            n_flip = int((hex_df['predicted_label'] !=
                          hex_df['predicted_label_multi'].map(MULTICLASS_TO_BINARY)).sum())
            if n_flip:
                print(f"   Próg P(PBC)>{PBC_THRESHOLD}: {n_flip} heksagonów "
                      f"zmieniło kategorię względem argmax")

            return hex_df
        except Exception as e:
            print(f"Błąd predykcji: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()


# === Funkcje pomocnicze ===
def safe_add_layer_to_project(layer, layer_name=None):
    try:
        if layer_name:
            layer.setName(layer_name)
        existing_layers = [l.name() for l in QgsProject.instance().mapLayers().values()]
        if layer.name() in existing_layers:
            print(f"Warstwa {layer.name()} już istnieje - usuwam starą")
            for l in QgsProject.instance().mapLayers().values():
                if l.name() == layer.name():
                    QgsProject.instance().removeMapLayer(l.id())
                    break
        QgsProject.instance().addMapLayer(layer, False)
        root = QgsProject.instance().layerTreeRoot()
        root.insertLayer(0, layer)
        print(f"✅ Bezpiecznie dodano warstwę: {layer.name()}")
        return True
    except Exception as e:
        print(f"❌ Błąd dodawania warstwy: {e}")
        return False


def layer_to_df(layer):
    data = []
    for f in layer.getFeatures():
        row = f.attributes()
        geom = f.geometry()
        if geom and not geom.isEmpty():
            pt = geom.asPoint()
            row.extend([pt.x(), pt.y()])
        else:
            row.extend([None, None])
        data.append(row)
    cols = [field.name() for field in layer.fields()] + ['geom_x', 'geom_y']
    return pd.DataFrame(data, columns=cols)

def wczytaj_heksagony_do_qgis(csv_path, nazwa_warstwy, hex_size=HEX_SIZE, crs=project_crs):
    """Wczytuje CSV z centroidami heksagonów i tworzy warstwę poligonową."""
    df = pd.read_csv(csv_path)
    
    for lyr in QgsProject.instance().mapLayersByName(nazwa_warstwy):
        QgsProject.instance().removeMapLayer(lyr.id())

    fields = QgsFields()
    fields.append(QgsField("hex_q", QVariant.Int))
    fields.append(QgsField("hex_r", QVariant.Int))
    fields.append(QgsField("predicted_label", QVariant.Int))
    fields.append(QgsField("predicted_label_multi", QVariant.Int))
    fields.append(QgsField("class_name", QVariant.String))
    fields.append(QgsField("confidence", QVariant.Double))
    fields.append(QgsField("p_pbc", QVariant.Double))

    CLASS_NAMES_LOCAL = {
        0: "Trawnik zadbany", 1: "Roślinność ruderalna", 2: "Pole uprawne",
        3: "Zaorane pole", 4: "Droga gruntowa", 5: "Asfalt", 6: "Beton",
        7: "Kostka czerwona", 8: "Kostka niebieska", 9: "Kort tenisowy",
        10: "Beton cień", 11: "Trawa cień", 12: "Gleba cień", 13: "Boisko",
    }

    layer = QgsVectorLayer("Polygon", nazwa_warstwy, "memory")
    layer.setCrs(crs)                 # crs to już obiekt QgsCoordinateReferenceSystem
    provider = layer.dataProvider()

    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()

    features = []
    for _, row in df.iterrows():
        cx, cy = float(row['center_x']), float(row['center_y'])
        pts = []
        for i in range(6):
            angle = math.radians(60 * i)
            pts.append(QgsPointXY(
                cx + hex_size * math.cos(angle),
                cy + hex_size * math.sin(angle)
            ))
        pts.append(pts[0])

        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry.fromPolygonXY([pts]))
        feat.setAttribute("hex_q", int(row['hex_q']))
        feat.setAttribute("hex_r", int(row['hex_r']))
        feat.setAttribute("predicted_label", int(row['predicted_label']))
        feat.setAttribute("predicted_label_multi", int(row['predicted_label_multi']))
        feat.setAttribute("class_name", CLASS_NAMES_LOCAL.get(int(row['predicted_label_multi']), "?"))
        feat.setAttribute("confidence", float(row['confidence']) if 'confidence' in row else 1.0)
        feat.setAttribute("p_pbc", float(row['p_pbc']) if 'p_pbc' in row else 0.0)
        features.append(feat)

    provider.addFeatures(features)
    layer.updateExtents()
    safe_add_layer_to_project(layer)
    # Zapisz do GeoPackage w folderze projektu
    gpkg_path = os.path.join(project_directory, f"{nazwa_warstwy}.gpkg")
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, gpkg_path, QgsCoordinateTransformContext(),
        QgsVectorFileWriter.SaveVectorOptions()
    )
    if error[0] == QgsVectorFileWriter.WriterError.NoError:
        print(f"  💾 Zapisano: {gpkg_path}")
    else:
        print(f"  ⚠️ Błąd zapisu GPKG: {error}")
    print(f"✅ Wczytano {len(features)} heksagonów jako poligony")
    return layer


def konwertuj_kolumny_na_int(warstwa, nazwy_kolumn):
    provider = warstwa.dataProvider()
    for nazwa_kolumny in nazwy_kolumn:
        field_index = warstwa.fields().lookupField(nazwa_kolumny)
        if field_index == -1:
            continue
        nowe_pole = QgsField(f"{nazwa_kolumny}_int", QVariant.Int)
        provider.addAttributes([nowe_pole])
        warstwa.updateFields()
        nowy_field_index = warstwa.fields().lookupField(f"{nazwa_kolumny}_int")
        warstwa.startEditing()
        for feature in warstwa.getFeatures():
            stara_wartosc = feature[nazwa_kolumny]
            try:
                nowa_wartosc = int(str(stara_wartosc)) if stara_wartosc is not None else 0
                warstwa.changeAttributeValue(feature.id(), nowy_field_index, nowa_wartosc)
            except (ValueError, TypeError):
                warstwa.changeAttributeValue(feature.id(), nowy_field_index, 0)
        warstwa.commitChanges()
        provider.deleteAttributes([field_index])
        warstwa.updateFields()
        warstwa.startEditing()
        nowy_field_index = warstwa.fields().lookupField(f"{nazwa_kolumny}_int")
        provider.renameAttributes({nowy_field_index: nazwa_kolumny})
        warstwa.commitChanges()
        warstwa.updateFields()
    return warstwa


def apply_qml_style_to_layer(layer, qml_file_path=None, show_messages=True):
    if isinstance(layer, str):
        layer_name = layer
        layer = None
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == layer_name:
                layer = lyr
                break
        if layer is None:
            if show_messages:
                print(f"Nie znaleziono warstwy: {layer_name}")
            return False
    if not os.path.exists(qml_file_path):
        if show_messages:
            print(f"Plik QML nie istnieje: {qml_file_path}")
        return False
    try:
        result = layer.loadNamedStyle(qml_file_path)
        if result[1]:
            layer.triggerRepaint()
            if show_messages:
                print(f"Styl zastosowany do warstwy: {layer.name()}")
            return True
        else:
            if show_messages:
                print(f"Nie udało się załadować stylu: {result[0]}")
            return False
    except Exception as e:
        if show_messages:
            print(f"Błąd ładowania stylu: {str(e)}")
        return False


def diagnose_layers(layer1, layer2):
    print("\n🔍 DIAGNOSTYKA WARSTW:")
    crs1 = layer1.crs().authid()
    crs2 = layer2.crs().authid()
    print(f"CRS warstwy punktowej: {crs1}")
    print(f"CRS warstwy maski: {crs2}")
    if crs1 != crs2:
        print("⚠️ UWAGA: Różne układy współrzędnych!")
    extent1 = layer1.extent()
    extent2 = layer2.extent()
    print(f"\nZakres warstwy punktowej: X: {extent1.xMinimum():.2f} - {extent1.xMaximum():.2f}, Y: {extent1.yMinimum():.2f} - {extent1.yMaximum():.2f}")
    print(f"Zakres warstwy maski: X: {extent2.xMinimum():.2f} - {extent2.xMaximum():.2f}, Y: {extent2.yMinimum():.2f} - {extent2.yMaximum():.2f}")
    intersection = extent1.intersect(extent2)
    if intersection.isEmpty():
        print("❌ ZAKRESY SIĘ NIE PRZECINAJĄ!")
        return False
    print("✅ Zakresy się przecinają")
    return True


def clip_layer_advanced(punkt_layer, mask_layer, output_name='clipped'):
    """
    Przycina punkty do maski POWIĘKSZONEJ o NEIGHBOR_RADIUS.

    ⚠️ DLACZEGO BUFOR: cechy sąsiedztwa (nb_planarity itd.) liczą się z punktów
    w promieniu NEIGHBOR_RADIUS. Gdyby przyciąć punkty dokładnie do granicy
    działki, heksagony przy krawędzi miałyby OBCIĘTE otoczenie → inne wartości
    cech niż w treningu → cichy błąd predykcji. Bufor to naprawia.
    Heksagony spoza działki są odfiltrowane PO predykcji (filter_hexes_to_mask).
    """
    print("\n🔧 ROZPOCZYNAM PRZYCINANIE...")
    if not diagnose_layers(punkt_layer, mask_layer):
        return None

    # Powiększ maskę o promień sąsiedztwa
    try:
        buf = processing.run("native:buffer", {
            'INPUT': mask_layer,
            'DISTANCE': NEIGHBOR_RADIUS,
            'SEGMENTS': 5,
            'DISSOLVE': False,
            'OUTPUT': 'memory:mask_nb_buffered'
        })['OUTPUT']
        print(f"   Maska powiększona o {NEIGHBOR_RADIUS} m (dla cech sąsiedztwa)")
    except Exception as e:
        print(f"   ⚠️ Nie udało się buforować maski: {e} — używam oryginalnej")
        buf = mask_layer

    # Metoda 1: Extract by location
    try:
        parametry = {
            'INPUT': punkt_layer,
            'PREDICATE': [0],
            'INTERSECT': buf,
            'OUTPUT': f'memory:{output_name}'
        }
        wynik = processing.run("native:extractbylocation", parametry)
        warstwa_wynik = wynik['OUTPUT']
        if warstwa_wynik.featureCount() > 0:
            print(f"✅ SUKCES: {warstwa_wynik.featureCount()} obiektów")
            safe_add_layer_to_project(warstwa_wynik)
            return warstwa_wynik
    except Exception as e:
        print(f"❌ Błąd: {e}")

    # Metoda 2: Z dodatkowym buforem
    try:
        parametry_buffer = {
            'INPUT': mask_layer,
            'DISTANCE': NEIGHBOR_RADIUS + 1,
            'OUTPUT': 'memory:mask_buffered'
        }
        wynik_buffer = processing.run("native:buffer", parametry_buffer)
        mask_buffered = wynik_buffer['OUTPUT']
        parametry = {
            'INPUT': punkt_layer,
            'PREDICATE': [0],
            'INTERSECT': mask_buffered,
            'OUTPUT': f'memory:{output_name}_buffered'
        }
        wynik = processing.run("native:extractbylocation", parametry)
        warstwa_wynik = wynik['OUTPUT']
        if warstwa_wynik.featureCount() > 0:
            print(f"✅ SUKCES Z BUFOREM: {warstwa_wynik.featureCount()} obiektów")
            safe_add_layer_to_project(warstwa_wynik)
            return warstwa_wynik
    except Exception as e:
        print(f"❌ Błąd z buforem: {e}")

    print("❌ Wszystkie metody zawiodły")
    return None


def filter_hexes_to_mask(hex_df, mask_layer):
    """
    Zostawia tylko heksagony, których centroid leży wewnątrz maski (działki).
    Potrzebne, bo punkty przycinamy do maski POWIĘKSZONEJ o NEIGHBOR_RADIUS —
    heksagony z tego bufora służą tylko do policzenia pełnego sąsiedztwa,
    ale nie należą do analizowanego terenu.
    """
    from qgis.core import QgsSpatialIndex, QgsFeatureRequest, QgsCoordinateTransform

    if hex_df.empty:
        return hex_df

    # geometrie maski (w CRS warstwy maski)
    mask_crs = mask_layer.crs()
    tr = None
    if mask_crs != project_crs:
        tr = QgsCoordinateTransform(project_crs, mask_crs, QgsProject.instance())

    index = QgsSpatialIndex(mask_layer.getFeatures())
    geoms = {f.id(): f.geometry() for f in mask_layer.getFeatures()}

    keep = []
    for _, row in hex_df.iterrows():
        pt = QgsPointXY(float(row['center_x']), float(row['center_y']))
        if tr:
            pt = tr.transform(pt)
        g = QgsGeometry.fromPointXY(pt)
        candidates = index.intersects(g.boundingBox())
        inside = any(geoms[fid].contains(g) for fid in candidates)
        keep.append(inside)

    return hex_df[np.array(keep)].reset_index(drop=True)


# === GŁÓWNA FUNKCJA ===
def run_terrain_prediction(nazwa_punktow, nazwa_maski, nazwa_warstwy_przyciete, 
                           nazwa_warstwy_wynik, output_csv_name):
    """
    Główna funkcja do predykcji terenu.
    """
    print(f"\n{'='*60}")
    print(f"🚀 ROZPOCZYNAM PREDYKCJĘ: {nazwa_warstwy_wynik}")
    print(f"{'='*60}")
    
    output_csv = os.path.join(project_directory, output_csv_name)
    
    # 1. Przycinanie warstwy
    print("🎯 KROK 1: Przycinanie warstwy...")
    warstwy_punktowe = QgsProject.instance().mapLayersByName(nazwa_punktow)
    warstwy_maski = QgsProject.instance().mapLayersByName(nazwa_maski)
    
    if not warstwy_punktowe:
        print(f"❌ Nie znaleziono warstwy: {nazwa_punktow}")
        return False
    if not warstwy_maski:
        print(f"❌ Nie znaleziono warstwy: {nazwa_maski}")
        return False
    
    warstwa_punktowa = warstwy_punktowe[0]
    warstwa_maski = warstwy_maski[0]
    print(f"✅ Warstwa punktowa: {warstwa_punktowa.featureCount()} obiektów")
    print(f"✅ Warstwa maski: {warstwa_maski.featureCount()} obiektów")
    
    warstwa_przycieta = clip_layer_advanced(warstwa_punktowa, warstwa_maski, nazwa_warstwy_przyciete)
    
    if not warstwa_przycieta or warstwa_przycieta.featureCount() == 0:
        print("❌ Nie udało się przyciąć warstwy")
        return False
    
    print(f"✅ Przycięto: {warstwa_przycieta.featureCount()} obiektów")
    
   # 2. Predykcja
    print("\n🎯 KROK 2: Predykcja...")
    layer_df = layer_to_df(warstwa_przycieta)
    print(f"Kształt danych: {layer_df.shape}")

    required_cols = ['X', 'Y'] + INPUT_FEATURES
    missing_cols = [col for col in required_cols if col not in layer_df.columns]
    if missing_cols:
        print(f"❌ Brakuje kolumn: {missing_cols}")
        return False

    predictor = QGISHexLidarPredictor()
    if not predictor.load_model(MODEL_PATH):
        print("❌ Nie można wczytać modelu!")
        return False

    hex_df = predictor.predict_hexagons(layer_df)

    if hex_df.empty:
        print("❌ Brak wyników predykcji")
        return False

    # ⚠️ Odfiltruj heksagony z BUFORA — punkty były przycięte do maski
    # powiększonej o NEIGHBOR_RADIUS (żeby sąsiedztwo było pełne), ale
    # do wyniku trafiają tylko heksagony, których centroid leży W MASCE.
    n_before = len(hex_df)
    hex_df = filter_hexes_to_mask(hex_df, warstwa_maski)
    if len(hex_df) < n_before:
        print(f"   Odfiltrowano {n_before - len(hex_df)} heksagonów z bufora "
              f"→ zostaje {len(hex_df)}")
    if hex_df.empty:
        print("❌ Brak heksagonów wewnątrz maski")
        return False

    # Statystyki
    print("\nRozkład predykcji (heksagony):")
    for class_id, count in hex_df['predicted_label_multi'].value_counts().sort_index().items():
        percentage = (count / len(hex_df)) * 100
        print(f"   Klasa {class_id}: {count:,} heksagonów ({percentage:.1f}%)")

    # Zapisz
    hex_df.to_csv(output_csv, index=False)
    print(f"✅ Zapisano {len(hex_df)} heksagonów do: {output_csv}")

    # Usuń warstwę tymczasową
    print("\n🧹 Usuwam warstwę tymczasową...")
    try:
        QgsProject.instance().removeMapLayer(warstwa_przycieta.id())
        print(f"✅ Usunięto: {nazwa_warstwy_przyciete}")
    except Exception as e:
        print(f"⚠️ {e}")

    # 3. Wczytaj warstwę wynikową
    print("\n🎯 KROK 3: Wczytywanie warstwy wynikowej...")

    result_layer = wczytaj_heksagony_do_qgis(output_csv, nazwa_warstwy_wynik)

    if not result_layer:
        print(f"❌ Błąd tworzenia warstwy {nazwa_warstwy_wynik}")
        return False

    style_path = os.path.join(SCRIPTS_PATH, "style/PBC_hex.qml")
    apply_qml_style_to_layer(nazwa_warstwy_wynik, style_path)
    print(f"✅ Warstwa {nazwa_warstwy_wynik} utworzona pomyślnie!")
    return True

# === WYKONANIE ===
 # Predykcja 1: Działki zgodne z funkcją

run_terrain_prediction(
    nazwa_punktow='Classification_2',
    nazwa_maski='dzialki_zgodne_z_funkcja',
    nazwa_warstwy_przyciete='Classification_2_przyciete',
    nazwa_warstwy_wynik='heksagony_pbc_predykcja',
    output_csv_name='heksagony_pbc_predykcja.csv'
)

run_terrain_prediction(
    nazwa_punktow='Classification_2',
    nazwa_maski='granica_terenu',
    nazwa_warstwy_przyciete='Classification_2_przyciete_teren',
    nazwa_warstwy_wynik='heksagony_pbc_predykcja_teren',
    output_csv_name='heksagony_pbc_predykcja_teren.csv'
)
print("\n🎉 WSZYSTKIE PREDYKCJE ZAKOŃCZONE!")