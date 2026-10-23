#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kompletny poprawiony skrypt QGIS
- Optymalizacja dla dużych zbiorów punktów
- Zabezpieczenia przed OOM (Out of Memory)
- Automatyczna klasyfikacja warstwy punktowej (bez potrzeby ręcznego "Klasyfikuj")
"""
import processing
from qgis.core import (QgsProject, QgsVectorLayer, QgsFeature, QgsWkbTypes,QgsGradientColorRamp, QgsGradientStop,
    QgsFields, QgsField, QgsGraduatedSymbolRenderer, QgsRendererRange,QgsMarkerSymbol, 
    )
from pathlib import Path
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

# Ciezkie biblioteki naukowe. Czytelny komunikat zamiast surowego bledu,
# gdy srodowisko QGIS ich nie ma albo ma niespojne numpy/scipy.
try:
    import pandas as pd
    import numpy as np
    from sklearn.cluster import DBSCAN
    from sklearn.linear_model import RANSACRegressor
    from sklearn.preprocessing import StandardScaler
    from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
except ImportError as _exc:
    raise ImportError(
        "Ten krok wymaga bibliotek: numpy, pandas, scipy, scikit-learn.\\n"
        "Zainstaluj je w srodowisku Pythona QGIS, np.:\\n"
        "    python3 -m pip install numpy pandas scipy scikit-learn\\n\\n"
        f"Szczegoly: {_exc}"
    ) from _exc
from qgis.utils import iface
import os
import gc  # Garbage collector dla zarządzania pamięcią

RNG_SEED = 42
KROK_PRZEDZIALU = 5           # [°]
MARGINES_GRANICY = 1.5       # [°] bliżej granicy niż to → zapis liczby zamiast przedziału
KAT_PLASKI = 2.5              # [°]

SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

# STAŁE OPTYMALIZACYJNE - MOŻESZ JE ZMNIEJSZYĆ JEŚLI DALEJ SĄ PROBLEMY Z PAMIĘCIĄ
MAX_POINTS_FOR_RANSAC = 5000  # Maksymalna liczba punktów dla RANSAC
MAX_POINTS_FOR_DBSCAN = 10000  # Maksymalna liczba punktów dla DBSCAN
BATCH_SIZE = 1000  # Rozmiar batcha dla przetwarzania


def apply_optimized_point_classification(layer_name):
    """
    Koloruje punkty dachów turbo, z normalizacją Z PER BUDYNEK — identycznie jak
    rasteryzacja do modelu (formuła z build_dsm: podłoga zakresu 0.6 m, DATA_FLOOR 0.12).

    Zamiast globalnego min/max po całym zbiorze: każdy budynek normalizowany osobno.
    Dodaje pole Z_norm (= dokładnie wartość, którą koloruje turbo w rastrze) i ustawia
    graduowany renderer turbo na [0,1]. Sygnatura, zapis QML i return jak w oryginale.
    """
    

    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        print(f"❌ Nie znaleziono warstwy: {layer_name}")
        return False
    layer = layers[0]

    field_name, id_field = 'Z', 'ID_BUDYNKU'
    fi = layer.fields().indexFromName(field_name)
    bi = layer.fields().indexFromName(id_field)
    if fi == -1 or bi == -1:
        print(f"❌ Wymagane pola '{field_name}' i '{id_field}' "
              f"(Z={fi != -1}, ID_BUDYNKU={bi != -1})")
        return False

    print(f"⚡ Normalizacja Z per budynek dla {layer.featureCount()} punktów...")

    # 1) min/max Z per budynek — jeden przebieg O(n)
    zmin, zmax = {}, {}
    for f in layer.getFeatures():
        attrs = f.attributes()
        b, z = attrs[bi], attrs[fi]
        if z is None:
            continue
        z = float(z)
        if b not in zmin or z < zmin[b]:
            zmin[b] = z
        if b not in zmax or z > zmax[b]:
            zmax[b] = z
    if not zmin:
        print("❌ Brak wartości Z")
        return False

    # 2) pole Z_norm (dodaj jeśli nie istnieje)
    if layer.fields().indexFromName('Z_norm') == -1:
        layer.dataProvider().addAttributes([QgsField('Z_norm', QVariant.Double)])
        layer.updateFields()
    ni = layer.fields().indexFromName('Z_norm')

    # 3) policz Z_norm (formuła build_dsm) i zapisz hurtowo (szybciej niż per-feature)
    DATA_FLOOR, MIN_RANGE = 0.12, 0.6
    updates = {}
    for f in layer.getFeatures():
        attrs = f.attributes()
        b, z = attrs[bi], attrs[fi]
        if z is None or b not in zmin:
            continue
        rng = max(zmax[b] - zmin[b], MIN_RANGE)
        v = DATA_FLOOR + (1 - DATA_FLOOR) * min(max((float(z) - zmin[b]) / rng, 0.0), 1.0)
        updates[f.id()] = {ni: float(v)}
    layer.dataProvider().changeAttributeValues(updates)
    layer.updateFields()
    print(f"✓ Z_norm policzone dla {len(updates)} punktów")

    # 4) rampa turbo — dokładnie matplotlib turbo (jak w rasterze); fallback gdyby brakło mpl
    def turbo_ramp(n=32):
        def qc(r, g, b):
            return QColor(int(r * 255), int(g * 255), int(b * 255))
        try:
            import matplotlib
            cmap = matplotlib.colormaps['turbo']
            stops = [QgsGradientStop(k / n, qc(*cmap(k / n)[:3])) for k in range(1, n)]
            return QgsGradientColorRamp(qc(*cmap(0.0)[:3]), qc(*cmap(1.0)[:3]), False, stops)
        except Exception:
            hexes = ['#30123b', '#4145ab', '#4675ed', '#39a2fc', '#1bcfd4', '#24eca6',
                     '#61fc6c', '#a4fc3b', '#d1e834', '#f3c63a', '#fe9b2d', '#f36315',
                     '#cb2a04', '#7a0403']
            cols = [QColor(h) for h in hexes]
            stops = [QgsGradientStop(i / (len(cols) - 1), cols[i]) for i in range(1, len(cols) - 1)]
            return QgsGradientColorRamp(cols[0], cols[-1], False, stops)

    ramp = turbo_ramp()

    # 5) graduowany renderer na Z_norm w STAŁYM [0,1] (Z_norm = pozycja w turbo,
    #    więc punkt o Z_norm=v dostaje turbo(v) — dokładnie jak piksel rastra)
    num_classes = 32   # zwiększ dla gładszego przejścia
    ranges = []
    for i in range(num_classes):
        lo, hi = i / num_classes, (i + 1) / num_classes
        col = ramp.color((i + 0.5) / num_classes)
        sym = QgsMarkerSymbol.createSimple({
            'name': 'circle',
            'color': col.name(),
            'outline_style': 'no',
            'size': '2',
        })
        ranges.append(QgsRendererRange(lo, hi, sym, f"{lo:.2f}–{hi:.2f}"))

    renderer = QgsGraduatedSymbolRenderer('Z_norm', ranges)
    renderer.setClassAttribute('Z_norm')
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    print(f"✅ Pokolorowano turbo (per budynek, {num_classes} klas)")

    # 6) zapis stylu (ta sama nazwa pliku co w oryginale)
    try:
        project_path = QgsProject.instance().fileName()
        if project_path:
            from pathlib import Path
            style_path = Path(project_path).parent / f"{layer_name}_auto_graduated.qml"
            layer.saveNamedStyle(str(style_path))
            print(f"💾 Styl zapisany: {style_path}")
    except Exception as e:
        print(f"⚠️ Zapisywanie stylu: {e}")

    return True


def zapis_do_gpkg(layer_name):
    """Zapisuje warstwę do pliku GPKG"""
    def fid_kolizja(warstwa):
        for field in warstwa.fields():
            if field.name().lower() == "fid" and field.typeName().lower() != "integer":
                return True
        return False

    def utworz_kopie_bez_fid(warstwa, nowa_nazwa):
        geometria = QgsWkbTypes.displayString(warstwa.wkbType())
        crs = warstwa.crs().authid()
        kopia = QgsVectorLayer(f"{geometria}?crs={crs}", nowa_nazwa, "memory")

        fields = QgsFields()
        for field in warstwa.fields():
            if field.name().lower() != "fid":
                fields.append(field)
        kopia.dataProvider().addAttributes(fields)
        kopia.updateFields()

        for feat in warstwa.getFeatures():
            nowy = QgsFeature(fields)
            attrs = [feat[field.name()] for field in fields]
            nowy.setAttributes(attrs)
            nowy.setGeometry(feat.geometry())
            kopia.dataProvider().addFeature(nowy)

        kopia.updateExtents()
        QgsProject.instance().addMapLayer(kopia)
        return kopia

    project_path = QgsProject.instance().fileName()
    if not project_path:
        print("❌ Projekt niezapisany.")
        return
    
    project_directory = Path(project_path).parent
    output_folder = Path(project_directory)
    
    if not output_folder.exists():
        output_folder.mkdir(parents=True, exist_ok=True)
        print(f"📂 Utworzono katalog: {output_folder}")
    else:
        print(f"📁 Katalog już istnieje: {output_folder}")
        
    output_path = f"{output_folder}/{layer_name}.gpkg"

    warstwy = QgsProject.instance().mapLayersByName(layer_name)
    if not warstwy:
        print(f"❌ Nie znaleziono warstwy: {layer_name}")
        return
    warstwa = warstwy[0]

    if fid_kolizja(warstwa):
        print("⚠️ Wykryto kolizję z polem 'fid'. Tworzę kopię bez tego pola.")
        warstwa = utworz_kopie_bez_fid(warstwa, f"{layer_name}_safe")

    processing.run("native:savefeatures", {
        'INPUT': warstwa,
        'OUTPUT': output_path
    })

    print(f"✅ Warstwa zapisana do: {output_path}")

    vlayer = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
    if vlayer.isValid():
        QgsProject.instance().addMapLayer(vlayer)
        print("✅ Warstwa wczytana ponownie do projektu.")
    else:
        print("❌ Nie udało się wczytać zapisanej warstwy.")


def remove_memory_layers():
    """Usuwa warstwy tymczasowe z pamięci"""
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.dataProvider().name() == 'memory':
            QgsProject.instance().removeMapLayer(lyr.id())
    gc.collect()  # Wymuszenie czyszczenia pamięci


def analyze_roof_slope_from_point_cloud(points_df, building_id):
    """
    Analizuje nachylenie dachu z optymalizacją dla dużych zbiorów punktów
    """
    if len(points_df) < 20:
        return {"slope": 0, "confidence": 0, "method": "insufficient_data"}
    
    # OPTYMALIZACJA: Dla bardzo dużych zbiorów używaj samplingu
    if len(points_df) > 20000:
        print(f"⚠️ Duży zbiór punktów ({len(points_df)}), używam samplingu...")
        sample_size = 15000
        points_df = points_df.sample(n=sample_size, random_state=42)
    
    points = points_df[['X', 'Y', 'Z']].values
    
    # === KROK 1: Czyszczenie danych ===
    cleaned_points = clean_point_cloud(points)
    
    if len(cleaned_points) < 15:
        return {"slope": 0, "confidence": 0, "method": "insufficient_clean_data"}
    
    # === KROK 2: Segmentacja płaszczyzn dachu ===
    roof_planes = segment_roof_planes(cleaned_points)
    
    if not roof_planes:
        return {"slope": 0, "confidence": 0, "method": "no_planes_found"}
    
    # === KROK 3: nachylenie każdej płaszczyzny (także płaskich!) ===
    plane_results = []  # (liczba_punktów, nachylenie, pewność)
    for plane_points in roof_planes:
        if len(plane_points) < 10:
            continue
        slope_info = calculate_plane_slope_robust(plane_points)
        if slope_info is None:
            continue
        plane_results.append((len(plane_points), slope_info['slope'], slope_info['confidence']))

    if not plane_results:
        return {
            "slope": calculate_overall_slope(cleaned_points),
            "confidence": 0.5,
            "method": "fallback_overall_accepted",
            "num_points": len(cleaned_points),
            "udzial_dominujacej": 0.0,
        }

    # === KROK 4: połać dominująca = segment z największą liczbą punktów ===
    n_dom, final_slope, confidence = max(plane_results, key=lambda p: p[0])
    udzial = n_dom / sum(p[0] for p in plane_results)

    return {
        "slope": final_slope,
        "confidence": confidence,
        "method": f"dominant_of_{len(plane_results)}",
        "num_points": len(cleaned_points),
        "udzial_dominujacej": udzial,
    }


def przedzial_nachylenia(slope):
    """
    Zwraca (od, do, etykieta).
    Blisko wielokrotności KROK_PRZEDZIALU → liczba, np. (30, 30, "30").
    Daleko od granicy → przedział [od, do), np. (20, 25, "20-25").
    """
    s = round(float(slope), 1)
    najblizsza = int(round(s / KROK_PRZEDZIALU) * KROK_PRZEDZIALU)
    if abs(s - najblizsza) < MARGINES_GRANICY:
        return najblizsza, najblizsza, str(najblizsza)
    od = int(np.floor(s / KROK_PRZEDZIALU) * KROK_PRZEDZIALU)
    do = od + KROK_PRZEDZIALU
    return od, do, f"{od}-{do}"


def clean_point_cloud(points):
    """Czyści chmurę punktów z outlierów"""
    z_values = points[:, 2]
    z_median = np.median(z_values)
    z_mad = np.median(np.abs(z_values - z_median))
    
    threshold = z_median + 3 * z_mad
    mask_z = z_values <= threshold
    
    z_10th_percentile = np.percentile(z_values, 10)
    mask_z_low = z_values >= z_10th_percentile
    
    final_mask = mask_z & mask_z_low
    
    return points[final_mask]


def segment_roof_planes(points):
    """
    Segmentuje punkty dachu na płaszczyzny używając DBSCAN
    Z optymalizacją dla dużych zbiorów
    """
    if len(points) < 15:
        return [points]
    
    # OPTYMALIZACJA: Sampling dla bardzo dużych zbiorów
    if len(points) > MAX_POINTS_FOR_DBSCAN:
        print(f"📊 DBSCAN: Sampling {MAX_POINTS_FOR_DBSCAN} z {len(points)} punktów...")
        indices = np.random.default_rng(RNG_SEED).choice(len(points), MAX_POINTS_FOR_DBSCAN, replace=False)
        points_sampled = points[indices]
    else:
        points_sampled = points
    
    # Oblicz lokalne normalne
    normals = calculate_local_normals(points_sampled)
    
    # Normalizuj współrzędne dla DBSCAN
    scaler = StandardScaler()
    points_scaled = scaler.fit_transform(points_sampled)
    
    # Połącz pozycje i normalne
    features = np.hstack([points_scaled, normals * 2])
    
    # DBSCAN clustering z optymalnymi parametrami
    clustering = DBSCAN(eps=0.3, min_samples=8).fit(features)
    
    # Pogrupuj punkty według klastrów
    segments = []
    unique_labels = set(clustering.labels_)
    
    for label in unique_labels:
        if label != -1:  # Ignoruj szum
            mask = clustering.labels_ == label
            segment_points = points_sampled[mask]
            if len(segment_points) >= 10:
                segments.append(segment_points)
    
    print(f"🔍 segment roof: znaleziono {len(segments)} segmentów")
    for i, segment in enumerate(segments[:10]):  # Wyświetl max 10 pierwszych
        print(f" Segment {i}: {len(segment)} punktów")
    
    if not segments:
        segments = [points_sampled]
    
    return segments


def calculate_local_normals(points, k=8):
    """Oblicza normalne lokalne używając PCA na sąsiadach"""
    from sklearn.neighbors import NearestNeighbors
    
    nbrs = NearestNeighbors(n_neighbors=min(k+1, len(points))).fit(points)
    distances, indices = nbrs.kneighbors(points)
    
    normals = []
    for i, neighbors_idx in enumerate(indices):
        neighbors = points[neighbors_idx]
        centered = neighbors - np.mean(neighbors, axis=0)
        
        try:
            _, _, V = np.linalg.svd(centered)
            normal = V[-1]
            
            if normal[2] < 0:
                normal = -normal
                
            normals.append(normal)
        except:
            normals.append([0, 0, 1])
    
    return np.array(normals)


def calculate_plane_slope_robust(points):
    """
    KLUCZOWA FUNKCJA - POPRAWIONA!
    Oblicza nachylenie płaszczyzny używając RANSAC
    Z zabezpieczeniami przed problemami pamięci
    """
    if len(points) < 10:
        return None
    
    # ZABEZPIECZENIE 1: Sampling dla dużych zbiorów
    if len(points) > MAX_POINTS_FOR_RANSAC:
        print(f"📊 RANSAC: Sampling {MAX_POINTS_FOR_RANSAC} z {len(points)} punktów...")
        indices = np.random.default_rng(RNG_SEED).choice(len(points), MAX_POINTS_FOR_RANSAC, replace=False)
        points_sampled = points[indices]
    else:
        points_sampled = points
    
    X = points_sampled[:, :2]  # x, y  
    y = points_sampled[:, 2]   # z
    
    print(f"🚀 Uruchamiam RANSAC dla {len(points_sampled)} punktów")
    
    try:
        # ZABEZPIECZENIE 2: Sprawdź zmienność danych
        z_std = np.std(y)
        if z_std < 0.01:  # Praktycznie płaska powierzchnia
            print("➡️ Powierzchnia praktycznie płaska (std < 0.01)")
            return {
                "slope": 0,
                "confidence": 1.0,
                "inlier_ratio": 1.0,
                "coefficients": [0, 0, np.mean(y)]
            }
        
        # ZABEZPIECZENIE 3: Optymalne parametry RANSAC
        min_pts = max(3, min(10, len(points_sampled) // 10))
        max_trials = min(50, max(10, len(points_sampled) // 50))
        
        ransac = RANSACRegressor(
            min_samples=min_pts,
            residual_threshold=max(0.1, z_std * 0.1),
            max_trials=max_trials,
            random_state=42
        )
        
        print(f"➡️ RANSAC params: min_samples={min_pts}, max_trials={max_trials}")
        
        # Próba dopasowania z obsługą błędów
        ransac.fit(X, y)
        
        if not hasattr(ransac, 'inlier_mask_') or ransac.inlier_mask_ is None:
            print("❌ RANSAC: brak inlier_mask_")
            return calculate_plane_slope_simple(points)
        
        # Oblicz nachylenie
        a, b = ransac.estimator_.coef_
        c = ransac.estimator_.intercept_
        
        normal = np.array([a, b, -1])
        normal = normal / np.linalg.norm(normal)
        
        cos_angle = abs(normal[2])
        if cos_angle > 0.999:
            slope_degrees = 0
        else:
            angle_rad = np.arccos(cos_angle)
            slope_degrees = np.degrees(angle_rad)
        
        # Pewność
        inlier_ratio = np.sum(ransac.inlier_mask_) / len(points_sampled)
        
        if len(points) > MAX_POINTS_FOR_RANSAC:
            confidence = inlier_ratio * 0.8  # Zmniejsz pewność dla samplowanych danych
        else:
            confidence = inlier_ratio
        
        return {
            "slope": slope_degrees,
            "confidence": confidence,
            "inlier_ratio": inlier_ratio,
            "coefficients": [a, b, c]
        }
        
    except MemoryError:
        print("❌ Brak pamięci dla RANSAC - używam uproszczonej metody")
        gc.collect()
        return calculate_plane_slope_simple(points)
    except Exception as e:
        print(f"❌ Wyjątek w RANSAC: {e}")
        return calculate_plane_slope_simple(points)


def calculate_plane_slope_simple(points):
    """Prosta metoda dopasowania płaszczyzny (fallback)"""
    print("🔄 Fallback: używam prostej metody")
    
    if len(points) < 3:
        return None
    
    # Sampling jeśli wciąż za dużo punktów
    if len(points) > 1000:
        indices = np.random.default_rng(RNG_SEED).choice(len(points), 1000, replace=False)
        points = points[indices]
    
    X = points[:, :2]
    y = points[:, 2]
    
    X_with_intercept = np.column_stack([X, np.ones(len(X))])
    
    try:
        coeffs, residuals, rank, s = np.linalg.lstsq(X_with_intercept, y, rcond=None)
        a, b, c = coeffs
        
        normal = np.array([a, b, -1])
        normal = normal / np.linalg.norm(normal)
        
        cos_angle = abs(normal[2])
        if cos_angle > 0.999:
            slope_degrees = 0
        else:
            angle_rad = np.arccos(cos_angle)
            slope_degrees = np.degrees(angle_rad)
        
        if len(residuals) > 0:
            mse = residuals[0] / len(points)
            confidence = max(0, 1 - mse)
        else:
            confidence = 0.5
    
        return {
            "slope": slope_degrees,
            "confidence": confidence,
            "method": "simple_lstsq"
        }
        
    except Exception as e:
        print(f"Błąd w prostej metodzie: {e}")
        return None


def calculate_overall_slope(points):
    """Oblicza ogólne nachylenie dachu (fallback method)"""
    if len(points) < 10:
        return 0
    
    try:
        points_2d = points[:, :2]
        points_centered = points_2d - np.mean(points_2d, axis=0)
        
        _, _, V = np.linalg.svd(points_centered)
        main_axis = V[0]
        
        projections = np.dot(points_centered, main_axis)
        horizontal_dist = np.max(projections) - np.min(projections)
     
        if horizontal_dist == 0:
            print("⚠️ Brak rozrzutu w kierunku głównej osi — nachylenie = 0")
            return 0
    
        median_proj = np.median(projections)
        mask_half1 = projections <= median_proj
        mask_half2 = projections > median_proj
    
        z_half1 = np.mean(points[mask_half1, 2]) if np.any(mask_half1) else None
        z_half2 = np.mean(points[mask_half2, 2]) if np.any(mask_half2) else None
    
        if z_half1 is not None and z_half2 is not None:
            height_diff = abs(z_half1 - z_half2)
        elif z_half1 is not None:
            height_diff = abs(z_half1 - np.mean(points[:, 2]))
        elif z_half2 is not None:
            height_diff = abs(z_half2 - np.mean(points[:, 2]))
        else:
            print("⚠️ Brak punktów w obu połówkach — nachylenie = 0")
            return 0
    
        slope_ratio = height_diff / horizontal_dist
        slope_degrees = np.degrees(np.arctan(slope_ratio))
        return slope_degrees
    
    except Exception as e:
        print("❌ Błąd w calculate_overall_slope:", e)
        return 0


def process_buildings_roof_slopes(points_layer):
    """Główna funkcja przetwarzania nachyleń dachów z optymalizacją pamięci"""    
    if not points_layer:
        print("❌ Brak aktywnej warstwy!")
        return
    
    buildings_layer = QgsProject.instance().mapLayersByName("budynki_z_szer_elew_front")[0]
    print(f"✅ Używam warstwy budynków: {buildings_layer.name()}")
    
    # OPTYMALIZACJA: Przetwarzaj punkty partiami
    print("📊 Pobieram punkty partiami...")
    points_data = []
    batch_counter = 0
    
    for feature in points_layer.getFeatures():
        row = {
            'X': feature.attribute('X'),
            'Y': feature.attribute('Y'),
            'Z': feature.attribute('Z'),
            'ID_BUDYNKU': feature.attribute('ID_BUDYNKU')
        }
        points_data.append(row)
        
        batch_counter += 1
        if batch_counter % 100000 == 0:
            print(f"  Przetworzono {batch_counter} punktów...")
            gc.collect()  # Czyszczenie pamięci co 100k punktów
    
    points_df = pd.DataFrame(points_data)
    print(f"✅ Pobrano {len(points_df)} punktów")
    print("Zakres wysokości Z:", points_df['Z'].min(), "–", points_df['Z'].max())
    
    # Czyszczenie pamięci po utworzeniu DataFrame
    del points_data
    gc.collect()
    
    # Dodaj pola do warstwy budynków
    pola_nachylenia = [
        ('nachylenie_chmura', QVariant.Double),     # surowy kąt, 0,1°
        ('pewnosc_nachylenia', QVariant.Double),
        ('metoda_nachylenia', QVariant.String),
        ('liczba_punktow', QVariant.Int),
        ('udzial_polaci_dom', QVariant.Double),     # udział połaci dominującej w punktach dachu
        ('nachylenie_od', QVariant.Int),
        ('nachylenie_do', QVariant.Int),
        ('nachylenie_przedzial', QVariant.String),  # "25-30"
    ]
    istniejace = [f.name() for f in buildings_layer.fields()]
    brakujace = [QgsField(n, t) for n, t in pola_nachylenia if n not in istniejace]
    if brakujace:
        buildings_layer.dataProvider().addAttributes(brakujace)
        buildings_layer.updateFields()
    
    buildings_layer.startEditing()
    
    # Przetwarzaj każdy budynek
    processed = 0
    for building_feature in buildings_layer.getFeatures():
        building_id = building_feature.attribute('ID_BUDYNKU')
        
        if building_id is None:
            continue
        
        # Pobierz punkty dla tego budynku
        building_points = points_df[points_df['ID_BUDYNKU'].astype(str) == str(building_id)]
        print(f"➡️ Budynek {building_id}: {len(building_points)} punktów")
        
        if len(building_points) < 10:
            slope_info = {"slope": 0, "confidence": 0, "method": "insufficient_points", "num_points": len(building_points)}
        else:
            slope_info = analyze_roof_slope_from_point_cloud(building_points, building_id)
        
        # Zapis wyników
        slope = slope_info.get('slope', 0) or 0
        if slope <= KAT_PLASKI:
            slope = 0.0

        metoda = str(slope_info.get('method', 'unknown'))
        brak_danych = metoda.startswith(('insufficient', 'no_planes'))
        if brak_danych:
            od = do = przedzial = None
        else:
            od, do, przedzial = przedzial_nachylenia(slope)

        wartosci = {
            'nachylenie_chmura': None if brak_danych else round(float(slope), 1),
            'pewnosc_nachylenia': round(float(slope_info.get('confidence', 0)), 2),
            'metoda_nachylenia': metoda,
            'liczba_punktow': int(slope_info.get('num_points', 0)),
            'udzial_polaci_dom': round(float(slope_info.get('udzial_dominujacej', 0)), 2),
            'nachylenie_od': od,
            'nachylenie_do': do,
            'nachylenie_przedzial': przedzial,
        }
        for nazwa, wartosc in wartosci.items():
            buildings_layer.changeAttributeValue(
                building_feature.id(), buildings_layer.fields().indexOf(nazwa), wartosc)
        
        processed += 1
        if processed % 10 == 0:
            print(f"⏳ Przetworzono {processed} budynków...")
            gc.collect()  # Czyszczenie pamięci
    
    buildings_layer.commitChanges()
    print(f"✅ Analiza zakończona! Przetworzono {processed} budynków")


# =====================================================================
# FUNKCJE OBLICZANIA WYSOKOŚCI BUDYNKÓW (v2 – interpolacja DTM)
# =====================================================================
# Zamiast:  mean(dach) − mean(grunt_per_działka)
# Teraz:    interpolacja TIN z gruntu → per-point subtraction → filtracja
#           kominów/anten → wyznaczenie kalenicy
# =====================================================================


def interpolate_ground_surface(ground_xy, ground_z, query_xy):
    """
    Buduje NMT (TIN) z punktów gruntu i interpoluje wysokość terenu
    w lokalizacjach query_xy (= punkty dachu).

    Używa triangulacji Delaunay + interpolacji liniowej – identycznie
    jak przy tworzeniu numerycznego modelu terenu.
    Punkty poza convex hull triangulacji uzupełnia nearest-neighbor.
    """
    if len(ground_xy) < 3:
        if len(ground_xy) == 0:
            return np.full(len(query_xy), np.nan)
        interp = NearestNDInterpolator(ground_xy, ground_z)
        return interp(query_xy)

    interp_linear = LinearNDInterpolator(ground_xy, ground_z)
    result = interp_linear(query_xy)

    nan_mask = np.isnan(result)
    if np.any(nan_mask):
        interp_nearest = NearestNDInterpolator(ground_xy, ground_z)
        result[nan_mask] = interp_nearest(query_xy[nan_mask])

    return result


def remove_superstructure_outliers(heights, gap_factor=3.0,
                                    min_gap_meters=1.5):
    """
    Usuwa kominy, anteny i inne nadbudówki z tablicy wysokości budynku.

    METODA: Detekcja gapów (przerw) w posortowanym rozkładzie wysokości.

    Kalenica dachu czterospadowego jest ciągłym przedłużeniem połaci –
    przejście od połaci do kalenicy jest płynne, bez skoku.
    Komin/antena natomiast tworzy wyraźną PRZERWĘ (gap) w rozkładzie:
    jest grupa punktów dachu, potem przerwa, potem izolowane wysokie punkty.

    Algorytm:
    1. Sortuje wysokości malejąco
    2. Oblicza różnice między kolejnymi wartościami (gaps)
    3. Szuka gapów znacząco większych niż typowy gap
       (> gap_factor × mediana gapów ORAZ > min_gap_meters)
    4. Punkty powyżej pierwszego takiego gapu to nadbudówki → odrzuca
    5. Jeśli nie ma żadnego dużego gapu → nic nie odrzuca

    Dzięki temu kalenica (ciągła dystrybucja) zostaje zachowana,
    a kominy (izolowane skoki) są odrzucane.
    """
    if len(heights) < 5:
        return heights

    sorted_h = np.sort(heights)[::-1]  # malejąco
    gaps = np.abs(np.diff(sorted_h))   # różnice między kolejnymi

    if len(gaps) == 0:
        return heights

    median_gap = np.median(gaps)
    if median_gap < 0.001:
        median_gap = 0.001  # zabezpieczenie przed dzieleniem przez 0

    # Szukaj pierwszego gapu który jest:
    #  - gap_factor × większy niż typowy gap (relatywny)
    #  - ORAZ większy niż min_gap_meters (absolutny próg)
    # Oba warunki łącznie zapobiegają fałszywym detekcjom
    cut_idx = None
    for i, g in enumerate(gaps):
        if g > gap_factor * median_gap and g > min_gap_meters:
            # Znaleziono gap – ale tylko jeśli powyżej gapu jest MAŁO punktów
            # (< 15% ogółu). Jeśli dużo → to nie kominy, to zróżnicowany dach
            n_above = i + 1  # ile punktów jest powyżej tego gapu
            if n_above / len(heights) < 0.15:
                cut_idx = i + 1
                break

    if cut_idx is None:
        # Brak gapu → nic nie odrzucamy
        return heights

    # Próg odcięcia: wartość tuż poniżej gapu
    threshold = sorted_h[cut_idx]
    filtered = heights[heights <= sorted_h[cut_idx - 1]]
    # Zachowaj punkty od progu w dół
    filtered = heights[heights <= threshold + 0.01]

    return filtered if len(filtered) >= 3 else heights


def calculate_ridge_height(heights_clean):
    """
    Wyznacza wysokość głównej kalenicy z przefiltrowanych wysokości.

    Po usunięciu kominów/anten najwyższe punkty w zbiorze SĄ kalenicą.
    Bierzemy górne 5-15% punktów (percentyl 90-98) i liczymy ich średnią.

    Dla dachów czterospadowych: po filtracji gap-based kalenica jest
    zachowana, więc górne punkty to właśnie ona.
    Dla dachów płaskich: górne punkty to po prostu najwyższa partia dachu.
    """
    if len(heights_clean) == 0:
        return 0.0

    if len(heights_clean) < 10:
        return float(np.percentile(heights_clean, 95))

    # Górne punkty = kalenica (po filtracji kominów nie ma nad nią nic)
    p90 = np.percentile(heights_clean, 90)
    p98 = np.percentile(heights_clean, 98)

    ridge_points = heights_clean[(heights_clean >= p90) & (heights_clean <= p98)]

    if len(ridge_points) < 3:
        return float(np.percentile(heights_clean, 95))

    return float(np.mean(ridge_points))


def calculate_building_height_interpolated(roof_xy, roof_z,
                                            ground_xy, ground_z):
    """
    Oblicza wysokość jednego budynku:
    1. Interpoluje DTM pod każdym punktem dachu
    2. Odejmuje punkt po punkcie
    3. Filtruje kominy/anteny
    4. Wyznacza kalenicę
    """
    empty = {
        'wysokosc': 0.0, 'wysokosc_mediana': 0.0,
        'n_roof': len(roof_z), 'n_ground': len(ground_z),
        'n_outliers': 0, 'method': 'no_data'
    }

    if len(roof_z) < 3:
        empty['method'] = 'insufficient_roof_points'
        return empty

    if len(ground_z) < 1:
        empty['method'] = 'no_ground_points'
        return empty

    # Krok 1: interpolacja terenu
    ground_z_interp = interpolate_ground_surface(ground_xy, ground_z, roof_xy)

    valid = ~np.isnan(ground_z_interp)
    if np.sum(valid) < 3:
        per_point = roof_z - np.median(ground_z)
        method = 'fallback_median_ground'
    else:
        per_point = roof_z[valid] - ground_z_interp[valid]
        method = 'interpolated_dtm'

    # Odrzuć ujemne (punkt dachu poniżej terenu = błąd danych)
    per_point = per_point[per_point > 0.5]
    if len(per_point) < 3:
        empty['method'] = 'all_heights_invalid'
        return empty

    # Krok 2: filtracja kominów/anten
    n_before = len(per_point)
    clean = remove_superstructure_outliers(per_point)
    n_outliers = n_before - len(clean)
    if len(clean) < 3:
        clean = per_point

    # Krok 3: kalenica
    ridge = calculate_ridge_height(clean)
    med = float(np.median(clean))

    return {
        'wysokosc': round(ridge, 2),
        'wysokosc_mediana': round(med, 2),
        'n_roof': len(roof_z),
        'n_ground': len(ground_z),
        'n_outliers': n_outliers,
        'method': method
    }


def add_height_to_buildings_layer():
    """
    Główna funkcja – oblicza wysokości budynków z interpolacją DTM
    i zapisuje do warstwy budynków.

    Wymaga tych samych warstw wejściowych co stara wersja:
    - 'budynki_z_szer_elew_front'          (poligony – cel)
    - 'Classification_2_bufor_with_IDs'    (punkty gruntu)
    - 'Classification_6_with_IDs'          (punkty dachów)
    """
    try:
        # === WARSTWA DOCELOWA ===
        target_layer = QgsProject.instance().mapLayersByName(
            'budynki_z_szer_elew_front')[0]

        field_names = [f.name() for f in target_layer.fields()]
        new_fields = []
        if 'wysokosc' not in field_names:
            new_fields.append(QgsField('wysokosc', QVariant.Double))
        if 'wys_mediana' not in field_names:
            new_fields.append(QgsField('wys_mediana', QVariant.Double))
        if 'wys_metoda' not in field_names:
            new_fields.append(QgsField('wys_metoda', QVariant.String))
        if 'wys_outliers' not in field_names:
            new_fields.append(QgsField('wys_outliers', QVariant.Int))

        if new_fields:
            target_layer.dataProvider().addAttributes(new_fields)
            target_layer.updateFields()
            print(f"Dodano {len(new_fields)} nowych kolumn do warstwy budynków")
        else:
            print("Kolumny wysokości już istnieją – będą aktualizowane")

        # === WARSTWA GRUNTU ===
        try:
            ground_layer = QgsProject.instance().mapLayersByName(
                'Classification_2_bufor_with_IDs')[0]
            print(f"✅ Warstwa gruntu: {ground_layer.name()} "
                  f"({ground_layer.featureCount()} pkt)")
        except IndexError:
            print("❌ Nie znaleziono warstwy 'Classification_2_bufor_with_IDs'")
            return False

        ground_field_names = [f.name() for f in ground_layer.fields()]
        ground_has_building_id = 'ID_BUDYNKU' in ground_field_names
        ground_group_key = 'ID_BUDYNKU' if ground_has_building_id else 'ID_DZIALKI'
        has_xy_fields = ('X' in ground_field_names and 'Y' in ground_field_names)

        print(f"ℹ️  Grunt grupowany po: {ground_group_key}")
        print(f"ℹ️  Grunt ma pola X/Y: {has_xy_fields}")

        ground_data = []
        for i, feat in enumerate(ground_layer.getFeatures()):
            z = feat['Z']
            grp = feat[ground_group_key]
            if z is None or grp is None:
                continue

            if has_xy_fields:
                x, y = feat['X'], feat['Y']
            else:
                pt = feat.geometry().asPoint()
                x, y = pt.x(), pt.y()

            ground_data.append({
                'X': float(x), 'Y': float(y), 'Z': float(z),
                'GROUP_KEY': str(grp)
            })
            if (i + 1) % 50000 == 0:
                print(f"  Grunt: wczytano {i + 1}...")
                gc.collect()

        ground_df = pd.DataFrame(ground_data)
        del ground_data
        gc.collect()
        print(f"✅ Pobrano {len(ground_df)} punktów gruntu")
        print(f"   Zakres Z: {ground_df['Z'].min():.2f} – {ground_df['Z'].max():.2f}")

        # === WARSTWA DACHÓW ===
        try:
            roof_layer = QgsProject.instance().mapLayersByName(
                'Classification_6_with_IDs')[0]
            print(f"✅ Warstwa dachów: {roof_layer.name()} "
                  f"({roof_layer.featureCount()} pkt)")
        except IndexError:
            print("❌ Nie znaleziono warstwy 'Classification_6_with_IDs'")
            return False

        roof_field_names = [f.name() for f in roof_layer.fields()]
        roof_data = []
        for i, feat in enumerate(roof_layer.getFeatures()):
            z = feat['Z']
            id_bud = feat['ID_BUDYNKU']
            if z is None or id_bud is None:
                continue

            x = float(feat['X']) if 'X' in roof_field_names else feat.geometry().asPoint().x()
            y = float(feat['Y']) if 'Y' in roof_field_names else feat.geometry().asPoint().y()
            id_dz = feat['ID_DZIALKI'] if 'ID_DZIALKI' in roof_field_names else ''

            roof_data.append({
                'X': x, 'Y': y, 'Z': float(z),
                'ID_BUDYNKU': str(id_bud),
                'ID_DZIALKI': str(id_dz) if id_dz else ''
            })
            if (i + 1) % 50000 == 0:
                print(f"  Dachy: wczytano {i + 1}...")
                gc.collect()

        roof_df = pd.DataFrame(roof_data)
        del roof_data
        gc.collect()
        print(f"✅ Pobrano {len(roof_df)} punktów dachów")
        print(f"   Zakres Z: {roof_df['Z'].min():.2f} – {roof_df['Z'].max():.2f}")

        # === OBLICZANIE WYSOKOŚCI PER BUDYNEK ===
        print("\n🔄 Obliczam wysokości budynków (interpolacja DTM)...")

        ground_groups = ground_df.groupby('GROUP_KEY')

        # Lookup: budynek → klucz grupy gruntu
        if not ground_has_building_id:
            bud_to_group = dict(zip(roof_df['ID_BUDYNKU'], roof_df['ID_DZIALKI']))
        else:
            bud_to_group = None

        roof_groups = roof_df.groupby('ID_BUDYNKU')
        height_results = {}
        processed = 0

        for building_id, roof_grp in roof_groups:
            r_xy = roof_grp[['X', 'Y']].values
            r_z = roof_grp['Z'].values

            gkey = building_id if ground_has_building_id else (
                bud_to_group.get(building_id, ''))

            if gkey in ground_groups.groups:
                g_grp = ground_groups.get_group(gkey)
                g_xy = g_grp[['X', 'Y']].values
                g_z = g_grp['Z'].values
            else:
                g_xy = np.empty((0, 2))
                g_z = np.empty(0)

            height_results[building_id] = calculate_building_height_interpolated(
                r_xy, r_z, g_xy, g_z)

            processed += 1
            if processed % 20 == 0:
                print(f"  ⏳ Przetworzono {processed} budynków...")
                gc.collect()

        print(f"✅ Obliczono wysokości dla {len(height_results)} budynków")

        # Diagnostyka
        methods = {}
        for r in height_results.values():
            m = r['method']
            methods[m] = methods.get(m, 0) + 1
        print("\n📊 Statystyki metod:")
        for m, cnt in sorted(methods.items(), key=lambda x: -x[1]):
            print(f"   {m}: {cnt}")

        all_h = [r['wysokosc'] for r in height_results.values() if r['wysokosc'] > 0]
        if all_h:
            print("\n📏 Wysokości budynków:")
            print(f"   min={min(all_h):.2f}  max={max(all_h):.2f}  "
                  f"mediana={np.median(all_h):.2f}  średnia={np.mean(all_h):.2f}")

        # === ZAPIS DO WARSTWY ===
        target_layer.startEditing()

        fld = {name: target_layer.fields().indexFromName(name)
               for name in ['wysokosc', 'wys_mediana', 'wys_metoda',
                            'wys_outliers', 'ID_BUDYNKU']}

        if fld['wysokosc'] == -1 or fld['ID_BUDYNKU'] == -1:
            print("❌ Brak wymaganych pól w warstwie docelowej")
            return False

        updated = 0
        not_found = 0
        for feat in target_layer.getFeatures():
            bid = str(feat.attributes()[fld['ID_BUDYNKU']])
            if bid in height_results:
                r = height_results[bid]
                # rzutowanie na natywne typy (QGIS 4/Qt6 nie przyjmuje numpy)
                target_layer.changeAttributeValue(
                    feat.id(), fld['wysokosc'], float(r['wysokosc']))
                if fld.get('wys_mediana', -1) != -1:
                    target_layer.changeAttributeValue(
                        feat.id(), fld['wys_mediana'], float(r['wysokosc_mediana']))
                if fld.get('wys_metoda', -1) != -1:
                    target_layer.changeAttributeValue(
                        feat.id(), fld['wys_metoda'], str(r['method']))
                if fld.get('wys_outliers', -1) != -1:
                    target_layer.changeAttributeValue(
                        feat.id(), fld['wys_outliers'], int(r['n_outliers']))
                updated += 1
            else:
                not_found += 1

        target_layer.commitChanges()

        print(f"\n✅ Sukces! Zaktualizowano wysokość dla {updated} budynków")
        if not_found:
            print(f"⚠️ Nie znaleziono danych dla {not_found} budynków")

        target_layer.triggerRepaint()
        iface.layerTreeView().refreshLayerSymbology(target_layer.id())

        del ground_df, roof_df, height_results
        gc.collect()

        return True

    except Exception as e:
        import traceback
        print(f"❌ Błąd podczas dodawania wysokości: {str(e)}")
        print("Pełny traceback:")
        traceback.print_exc()
        return False


def przytnij_punkty_do_poligonow(nazwa_punktow, nazwa_maski, output_name):
    """Przycina punkty do poligonów"""
    warstwa_punktowa = QgsProject.instance().mapLayersByName(nazwa_punktow)[0]
    warstwa_poligonow = QgsProject.instance().mapLayersByName(nazwa_maski)[0]

    parametry = {
        'INPUT': warstwa_punktowa,
        'PREDICATE': [0],
        'INTERSECT': warstwa_poligonow,
        'OUTPUT': f"memory:{output_name}",
    }
    
    wynik = processing.run("native:extractbylocation", parametry)
    warstwa_przycieta = wynik['OUTPUT']
    QgsProject.instance().addMapLayer(warstwa_przycieta)
    

# ============= GŁÓWNY SKRYPT =============
print("🚀 Uruchamiam poprawiony skrypt z optymalizacjami...")
print("📋 Ustawienia optymalizacji:")
print(f"  MAX_POINTS_FOR_RANSAC: {MAX_POINTS_FOR_RANSAC}")
print(f"  MAX_POINTS_FOR_DBSCAN: {MAX_POINTS_FOR_DBSCAN}")
print("")
print("⚠️ JEŚLI DALEJ SĄ PROBLEMY Z PAMIĘCIĄ, ZMNIEJSZ TE WARTOŚCI!")
print("")

# PRZYGOTOWANIE PUNKTÓW    
# 1. BUFOR 5M WOKÓŁ KAŻDEGO BUDYNKU
warstwa_budynkow = QgsProject.instance().mapLayersByName("budynki_z_szer_elew_front")[0]
parametry = {
    'INPUT': warstwa_budynkow,
    'DISTANCE': 5,
    'SEGMENTS': 5,
    'END_CAP_STYLE': 0,
    'JOIN_STYLE': 0,
    'MITER_LIMIT': 2,
    'DISSOLVE': False,
    'SEPARATE_DISJOINT': False,
    'OUTPUT': 'memory:bufor_5m_budynki'
}
wynik = processing.run("native:buffer", parametry)
warstwa_bufora = wynik['OUTPUT']
QgsProject.instance().addMapLayer(warstwa_bufora)

# 2. RÓŻNICA SYMETRYCZNA
warstwa_bufora = QgsProject.instance().mapLayersByName("bufor_5m_budynki")[0]
warstwa_budynkow = QgsProject.instance().mapLayersByName("budynki_z_szer_elew_front")[0]
parametry = {
    'INPUT': warstwa_bufora,
    'OVERLAY': warstwa_budynkow,
    'OUTPUT': 'memory:roznica_symetryczna_bufor_vs_budynki'
}
wynik = processing.run("native:symmetricaldifference", parametry)
QgsProject.instance().addMapLayer(wynik['OUTPUT'])

# 3. PRZYCINA PUNKTY GRUNTU DO BUFORÓW WOKÓŁ BUDYNKÓW
przytnij_punkty_do_poligonow('Classification_2', 
                             'roznica_symetryczna_bufor_vs_budynki', 
                             "Classification_2_bufor")   
    
# 4. DOŁĄCZA ID_DZIALKI DO PUNKTÓW GRUNTU
wynik = processing.run("native:joinattributesbylocation", {
    'INPUT': QgsProject.instance().mapLayersByName("Classification_2_bufor")[0],
    'JOIN': QgsProject.instance().mapLayersByName("dzialki_ze_wskaznikami")[0],
    'PREDICATE': [0],
    'JOIN_FIELDS': ['ID_DZIALKI',],
    'METHOD': 0,
    'DISCARD_NONMATCHING': False,
    'OUTPUT': 'memory:Classification_2_bufor_with_IDs'
})
QgsProject.instance().addMapLayer(wynik['OUTPUT'])
print("✅ Gotowe: utworzono warstwę Classification_2_bufor_with_IDs z przypisanymi polami.")
zapis_do_gpkg("Classification_2_bufor_with_IDs")

# 5. PRZYCINA PUNKTY BUDYNKÓW
przytnij_punkty_do_poligonow('Classification_6', 
                             'budynki_z_szer_elew_front', 
                             "Classification_6_przyciete")   

# DODAJE ATRYBUTY BUDYNKÓW DO WARSTWY PUNKTOWEJ
wynik = processing.run("native:joinattributesbylocation", {
    'INPUT': QgsProject.instance().mapLayersByName("Classification_6_przyciete")[0],
    'JOIN': QgsProject.instance().mapLayersByName("budynki_z_szer_elew_front")[0],
    'PREDICATE': [0],
    'JOIN_FIELDS': ['ID_BUDYNKU', 'ID_DZIALKI'],
    'METHOD': 0,
    'DISCARD_NONMATCHING': False,
    'OUTPUT': 'memory:Classification_6_with_IDs'
})
QgsProject.instance().addMapLayer(wynik['OUTPUT'])
print("✅ Gotowe: utworzono warstwę Classification_6_with_IDs z przypisanymi polami.")

# OBLICZA WYSOKOŚCI I DOPISUJE DO WARSTWY BUDYNKÓW
print("📏 Obliczam wysokości budynków...")
add_height_to_buildings_layer()
gc.collect()  # Czyszczenie pamięci

# OBLICZANIE NACHYLENIA POŁACI DACHOWYCH
print("🏠 Rozpoczynam analizę nachyleń dachów z chmury punktów...")
process_buildings_roof_slopes(
    points_layer=QgsProject.instance().mapLayersByName('Classification_6_with_IDs')[0]
)
gc.collect()  # Czyszczenie pamięci

# ZAPISUJE DO PLIKU WARSTWĘ PUNKTÓW Z ID
layer = QgsProject.instance().mapLayersByName('Classification_6_with_IDs')[0]
if layer:
    print(f"💾 Zapisuję warstwę: {layer.name()}")
else:
    print("❌ Brak aktywnej warstwy")
            
layer_name = layer.name()
zapis_do_gpkg(layer_name)

# Czyszczenie warstw tymczasowych
print("🧹 Czyszczenie warstw tymczasowych...")
remove_memory_layers()

# ===== NOWA SEKCJA: AUTOMATYCZNA KLASYFIKACJA =====
# STYLIZACJA Z AUTOMATYCZNĄ KLASYFIKACJĄ KTÓRA NIE WYMAGA KLIKANIA "KLASYFIKUJ"
print("\n🎨 STOSOWANIE AUTOMATYCZNEJ KLASYFIKACJI WARSTWY...")
print("   (nie będzie potrzebne otwieranie właściwości i klikanie 'Klasyfikuj')\n")

# Wczytaj warstwę z pliku GPKG jeśli jeszcze nie ma w projekcie
layers = QgsProject.instance().mapLayersByName("Classification_6_with_IDs")
if not layers:
    # Spróbuj wczytać z pliku
    project_path = QgsProject.instance().fileName()
    if project_path:
        project_dir = Path(project_path).parent
        gpkg_path = project_dir / "Classification_6_with_IDs.gpkg"
        if gpkg_path.exists():
            vlayer = QgsVectorLayer(str(gpkg_path), "Classification_6_with_IDs", "ogr")
            if vlayer.isValid():
                QgsProject.instance().addMapLayer(vlayer)
                print("📂 Wczytano warstwę z pliku GPKG")

# Zastosuj automatyczną klasyfikację
apply_optimized_point_classification("Classification_6_with_IDs")

print("\n✅ SKRYPT ZAKOŃCZONY POMYŚLNIE!")
print("📊 Warstwa Classification_6_with_IDs jest teraz w pełni sklasyfikowana")
print("   i gotowa do wyświetlenia bez dalszych akcji!")
print("\n💡 Wskazówki:")
print("   - Jeśli nadal występują problemy z pamięcią, zmniejsz wartości")
print("     MAX_POINTS_FOR_RANSAC i MAX_POINTS_FOR_DBSCAN na początku skryptu")
print("   - Klasyfikacja jest już zastosowana - nie ma potrzeby otwierania")
print("     właściwości warstwy i klikania 'Klasyfikuj'")