#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
import processing
import os
from qgis.core import (QgsProject, QgsField, QgsVectorLayer)
from PyQt5.QtCore import QVariant
import warnings
warnings.filterwarnings('ignore')
import torch
import torch.nn as nn
import pickle
import math
from collections import defaultdict

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

torch.set_num_threads(4)

# === Parametry modelu ===
INPUT_FEATURES = ['Z', 'Intensity', 'ReturnNumber', 'NumberOfReturns', 'Red', 'Green', 'Blue']
MODEL_PATH = os.path.join(SCRIPTS_PATH, "best_hex_model.pth")
SCALER_PATH = os.path.join(SCRIPTS_PATH, "scaler_hex.pkl")
HEX_SIZE = 1.0


# === Model heksagonalny ===
class HexTerrainNet(nn.Module):
    def __init__(self, input_dim, hidden_dim=128, output_dim=5):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.BatchNorm1d(hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim // 2, hidden_dim // 4),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim // 4, output_dim)
        )
    
    def forward(self, x):
        return self.net(x)


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
    hex_groups = defaultdict(list)
    print("Grupowanie punktów w heksagony...")
    for idx, row in points_data.iterrows():
        hex_coord = hex_grid_coordinates(row['X'], row['Y'], HEX_SIZE)
        hex_groups[hex_coord].append(row)
    print(f"Utworzono {len(hex_groups)} heksagonów z {len(points_data)} punktów")
    
    hex_features = []
    hex_coords = []
    
    for hex_coord, points in hex_groups.items():
        if len(points) < 3:
            continue
        points_df = pd.DataFrame(points)
        features = []
        
        for feature in INPUT_FEATURES:
            values = points_df[feature].values
            if len(values) > 0:
                features.extend([
                    np.mean(values), np.std(values) if len(values) > 1 else 0.0,
                    np.min(values), np.max(values),
                    np.percentile(values, 25), np.percentile(values, 75),
                ])
            else:
                features.extend([0.0] * 6)
        
        features.extend([
            len(points),
            points_df['Z'].max() - points_df['Z'].min(),
            np.std(points_df['Z']),
        ])
        
        if 'ReturnNumber' in points_df.columns and 'NumberOfReturns' in points_df.columns:
            first_returns = (points_df['ReturnNumber'] == 1).sum()
            features.append(first_returns / len(points))
            last_returns = (points_df['ReturnNumber'] == points_df['NumberOfReturns']).sum()
            features.append(last_returns / len(points))
            features.append(points_df['NumberOfReturns'].mean())
        
        if all(col in points_df.columns for col in ['Red', 'Green', 'Blue']):
            ndvi_like = (points_df['Green'] - points_df['Red']) / (points_df['Green'] + points_df['Red'] + 1e-8)
            features.extend([np.mean(ndvi_like), np.std(ndvi_like)])
            brightness = (points_df['Red'] + points_df['Green'] + points_df['Blue']) / 3
            features.extend([np.mean(brightness), np.std(brightness)])
        
        hex_features.append(features)
        hex_coords.append(hex_coord)
    
    return np.array(hex_features), hex_coords, hex_groups


def map_hex_predictions_to_points(hex_predictions, hex_coords, hex_groups, original_points):
    point_predictions = np.zeros(len(original_points))
    for hex_coord, prediction in zip(hex_coords, hex_predictions):
        if hex_coord in hex_groups:
            for point in hex_groups[hex_coord]:
                point_idx = point.name if hasattr(point, 'name') else point['original_index']
                if point_idx < len(point_predictions):
                    point_predictions[point_idx] = prediction
    return point_predictions


class QGISHexLidarPredictor:
    def __init__(self):
        self.model = None
        self.scaler = None
        self.hex_size = HEX_SIZE
        self.input_dim = None
        
    def load_model(self, model_path, scaler_path):
        try:
            checkpoint = torch.load(model_path, map_location='cpu', weights_only=False)
            self.input_dim = checkpoint.get('input_dim', 52)
            num_classes = checkpoint.get('num_classes', 5)
            self.hex_size = checkpoint.get('hex_size', HEX_SIZE)
            self.model = HexTerrainNet(input_dim=self.input_dim, output_dim=num_classes)
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.model.eval()
            with open(scaler_path, 'rb') as f:
                self.scaler = pickle.load(f)
            print(f"Model załadowany: input_dim={self.input_dim}, output_dim={num_classes}")
            return True
        except Exception as e:
            print(f"Błąd ładowania modelu: {e}")
            return False
    
    def predict_points(self, points_df):
        try:
            points_df = points_df.copy()
            points_df['original_index'] = range(len(points_df))
            X_hex, hex_coords, hex_groups = create_hexagon_features(points_df)
            if len(X_hex) == 0:
                print("Brak heksagonów do predykcji!")
                return np.zeros(len(points_df))
            print(f"Stworzono {len(X_hex)} heksagonów o wymiarach {X_hex.shape}")
            X_scaled = self.scaler.transform(X_hex)
            predictions = []
            with torch.no_grad():
                for i in range(0, len(X_scaled), 64):
                    batch = X_scaled[i:i+64]
                    X_tensor = torch.tensor(batch, dtype=torch.float32)
                    logits = self.model(X_tensor)
                    batch_preds = torch.argmax(logits, dim=1).numpy()
                    predictions.extend(batch_preds)
            predictions = np.array(predictions)
            return map_hex_predictions_to_points(predictions, hex_coords, hex_groups, points_df)
        except Exception as e:
            print(f"Błąd predykcji: {e}")
            return np.zeros(len(points_df))


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
        data.append(f.attributes())
    return pd.DataFrame(data, columns=[field.name() for field in layer.fields()])


def wczytaj_csv_do_qgis(sciezka_csv, nazwa_kolumny_x='X', nazwa_kolumny_y='Y', 
                        separator=',', crs_kod=None, nazwa_warstwy=None, 
                        kolumny_int=['predicted_label']):
    if crs_kod is None:
        crs_kod = project_crs
    if not os.path.exists(sciezka_csv):
        print(f"Błąd: Plik {sciezka_csv} nie istnieje!")
        return None
    if nazwa_warstwy is None:
        nazwa_warstwy = os.path.splitext(os.path.basename(sciezka_csv))[0]
    
    # Konwersja CRS na string
    if hasattr(crs_kod, 'authid'):
        crs_string = crs_kod.authid()
    else:
        crs_string = str(crs_kod)
    
    uri = f"file:///{sciezka_csv}?delimiter={separator}&xField={nazwa_kolumny_x}&yField={nazwa_kolumny_y}&crs={crs_string}&detectTypes=no"
    warstwa = QgsVectorLayer(uri, nazwa_warstwy, "delimitedtext")
    
    if not warstwa.isValid():
        print(f"Błąd: Nie można wczytać warstwy z pliku {sciezka_csv}")
        return None
    
    safe_add_layer_to_project(warstwa)
    if kolumny_int:
        konwertuj_kolumny_na_int(warstwa, kolumny_int)
    print(f"Wczytano warstwę: {nazwa_warstwy} ({warstwa.featureCount()} obiektów)")
    return warstwa


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
    print("\n🔧 ROZPOCZYNAM PRZYCINANIE...")
    if not diagnose_layers(punkt_layer, mask_layer):
        return None
    
    # Metoda 1: Extract by location
    try:
        parametry = {
            'INPUT': punkt_layer,
            'PREDICATE': [0],
            'INTERSECT': mask_layer,
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
    
    # Metoda 2: Z buforem
    try:
        parametry_buffer = {
            'INPUT': mask_layer,
            'DISTANCE': 1,
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
    if not predictor.load_model(MODEL_PATH, SCALER_PATH):
        print("❌ Nie można wczytać modelu!")
        return False
    
    predictions = predictor.predict_points(layer_df)
    
    # Statystyki
    unique, counts = np.unique(predictions, return_counts=True)
    print("\nRozkład predykcji:")
    for class_id, count in zip(unique, counts):
        percentage = (count / len(predictions)) * 100
        print(f"   Klasa {class_id}: {count:,} punktów ({percentage:.1f}%)")
    
    # Konwersja klas
    predictions_converted = predictions.copy()
    for i in range(len(predictions_converted)):
        if predictions_converted[i] in [2, 3]:
            predictions_converted[i] = 0
        elif predictions_converted[i] == 4:
            predictions_converted[i] = 1
    
    # Zapisz wyniki
    layer_df['predicted_label'] = predictions_converted
    layer_df.to_csv(output_csv, index=False)
    print(f"✅ Zapisano wyniki do: {output_csv}")
    
    # ⬅️ USUŃ WARSTWĘ MEMORY PO UŻYCIU!
    print("\n🧹 Usuwam warstwę tymczasową...")
    try:
        QgsProject.instance().removeMapLayer(warstwa_przycieta.id())
        print(f"✅ Usunięto warstwę tymczasową: {nazwa_warstwy_przyciete}")
    except Exception as e:
        print(f"⚠️ Nie udało się usunąć warstwy tymczasowej: {e}")
    
    # 3. Wczytaj warstwę wynikową
    print("\n🎯 KROK 3: Wczytywanie warstwy wynikowej...")
    
    # Usuń istniejącą warstwę
    existing_layers = QgsProject.instance().mapLayersByName(nazwa_warstwy_wynik)
    if existing_layers:
        for layer in existing_layers:
            QgsProject.instance().removeMapLayer(layer.id())
    
    result_layer = wczytaj_csv_do_qgis(
        output_csv, 
        nazwa_kolumny_x='X', 
        nazwa_kolumny_y='Y',
        separator=',', 
        crs_kod=project_crs,
        nazwa_warstwy=nazwa_warstwy_wynik,
        kolumny_int=['predicted_label']
    )
    
    if result_layer:
        # Aplikuj styl
        style_path = os.path.join(SCRIPTS_PATH, "style/punkty_PBC_new.qml")
        apply_qml_style_to_layer(nazwa_warstwy_wynik, style_path, show_messages=True)
        print(f"✅ Warstwa {nazwa_warstwy_wynik} utworzona pomyślnie!")
        return True
    else:
        print(f"❌ Błąd tworzenia warstwy {nazwa_warstwy_wynik}")
        return False

# === WYKONANIE ===
 # Predykcja 1: Działki zgodne z funkcją
run_terrain_prediction(
     nazwa_punktow='Classification_2',
     nazwa_maski='dzialki_zgodne_z_funkcja',
     nazwa_warstwy_przyciete='Classification_2_przyciete',
     nazwa_warstwy_wynik='punkty_pbc_wyniki_predykcji',
     output_csv_name='punkty_pbc_wyniki_predykcji.csv'
 )
 
 # Predykcja 2: Granica terenu
run_terrain_prediction(
     nazwa_punktow='Classification_2',
     nazwa_maski='granica_terenu',
     nazwa_warstwy_przyciete='Classification_2_przyciete_teren',
     nazwa_warstwy_wynik='punkty_pbc_wyniki_predykcji_teren_inwestycji',
     output_csv_name='punkty_pbc_wyniki_predykcji_teren_inwestycji.csv'
 )
 
print("\n🎉 WSZYSTKIE PREDYKCJE ZAKOŃCZONE!")