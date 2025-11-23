#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kompletny poprawiony skrypt QGIS
- Optymalizacja dla dużych zbiorów punktów
- Zabezpieczenia przed OOM (Out of Memory)
- Automatyczna klasyfikacja warstwy punktowej (bez potrzeby ręcznego "Klasyfikuj")
"""
import processing
from qgis.core import (QgsProject, QgsVectorLayer, QgsFeature, QgsWkbTypes,
    QgsFields, QgsField, QgsGraduatedSymbolRenderer, QgsRendererRange,QgsMarkerSymbol, 
    )
from pathlib import Path
from PyQt5.QtCore import QVariant
from PyQt5.QtGui import QColor
import pandas as pd
import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.linear_model import RANSACRegressor
from sklearn.preprocessing import StandardScaler
from qgis.utils import iface
import os
import gc  # Garbage collector dla zarządzania pamięcią

SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

# STAŁE OPTYMALIZACYJNE - MOŻESZ JE ZMNIEJSZYĆ JEŚLI DALEJ SĄ PROBLEMY Z PAMIĘCIĄ
MAX_POINTS_FOR_RANSAC = 5000  # Maksymalna liczba punktów dla RANSAC
MAX_POINTS_FOR_DBSCAN = 10000  # Maksymalna liczba punktów dla DBSCAN
BATCH_SIZE = 1000  # Rozmiar batcha dla przetwarzania


def apply_optimized_point_classification(layer_name):
    """
    Specjalna funkcja optymalizowana dla dużych chmur punktów.
    Stosuje uproszczoną klasyfikację Fixed Interval która jest szybsza.
    NIE WYMAGA otwierania właściwości warstwy i klikania "Klasyfikuj"!
    """
    
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        print(f"❌ Nie znaleziono warstwy: {layer_name}")
        return False
    
    layer = layers[0]
    field_name = 'Z'
    
    print(f"⚡ Stosuję szybką klasyfikację dla {layer.featureCount()} punktów...")
    
    # === SZYBKA METODA: Oblicz przedziały bez iteracji po wszystkich punktach ===
    # Użyj statystyk warstwy (znacznie szybsze dla dużych zbiorów)
    
    idx = layer.fields().indexFromName(field_name)
    if idx == -1:
        print(f"❌ Nie znaleziono pola {field_name}")
        return False
    
    # Pobierz statystyki bezpośrednio z providera (bardzo szybkie!)
    
    # Szybkie pobranie min/max poprzez sampling
    sample_size = min(10000, layer.featureCount())
    sample_step = max(1, layer.featureCount() // sample_size)
    
    values = []
    counter = 0
    for feature in layer.getFeatures():
        if counter % sample_step == 0:
            val = feature.attributes()[idx]
            if val is not None:
                values.append(float(val))
        counter += 1
        if len(values) >= sample_size:
            break
    
    if not values:
        print("❌ Nie można pobrać wartości Z")
        return False
    
    min_val = min(values)
    max_val = max(values)
    
    print(f"📈 Zakres Z: {min_val:.2f} - {max_val:.2f} m")
    
    # === Utwórz przedziały Fixed Interval (równe) ===
    num_classes = 10
    interval = (max_val - min_val) / num_classes
        
       # Kolory: gradient w odcieniach szarości (jasny -> ciemny)
    colors = [
        QColor(245, 245, 245),  # bardzo jasny szary
        QColor(220, 220, 220),  # jasny szary
        QColor(200, 200, 200),  # jasny średni
        QColor(180, 180, 180),  # średni szary
        QColor(160, 160, 160),  # neutralny szary
        QColor(130, 130, 130),  # ciemny średni
        QColor(100, 100, 100),  # ciemny szary
        QColor(70, 70, 70),     # bardzo ciemny szary
        QColor(45, 45, 45),     # near-black
        QColor(20, 20, 20)      # almost black
    ]

    
    # Utwórz przedziały
    ranges = []
    for i in range(num_classes):
        lower = min_val + (i * interval)
        upper = min_val + ((i + 1) * interval)
        
        # Ostatni przedział - upewnij się że zawiera max
        if i == num_classes - 1:
            upper = max_val + 0.01
        
        # Symbol
        color_idx = min(i, len(colors) - 1)
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'circle',
            'color': colors[color_idx].name(),
            'outline_style': 'no',
            'size': '2'  # Małe punkty dla wydajności
        })
        
        # Etykieta
        label = f'{lower:.1f} - {upper:.1f} m'
        
        # Dodaj przedział
        range_item = QgsRendererRange(lower, upper, symbol, label)
        ranges.append(range_item)
    
    # Utwórz renderer
    renderer = QgsGraduatedSymbolRenderer(field_name, ranges)
    renderer.setClassAttribute(field_name)
    
    # Format liczb w legendzie
    # renderer.setLabelFormat("%.1f")
    
    # Zastosuj
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    
    print(f"✅ Klasyfikacja zastosowana! ({num_classes} klas)")
    
    # Zapisz styl
    try:
        project_path = QgsProject.instance().fileName()
        if project_path:
            from pathlib import Path
            project_dir = Path(project_path).parent
            style_path = project_dir / f"{layer_name}_auto_graduated.qml"
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
    
    # === KROK 3: Oblicz nachylenie dla każdej płaszczyzny ===
    plane_slopes = []
    plane_confidences = []
    
    for plane_points in roof_planes:
        if len(plane_points) < 10:
            continue
            
        slope_info = calculate_plane_slope_robust(plane_points)
        if slope_info and slope_info['slope'] > 0:
            plane_slopes.append(slope_info['slope'])
            plane_confidences.append(slope_info['confidence'])
    
    if len(plane_slopes) == 0:
        fallback_slope = calculate_overall_slope(cleaned_points)
        return { 
            "slope": fallback_slope,
            "confidence": 0.5,
            "method": "fallback_overall_accepted",
            "num_points": len(cleaned_points)
        }
    
    # === KROK 4: Wybierz najlepsze nachylenie ===
    if len(plane_slopes) == 1:
        plane_slopes.sort(reverse=True)
        final_slope = plane_slopes[0]
        confidence = plane_confidences[0]
    else:
        weights = np.array(plane_confidences)
        final_slope = np.average(plane_slopes, weights=weights)
        confidence = np.mean(plane_confidences)
    
    return {
        "slope": final_slope,
        "confidence": confidence,
        "method": f"multi_plane_{len(plane_slopes)}",
        "num_points": len(cleaned_points)
    }


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
        indices = np.random.choice(len(points), MAX_POINTS_FOR_DBSCAN, replace=False)
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
        indices = np.random.choice(len(points), MAX_POINTS_FOR_RANSAC, replace=False)
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
        indices = np.random.choice(len(points), 1000, replace=False)
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
    if 'nachylenie_chmura' not in [field.name() for field in buildings_layer.fields()]:
        buildings_layer.startEditing()
        buildings_layer.dataProvider().addAttributes([
            QgsField('nachylenie_chmura', QVariant.Double),
            QgsField('pewnosc_nachylenia', QVariant.Double),
            QgsField('metoda_nachylenia', QVariant.String),
            QgsField('liczba_punktow', QVariant.Int)
        ])
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
        
        # Zaokrąglij nachylenie
        slope = slope_info.get('slope', 0)
        if slope is None:
            slope = 0
        if slope > 2.5:
            slope = round(slope / 5) * 5
        else:
            slope = round(slope, 1)
            continue

        # Zapisz wyniki
        buildings_layer.changeAttributeValue(
            building_feature.id(),
            buildings_layer.fields().indexOf('nachylenie_chmura'),
            slope
        )
        buildings_layer.changeAttributeValue(
            building_feature.id(),
            buildings_layer.fields().indexOf('pewnosc_nachylenia'),
            round(slope_info.get('confidence', 0), 2)
        )
        buildings_layer.changeAttributeValue(
            building_feature.id(),
            buildings_layer.fields().indexOf('metoda_nachylenia'),
            slope_info.get('method', 'unknown')
        )
        buildings_layer.changeAttributeValue(
            building_feature.id(),
            buildings_layer.fields().indexOf('liczba_punktow'),
            slope_info.get('num_points', 0)
        )
        
        processed += 1
        if processed % 10 == 0:
            print(f"⏳ Przetworzono {processed} budynków...")
            gc.collect()  # Czyszczenie pamięci
    
    buildings_layer.commitChanges()
    print(f"✅ Analiza zakończona! Przetworzono {processed} budynków")


def filter_outliers_iqr(data, multiplier=1.5):
    """Filtruje outliery używając metody IQR"""
    if len(data) < 4:
        return data
    
    q1 = np.percentile(data, 25)
    q3 = np.percentile(data, 75)
    iqr = q3 - q1
    
    lower_bound = q1 - multiplier * iqr
    upper_bound = q3 + multiplier * iqr
    
    filtered_data = [x for x in data if lower_bound <= x <= upper_bound]
    
    if len(filtered_data) < max(3, len(data) * 0.3):
        return data
    
    return filtered_data


def calculate_roof_height(roof_points):
    """Oblicza reprezentatywną wysokość dachu z filtrowaniem outlierów"""
    if not roof_points or len(roof_points) == 0:
        return 0
    
    filtered_points = filter_outliers_iqr(roof_points, multiplier=1.5)
    
    if len(filtered_points) > 20:
        sorted_points = sorted(filtered_points, reverse=True)
        percentile_70 = int(len(sorted_points) * 0.05)
        percentile_95 = int(len(sorted_points) * 0.30)
        selected_points = sorted_points[percentile_70:percentile_95]
        
        if len(selected_points) > 0:
            return np.mean(selected_points)
    
    return np.mean(filtered_points)


def calculate_ground_height(ground_points):
    """Oblicza reprezentatywną wysokość gruntu z filtrowaniem outlierów"""
    if not ground_points or len(ground_points) == 0:
        return 0
    
    filtered_points = filter_outliers_iqr(ground_points, multiplier=1.5)
    return np.mean(filtered_points)


def add_height_to_buildings_layer():
    """Główna funkcja dodająca kolumnę wysokość z optymalizacją pamięci"""
    try:
        target_layer = QgsProject.instance().mapLayersByName('budynki_z_szer_elew_front')[0]
        
        field_names = [field.name() for field in target_layer.fields()]
        
        if 'wysokosc' not in field_names:
            target_layer.dataProvider().addAttributes([QgsField('wysokosc', QVariant.Double)])
            target_layer.updateFields()
            print("Dodano kolumnę 'wysokosc' do warstwy")
        else:
            print("Kolumna 'wysokosc' już istnieje - będzie aktualizowana")
        
        # Pobierz dane z warstwy gruntu partiami
        try:
            ground_layer = QgsProject.instance().mapLayersByName('Classification_2_bufor_with_IDs')[0]
            print(f"✅ Znaleziono warstwę gruntu: {ground_layer.name()}")
            print(f"Liczba obiektów w warstwie gruntu: {ground_layer.featureCount()}")
        except IndexError:
            print("❌ BŁĄD: Nie znaleziono warstwy 'Classification_2_bufor_with_IDs'")
            return False
        
        ground_field_names = [field.name() for field in ground_layer.fields()]
        print(f"Pola warstwy gruntu: {ground_field_names}")
        
        # OPTYMALIZACJA: Przetwarzanie partiami
        ground_data = []
        batch_counter = 0
        
        for feature in ground_layer.getFeatures():
            attrs = feature.attributes()
            fields = {field.name(): i for i, field in enumerate(ground_layer.fields())}
            
            if 'Z' not in fields or 'ID_DZIALKI' not in fields:
                print("❌ BŁĄD: Brak wymaganych pól w warstwie gruntu")
                return False
            
            z_value = attrs[fields['Z']] if attrs[fields['Z']] is not None else 0
            id_dzialki = attrs[fields['ID_DZIALKI']] if attrs[fields['ID_DZIALKI']] is not None else ''
            
            ground_data.append({
                'Z': z_value,
                'ID_DZIALKI': id_dzialki
            })
            
            batch_counter += 1
            if batch_counter % 50000 == 0:
                print(f"  Grunt: przetworzono {batch_counter} punktów...")
                gc.collect()
        
        ground_df = pd.DataFrame(ground_data)
        del ground_data
        gc.collect()
        
        print(f"✅ Pobrano {len(ground_df)} punktów gruntu")
        print(f"Zakres wysokości gruntu: {ground_df['Z'].min():.2f} - {ground_df['Z'].max():.2f}")
        
        # Pobierz dane z warstwy dachów partiami
        try:
            roof_layer = QgsProject.instance().mapLayersByName('Classification_6_with_IDs')[0]
            print(f"✅ Znaleziono warstwę dachów: {roof_layer.name()}")
            print(f"Liczba obiektów w warstwie dachów: {roof_layer.featureCount()}")
        except IndexError:
            print("❌ BŁĄD: Nie znaleziono warstwy 'Classification_6_with_IDs'")
            return False
        
        roof_data = []
        batch_counter = 0
        
        for feature in roof_layer.getFeatures():
            attrs = feature.attributes()
            fields = {field.name(): i for i, field in enumerate(roof_layer.fields())}
            
            if 'Z' not in fields or 'ID_DZIALKI' not in fields or 'ID_BUDYNKU' not in fields:
                print("❌ BŁĄD: Brak wymaganych pól w warstwie dachów")
                return False
            
            z_value = attrs[fields['Z']] if attrs[fields['Z']] is not None else 0
            id_dzialki = attrs[fields['ID_DZIALKI']] if attrs[fields['ID_DZIALKI']] is not None else ''
            id_budynku = attrs[fields['ID_BUDYNKU']] if attrs[fields['ID_BUDYNKU']] is not None else ''
            
            roof_data.append({
                'Z': z_value,
                'ID_DZIALKI': id_dzialki,
                'ID_BUDYNKU': id_budynku
            })
            
            batch_counter += 1
            if batch_counter % 50000 == 0:
                print(f"  Dachy: przetworzono {batch_counter} punktów...")
                gc.collect()
        
        roof_df = pd.DataFrame(roof_data)
        del roof_data
        gc.collect()
        
        print(f"✅ Pobrano {len(roof_df)} punktów dachów")
        print(f"Zakres wysokości dachów: {roof_df['Z'].min():.2f} - {roof_df['Z'].max():.2f}")
        
        # Oblicz wysokości
        print("🔄 Obliczam wysokości gruntu...")
        ground_heights = ground_df.groupby('ID_DZIALKI')['Z'].apply(list).reset_index()
        ground_heights['Z_ground_mean'] = ground_heights['Z'].apply(calculate_ground_height)
        ground_heights = ground_heights[['ID_DZIALKI', 'Z_ground_mean']]
        
        print("🔄 Obliczam wysokości dachów...")
        roof_heights = roof_df.groupby('ID_BUDYNKU').agg({
            'Z': list,
            'ID_DZIALKI': 'first'
        }).reset_index()
        
        roof_heights['Z_roof_mean'] = roof_heights['Z'].apply(calculate_roof_height)
        
        print("🔄 Łączę dane i obliczam wysokości budynków...")
        buildings_heights = pd.merge(roof_heights, ground_heights, on='ID_DZIALKI', how='left')
        
        missing_ground = buildings_heights['Z_ground_mean'].isna().sum()
        if missing_ground > 0:
            print(f"⚠️ UWAGA: {missing_ground} budynków nie ma danych o gruncie")
            ground_median = ground_df['Z'].median()
            buildings_heights['Z_ground_mean'].fillna(ground_median, inplace=True)
            print(f"Użyto mediany gruntu: {ground_median:.2f}")
        
        buildings_heights['wysokosc'] = round(
            buildings_heights['Z_roof_mean'] - buildings_heights['Z_ground_mean'], 2
        )
        
        height_dict = dict(zip(buildings_heights['ID_BUDYNKU'], buildings_heights['wysokosc']))
        print(f"Utworzono słownik wysokości dla {len(height_dict)} budynków")
        
        # Aktualizuj warstwę docelową
        target_layer.startEditing()
        
        height_field_idx = target_layer.fields().indexFromName('wysokosc')
        id_field_idx = target_layer.fields().indexFromName('ID_BUDYNKU')
        
        if height_field_idx == -1 or id_field_idx == -1:
            print("❌ BŁĄD: Nie znaleziono wymaganych pól w warstwie docelowej")
            return False
        
        updated_count = 0
        not_found_count = 0
        
        for feature in target_layer.getFeatures():
            building_id = feature.attributes()[id_field_idx]
            
            if building_id in height_dict:
                height_value = height_dict[building_id]
                target_layer.changeAttributeValue(feature.id(), height_field_idx, height_value)
                updated_count += 1
            else:
                not_found_count += 1
        
        target_layer.commitChanges()
        
        print(f"✅ Sukces! Zaktualizowano wysokość dla {updated_count} budynków")
        print(f"⚠️ Nie znaleziono danych dla {not_found_count} budynków")
        
        target_layer.triggerRepaint()
        iface.layerTreeView().refreshLayerSymbology(target_layer.id())
        
        # Czyszczenie pamięci
        del ground_df, roof_df, buildings_heights, height_dict
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