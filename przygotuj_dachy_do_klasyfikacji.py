#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep  9 05:12:18 2025

@author: adrian
"""
import pandas as pd
import numpy as np
from qgis.core import QgsProject
from pathlib import Path
from scipy.interpolate import griddata
import os
from PIL import Image
import json
import threading
import subprocess
import sys

project_path = QgsProject.instance().fileName()
project_directory = Path(project_path).parent
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))


def run_script_bg(script_path, args=None):
    """
    Uruchamia skrypt w tle z opcjonalnymi argumentami.
    Użycie: run_script_bg("ścieżka/do/skryptu.py", args=["/ścieżka/do/projektu.qgz"])
    """
    def run_in_thread():
        try:
            # Budowanie polecenia jako lista
            command = [sys.executable, script_path]
            if args:
                command.extend(args)

            result = subprocess.run(command,
                                    capture_output=True,
                                    text=True,
                                    cwd=os.path.dirname(script_path))
            
            print(f"Script finished with return code: {result.returncode}")
            if result.stdout:
                print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
        except Exception as e:
            print(f"Error running script: {e}")
    
    thread = threading.Thread(target=run_in_thread)
    thread.start()
    print(f"Script started in background: {script_path} with args: {args}")

    
    
def run_classifier():
    """Uruchom klasyfikator - ZMIEŃ ŚCIEŻKĘ!"""
    script_name = 'headless_classifier.py'
    script_path = os.path.join(SCRIPTS_PATH, script_name)
    run_script_bg(script_path, args=[project_path])
    
    
# Funkcja unitaryzacji zerowanej
def unitaryzacja_zerowana(group):
    """
    Wykonuje unitaryzację zerowaną dla kolumny Z w grupie
    Wzór: (Z - Z_min) / (Z_max - Z_min)
    """
    z_min = group['Z'].min()
    z_max = group['Z'].max()
    
    # Sprawdzenie czy istnieje różnica między min i max
    if z_max == z_min:
        # Jeśli wszystkie wartości Z są identyczne, przypisz 0
        group['Z_unitarized'] = 0.0
    else:
        # Unitaryzacja zerowana
        group['Z_unitarized'] = (group['Z'] - z_min) / (z_max - z_min)
    
    return group


def create_raster_for_building(building_data, building_id, resolution=128, method='linear'):
    """
    Tworzy raster dla jednego budynku - zoptymalizowany dla ML
    
    Parameters:
    building_data: DataFrame z danymi punktowymi dla jednego budynku
    building_id: ID budynku
    resolution: rozdzielczość rastera (rekomendowane: 64, 128, 256)
    method: metoda interpolacji ('linear', 'cubic', 'nearest')
    """
    
    # Wyodrębnienie współrzędnych i wartości
    x = building_data['X'].values
    y = building_data['Y'].values
    z = building_data['Z_unitarized'].values
    
    # Definicja siatki rastera
    x_min, x_max = x.min(), x.max()
    y_min, y_max = y.min(), y.max()
    
    # Sprawdzenie czy budynek ma wymiary (nie jest punktem)
    x_range = x_max - x_min
    y_range = y_max - y_min
    
    if x_range == 0 or y_range == 0:
        print(f"  Ostrzeżenie: Budynek {building_id} ma zerowe wymiary")
        # Dodaj minimalny margines
        margin = max(1.0, np.std(x) + np.std(y)) / 2
        x_min -= margin
        x_max += margin
        y_min -= margin
        y_max += margin
    else:
        # Dodanie marginesu (10% rozmiaru dla lepszego kontekstu)
        x_margin = x_range * 0.1
        y_margin = y_range * 0.1
        
        x_min -= x_margin
        x_max += x_margin
        y_min -= y_margin
        y_max += y_margin
    
    # Utworzenie kwadratowej siatki (ważne dla CNN)
    # Znajdź większy wymiar i zrób siatkę kwadratową
    max_range = max(x_max - x_min, y_max - y_min)
    
    # Wycentrowanie
    x_center = (x_min + x_max) / 2
    y_center = (y_min + y_max) / 2
    
    x_min = x_center - max_range / 2
    x_max = x_center + max_range / 2
    y_min = y_center - max_range / 2
    y_max = y_center + max_range / 2
    
    # Utworzenie siatki
    xi = np.linspace(x_min, x_max, resolution)
    yi = np.linspace(y_min, y_max, resolution)
    xi, yi = np.meshgrid(xi, yi)
    
    # Interpolacja wartości na siatkę
    try:
        zi = griddata((x, y), z, (xi, yi), method=method, fill_value=0)
        # Zamień NaN na 0
        zi = np.nan_to_num(zi, nan=0.0)
    except Exception as e:
        print(f"  Błąd interpolacji dla budynku {building_id}: {e}")
        # W przypadku problemów, użyj nearest
        zi = griddata((x, y), z, (xi, yi), method='nearest', fill_value=0)
        zi = np.nan_to_num(zi, nan=0.0)
    
    return zi

def save_raster_for_prediction(raster_data, building_id, output_dir, format='png'):
    """
    Zapisuje raster w formacie przygotowanym dla predykcji ML
    
    Parameters:
    raster_data: macierz numpy z danymi rastera
    building_id: ID budynku  
    output_dir: katalog wyjściowy
    format: format obrazu ('png', 'jpg', 'npy')
    """
    
    # Normalizacja do zakresu 0-255 dla obrazów
    raster_normalized = (raster_data * 255).astype(np.uint8)
    
    # Bezpieczna nazwa pliku
    # safe_id = str(building_id).replace('/', '_').replace('.', '_').replace(' ', '_')
    safe_id = str(building_id).replace('/', '_').replace(' ', '_')

    # Wszystkie pliki w jednym katalogu (brak podziału na kategorie)
    os.makedirs(output_dir, exist_ok=True)
    
    if format == 'png':
        # Zapisz jako obraz PNG (skala szarości)
        filename = os.path.join(output_dir, f"{safe_id}.png")
        Image.fromarray(raster_normalized, mode='L').save(filename)
        
    elif format == 'jpg':
        # Zapisz jako obraz JPG
        filename = os.path.join(output_dir, f"{safe_id}.jpg")
        Image.fromarray(raster_normalized, mode='L').save(filename, quality=95)
        
    elif format == 'npy':
        # Zapisz jako macierz numpy (zachowuje oryginalne wartości 0-1)
        filename = os.path.join(output_dir, f"{safe_id}.npy")
        np.save(filename, raster_data)
    
    return filename

def prepare_prediction_data(df, output_dir='prediction_data', resolution=128, format='png', 
                           preview=True, max_preview=10):
    """
    Główna funkcja przygotowująca dane do predykcji
    
    Parameters:
    df: DataFrame z danymi (bez kolumny 'Kategoria' lub zostanie zignorowana)
    output_dir: katalog wyjściowy
    resolution: rozdzielczość obrazów (64, 128, 256 zalecane)
    format: format plików ('png', 'jpg', 'npy')  
    preview: czy pokazać podglądy
    max_preview: maksymalna liczba podglądów
    """
    
    # Utworzenie katalogu wyjściowego
    os.makedirs(output_dir, exist_ok=True)
    
    # Statystyki
    building_ids = df['ID_BUDYNKU'].unique()
    
    print("Przygotowywanie danych do predykcji...")
    print(f"Budynków: {len(building_ids)}")
    print(f"Rozdzielczość: {resolution}x{resolution}")
    print(f"Format: {format}")
    print("-" * 50)
    
    # Słownik do zbierania statystyk
    stats = {
        'total_buildings': len(building_ids),
        'processed_buildings': 0,
        'resolution': resolution,
        'format': format,
        'failed_buildings': [],
        'output_files': []
    }
    
    # Lista do mapowania ID budynków na pliki (przydatne do predykcji)
    building_file_mapping = {}
    
    # Licznik dla podglądu
    # preview_count = 0
    
    # Przetwarzanie każdego budynku
    for i, building_id in enumerate(building_ids, 1):
        print(f"[{i}/{len(building_ids)}] Przetwarzanie budynku: {building_id}")
        
        # Filtrowanie danych dla budynku
        building_data = df[df['ID_BUDYNKU'] == building_id].copy()
        
        if len(building_data) < 3:
            print(f"  Pominięto - za mało punktów ({len(building_data)})")
            stats['failed_buildings'].append({
                'building_id': building_id,
                'reason': 'too_few_points',
                'points_count': len(building_data)
            })
            continue
        
        try:
            # Tworzenie rastera
            zi = create_raster_for_building(building_data, building_id, resolution)
            
            # Zapisanie rastera
            filename = save_raster_for_prediction(zi, building_id, output_dir, format)
            
            # Aktualizacja statystyk
            stats['processed_buildings'] += 1
            stats['output_files'].append(os.path.relpath(filename))
            building_file_mapping[building_id] = os.path.relpath(filename)
            
            print(f"  Zapisano: {os.path.relpath(filename)}")
            
            # # Podgląd (opcjonalnie)
            # if preview and preview_count < max_preview:
            #     plt.figure(figsize=(8, 6))
                
            #     # Wykres punktów oryginalnych
            #     plt.subplot(1, 2, 1)
            #     scatter = plt.scatter(building_data['X'], building_data['Y'], 
            #                         c=building_data['Z_unitarized'], 
            #                         cmap='gray_r', s=30, edgecolors='black', linewidth=0.5)
            #     plt.title(f'Punkty oryginalne\n{building_id}')
            #     plt.xlabel('X')
            #     plt.ylabel('Y')
            #     plt.axis('equal')
            #     plt.colorbar(scatter, label='Z_unitarized')
                
            #     # Wykres rastera
            #     plt.subplot(1, 2, 2)
            #     plt.imshow(zi, cmap='gray_r', origin='lower')
            #     plt.title(f'Raster {resolution}x{resolution}\nGotowy do predykcji')
            #     plt.axis('off')
                
            #     plt.tight_layout()
            #     plt.show()
                
            #     preview_count += 1
            
        except Exception as e:
            print(f"  Błąd: {str(e)}")
            stats['failed_buildings'].append({
                'building_id': building_id,
                'reason': 'processing_error', 
                'error': str(e)
            })
            continue
    
    # Zapisanie mapowania ID -> plik (przydatne do interpretacji wyników predykcji)
    mapping_file = os.path.join(output_dir, 'building_file_mapping.json')
    with open(mapping_file, 'w', encoding='utf-8') as f:
        json.dump(building_file_mapping, f, indent=2, ensure_ascii=False)
    
    # Zapisanie statystyk
    stats_file = os.path.join(output_dir, 'prediction_data_stats.json')
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    
    # Podsumowanie
    print("\n" + "="*50)
    print("PODSUMOWANIE PRZYGOTOWANIA DANYCH DO PREDYKCJI")
    print("="*50)
    print(f"Katalog wyjściowy: {output_dir}")
    print(f"Rozdzielczość: {resolution}x{resolution}")
    print(f"Format plików: {format}")
    print(f"Łączna liczba budynków: {len(building_ids)}")
    print(f"Pomyślnie przetworzonych: {stats['processed_buildings']}")
    print(f"Błędnych: {len(stats['failed_buildings'])}")
    
    print("\nPLIKI WYJŚCIOWE:")
    print(f"  Obrazy/rastry: {stats['processed_buildings']} plików w {output_dir}/")
    print(f"  Mapowanie ID->plik: {mapping_file}")
    print(f"  Statystyki: {stats_file}")
    
    if stats['failed_buildings']:
        print("\nBUDYNKI Z BŁĘDAMI:")
        for failed in stats['failed_buildings'][:5]:  # Pokaż pierwszych 5
            print(f"  {failed['building_id']}: {failed['reason']}")
        if len(stats['failed_buildings']) > 5:
            print(f"  ... i {len(stats['failed_buildings']) - 5} więcej")
    
    print("\nDane gotowe do użycia przez model ML!")
    
    return stats, building_file_mapping


# Pobierz warstwę z projektu
nazwa_warstwy = 'Classification_6_with_IDs'
warstwa = QgsProject.instance().mapLayersByName(nazwa_warstwy)
if not warstwa:
    raise ValueError(f"Nie znaleziono warstwy o nazwie: {nazwa_warstwy}")

layer = warstwa[0]

# Pobierz dane atrybutowe
features = layer.getFeatures()
dane = []

for feature in features:
    dane.append(feature.attributes())

# Pobierz nazwy pól
nazwy_pol = [field.name() for field in layer.fields()]

# Stwórz DataFrame
df = pd.DataFrame(dane, columns=nazwy_pol)
# przetwarzanie df
df = df[['X','Y', 'Z', 'ID_BUDYNKU']]
# Obliczanie min i max dla każdej grupy
group_stats = df.groupby('ID_BUDYNKU')['Z'].agg(['min', 'max'])

# Łączenie z oryginalnymi danymi
df_alt = df.merge(group_stats, left_on='ID_BUDYNKU', right_index=True, suffixes=('', '_group'))

# Obliczanie unitaryzacji zerowanej
df_alt['Z_unitarized'] = np.where(
    df_alt['max'] == df_alt['min'],  # Jeśli min == max
    0.0,  # Przypisz 0
    (df_alt['Z'] - df_alt['min']) / (df_alt['max'] - df_alt['min'])  # Inaczej unitaryzuj
)

# Usunięcie pomocniczych kolumn
df_alt = df_alt.drop(['min', 'max'], axis=1)

# RASTERYZACJA
 # Parametry do dostosowania
RESOLUTION = 128  # 64, 128, lub 256
FORMAT = 'png'    # 'png', 'jpg', lub 'npy'  
def get_prediction_data_dir():
    """Zwraca ścieżkę do katalogu prediction_data w folderze projektu QGIS"""
    prediction_dir = project_directory / "prediction_data"
    
    # Utwórz folder jeśli nie istnieje
    prediction_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Katalog predykcji (w projekcie): {prediction_dir}")
    return str(prediction_dir)


# Użycie:
OUTPUT_DIR = get_prediction_data_dir()

# Uruchomienie 
stats, mapping = prepare_prediction_data(
    df = df_alt, 
    output_dir=OUTPUT_DIR,
    resolution=RESOLUTION,
    format=FORMAT,
    preview=True,
    max_preview=5
)
 
run_classifier()