#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🎯 ZOPTYMALIZOWANY PIPELINE DLA DUŻYCH CHMUR PUNKTÓW
Z logowaniem postępu i inteligentnym przycinaniem

KLUCZOWE USPRAWNIENIE:
- Jeśli brak RGB w chmurze → najpierw przycina do maski, POTEM dodaje RGB
- To drastycznie przyspiesza proces dla dużych chmur!

INSTRUKCJA:
1. Wczytaj chmurę punktów LAZ do QGIS (zaznacz jako aktywną)
2. Wczytaj warstwy maski: 'dzialki_zgodne_z_funkcja' i 'granica_terenu'
3. Wczytaj ortofotomapę (jeśli chmura nie ma RGB)
4. Uruchom skrypt
5. Monitoruj postęp w pliku: ~/qgis_progress.log

UWAGA: Dla dużych chmur (38M+) może to trwać 2-4 GODZINY!
"""

from qgis.core import (
    QgsProcessingFeedback, QgsProject,
    QgsVectorLayer, QgsProcessingContext,
    QgsField, QgsRasterLayer, QgsPointCloudLayer,
    QgsCoordinateTransform, QgsRaster
)
from qgis import processing
from qgis.PyQt.QtCore import QVariant, Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QComboBox, QGroupBox, QMessageBox
)
from qgis.PyQt.QtGui import QFont
import os
import time
from datetime import datetime

try:
    from qgis.utils import iface
    IFACE_AVAILABLE = True
except ImportError:
    iface = None
    IFACE_AVAILABLE = False

# ==================== USTAWIENIA ====================
LOG_FILE = os.path.expanduser("~/qgis_progress.log")
PROGRESS_UPDATE_INTERVAL = 100000  # Co ile punktów raportować postęp
COMMIT_INTERVAL = 1000000  # Co ile punktów zapisywać (commit)

# Nazwy warstw maski (możesz zmienić)
MASK_LAYER_1 = 'dzialki_zgodne_z_funkcja'
MASK_LAYER_2 = 'granica_terenu'

# Klasyfikacje do wczytania po podziale
CLASSIFICATIONS_TO_LOAD = [2, 3, 4, 5, 6, 9]


class ProgressLogger:
    """Klasa do logowania postępu do pliku z dokładnymi pomiarami czasu"""
    
    def __init__(self, log_file):
        self.log_file = log_file
        self.start_time = None
        self.overall_start = time.time()
        
        # Wyczyść stary log i utwórz nagłówek
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("QGIS POINT CLOUD PROCESSING LOG\n")
            f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")
        
        print(f"\n📝 Logowanie postępu do: {self.log_file}")
        print(f"   Monitoruj w czasie rzeczywistym: tail -f {self.log_file}")
    
    def log(self, message, also_print=True):
        """Zapisz wiadomość do logu z timestampem"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_msg = f"[{timestamp}] {message}"
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_msg + "\n")
        
        if also_print:
            print(message)
    
    def start_timer(self, task_name):
        """Rozpocznij pomiar czasu dla zadania"""
        self.start_time = time.time()
        self.log(f"\n{'='*80}")
        self.log(f"⏳ ROZPOCZYNAM: {task_name}")
        self.log(f"{'='*80}")
    
    def end_timer(self, task_name):
        """Zakończ pomiar czasu i raportuj"""
        if self.start_time:
            elapsed = time.time() - self.start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.log(f"✅ {task_name} zakończone w {minutes}m {seconds}s")
            self.start_time = None
    
    def estimate_time(self, processed, total, operation_name="Operacja"):
        """Oszacuj pozostały czas na podstawie dotychczasowego postępu"""
        if self.start_time and processed > 0:
            elapsed = time.time() - self.start_time
            rate = processed / elapsed  # punktów/sekundę
            remaining = total - processed
            eta_seconds = remaining / rate if rate > 0 else 0
            eta_minutes = int(eta_seconds // 60)
            
            self.log(
                f"📊 {operation_name}: {processed:,}/{total:,} punktów "
                f"({100*processed/total:.1f}%) - "
                f"Pozostało ~{eta_minutes} minut"
            )
    
    def final_summary(self):
        """Podsumowanie całego procesu"""
        total_elapsed = time.time() - self.overall_start
        hours = int(total_elapsed // 3600)
        minutes = int((total_elapsed % 3600) // 60)
        seconds = int(total_elapsed % 60)
        
        self.log("\n" + "="*80)
        self.log("🎉 PRZETWARZANIE ZAKOŃCZONE POMYŚLNIE!")
        self.log("="*80)
        if hours > 0:
            self.log(f"⏱️  Całkowity czas: {hours}h {minutes}m {seconds}s")
        else:
            self.log(f"⏱️  Całkowity czas: {minutes}m {seconds}s")


# Globalna instancja loggera
logger = ProgressLogger(LOG_FILE)


# ==================== FUNKCJE POMOCNICZE ====================

def get_active_layer():
    """Pobiera aktywną warstwę z QGIS"""
    if not IFACE_AVAILABLE or not iface:
        raise Exception("iface nie jest dostępne!")
    
    layer = iface.activeLayer()
    if layer is None:
        raise Exception("Brak aktywnej warstwy! Wybierz warstwę point cloud w panelu warstw.")
    
    logger.log(f"\n📍 Aktywna warstwa: {layer.name()}")
    logger.log(f"   Typ: {type(layer).__name__}")
    logger.log(f"   Źródło: {layer.source()}")
    
    return layer


def get_available_point_cloud_attributes(layer):
    """
    Pobiera listę dostępnych atrybutów w chmurze punktów
    """
    logger.log("\n🔍 Sprawdzam atrybuty chmury punktów...")
    
    try:
        if isinstance(layer, QgsPointCloudLayer):
            attributes_collection = layer.attributes()
            attr_list = attributes_collection.attributes()
            attr_names = [attr.name() for attr in attr_list]
            
            logger.log(f"   Znaleziono {len(attr_names)} atrybutów:")
            for attr in attr_names:
                logger.log(f"      - {attr}")
            
            return attr_names
        else:
            logger.log("   ⚠️  Nie jest QgsPointCloudLayer, używam domyślnych atrybutów")
            return ['X', 'Y', 'Z', 'Classification', 'Intensity']
    except Exception as e:
        logger.log(f"   ❌ Błąd odczytu atrybutów: {e}")
        return ['X', 'Y', 'Z', 'Classification', 'Intensity']


def merge_vector_layers(layer1, layer2, project):
    """Scalanie dwóch warstw wektorowych"""
    logger.log(f"\n🔗 Scalanie warstw: '{layer1.name()}' + '{layer2.name()}'")
    
    if not layer1 or not layer2:
        raise ValueError("Jedna z warstw jest nieprawidłowa")
    
    params = {
        'LAYERS': [layer1, layer2],
        'CRS': None,
        'OUTPUT': 'TEMPORARY_OUTPUT'
    }
    
    result = processing.run('native:mergevectorlayers', params)
    merged_layer = result['OUTPUT']
    merged_layer.setName('Scalone_warstwy')
    project.addMapLayer(merged_layer)
    
    logger.log(f"✅ Scalono! Obiektów: {merged_layer.featureCount()}")
    
    return merged_layer


def przytnij_warstwe_do_maski(warstwa_wejsciowa, nazwa_maski):
    """
    Przycina warstwę wektorową do maski
    """
    logger.start_timer(f"Przycinanie do maski '{nazwa_maski}'")
    
    if not warstwa_wejsciowa or not warstwa_wejsciowa.isValid():
        raise ValueError("Warstwa wejściowa jest nieprawidłowa")
    
    warstwy_maski = QgsProject.instance().mapLayersByName(nazwa_maski)
    
    if not warstwy_maski:
        raise ValueError(f"Nie znaleziono warstwy o nazwie: {nazwa_maski}")
    
    warstwa_maska = warstwy_maski[0]
    
    if not warstwa_maska.isValid():
        raise ValueError(f"Warstwa {nazwa_maski} jest nieprawidłowa")
    
    input_count = warstwa_wejsciowa.featureCount()
    logger.log(f"   Punktów przed przycięciem: {input_count:,}")
    
    parametry = {
        'INPUT': warstwa_wejsciowa,
        'OVERLAY': warstwa_maska,
        'OUTPUT': 'memory:'
    }
    
    wynik = processing.run("native:clip", parametry)
    warstwa_wynikowa = wynik['OUTPUT']
    
    output_count = warstwa_wynikowa.featureCount()
    removed = input_count - output_count
    percent_removed = (removed / input_count * 100) if input_count > 0 else 0
    
    logger.log(f"   Punktów po przycięciu: {output_count:,}")
    logger.log(f"   Usunięto: {removed:,} punktów ({percent_removed:.1f}%)")
    
    logger.end_timer(f"Przycinanie do maski")
    
    return warstwa_wynikowa


def find_best_orthophoto():
    """Znajduje najlepszą dostępną ortofotomapę w projekcie"""
    logger.log("\n🔍 Szukam ortofotomapy...")
    
    project = QgsProject.instance()
    layers = project.mapLayers().values()
    
    raster_layers = [l for l in layers if isinstance(l, QgsRasterLayer) and l.isValid()]
    
    if not raster_layers:
        logger.log("   ⚠️  Brak warstw rastrowych w projekcie")
        return None
    
    # Preferuj RGB (3+ pasma)
    rgb_layers = [l for l in raster_layers if l.bandCount() >= 3]
    
    if rgb_layers:
        best = rgb_layers[0]
        logger.log(f"   ✅ Znaleziono ortofotomapę RGB: '{best.name()}' ({best.bandCount()} pasm)")
        return best.name()
    
    # Jeśli nie ma RGB, weź grayscale
    gray_layers = [l for l in raster_layers if l.bandCount() == 1]
    if gray_layers:
        best = gray_layers[0]
        logger.log(f"   ⚠️  Znaleziono tylko grayscale: '{best.name()}'")
        return best.name()
    
    logger.log("   ❌ Nie znaleziono odpowiedniej ortofotomapy")
    return None


def add_rgb_from_orthophoto(vector_layer, orthophoto_layer_name):
    """
    Dodaje wartości RGB z ortofotomapy do warstwy punktowej
    Z POSTĘPEM dla dużych zbiorów danych
    """
    logger.start_timer("Dodawanie RGB z ortofotomapy")
    
    project = QgsProject.instance()
    
    # Znajdź warstwę ortofotomapy
    ortho_layers = project.mapLayersByName(orthophoto_layer_name)
    if not ortho_layers:
        logger.log(f"❌ Nie znaleziono warstwy ortofotomapy: {orthophoto_layer_name}")
        return False
    
    raster_layer = ortho_layers[0]
    
    if not raster_layer.isValid():
        logger.log(f"❌ Warstwa ortofotomapy jest nieprawidłowa")
        return False
    
    band_count = raster_layer.bandCount()
    is_grayscale = (band_count == 1)
    
    if is_grayscale:
        logger.log(f"⚠️  Ortofotomapa: Grayscale (wartość będzie skopiowana do R,G,B)")
    elif band_count < 3:
        logger.log(f"❌ Ortofotomapa musi mieć co najmniej 3 pasma (RGB) lub 1 (grayscale)")
        return False
    else:
        logger.log(f"✅ Ortofotomapa: RGB ({band_count} pasm)")
    
    logger.log(f"   Ortofotomapa: {raster_layer.name()}")
    logger.log(f"   CRS: {raster_layer.crs().authid()}")
    
    # Dodaj pola RGB jeśli nie istnieją
    provider = vector_layer.dataProvider()
    existing_fields = [field.name() for field in vector_layer.fields()]
    fields_to_add = []
    
    if 'Red' not in existing_fields:
        fields_to_add.append(QgsField('Red', QVariant.Int))
    if 'Green' not in existing_fields:
        fields_to_add.append(QgsField('Green', QVariant.Int))
    if 'Blue' not in existing_fields:
        fields_to_add.append(QgsField('Blue', QVariant.Int))
    
    if fields_to_add:
        vector_layer.startEditing()
        provider.addAttributes(fields_to_add)
        vector_layer.updateFields()
        vector_layer.commitChanges()
        logger.log("   ✓ Dodano pola RGB")
    
    # Pobierz provider rastra
    raster_provider = raster_layer.dataProvider()
    
    # Sprawdź czy potrzebna transformacja CRS
    vector_crs = vector_layer.crs()
    raster_crs = raster_layer.crs()
    
    transform = None
    if vector_crs != raster_crs:
        logger.log(f"   🔄 Transformacja CRS: {vector_crs.authid()} → {raster_crs.authid()}")
        transform = QgsCoordinateTransform(vector_crs, raster_crs, project)
    
    # Pobierz indeksy pól
    red_idx = vector_layer.fields().indexFromName('Red')
    green_idx = vector_layer.fields().indexFromName('Green')
    blue_idx = vector_layer.fields().indexFromName('Blue')
    
    # Rozpocznij edycję
    vector_layer.startEditing()
    
    total_features = vector_layer.featureCount()
    processed = 0
    success_count = 0
    
    logger.log(f"\n⏳ Przetwarzanie {total_features:,} punktów...")
    logger.log(f"   Postęp raportowany co {PROGRESS_UPDATE_INTERVAL:,} punktów")
    
    # Oszacowanie czasu
    estimated_minutes = total_features // 10000
    if estimated_minutes > 60:
        logger.log(f"   ⏱️  Szacowany czas: ~{estimated_minutes//60}h {estimated_minutes%60}m")
    else:
        logger.log(f"   ⏱️  Szacowany czas: ~{estimated_minutes}m")
    
    logger.log("")
    
    for feature in vector_layer.getFeatures():
        geom = feature.geometry()
        
        if geom.isNull() or geom.isEmpty():
            continue
        
        point = geom.asPoint()
        
        if transform:
            point = transform.transform(point)
        
        try:
            ident = raster_provider.identify(point, QgsRaster.IdentifyFormatValue)
            
            if ident.isValid():
                results = ident.results()
                
                if is_grayscale:
                    # Dla grayscale skopiuj wartość do R, G, B
                    gray = results.get(1, None)
                    if gray is not None:
                        gray_int = int(gray)
                        vector_layer.changeAttributeValue(feature.id(), red_idx, gray_int)
                        vector_layer.changeAttributeValue(feature.id(), green_idx, gray_int)
                        vector_layer.changeAttributeValue(feature.id(), blue_idx, gray_int)
                        success_count += 1
                else:
                    # Dla RGB
                    red = results.get(1, None)
                    green = results.get(2, None)
                    blue = results.get(3, None)
                    
                    if red is not None and green is not None and blue is not None:
                        vector_layer.changeAttributeValue(feature.id(), red_idx, int(red))
                        vector_layer.changeAttributeValue(feature.id(), green_idx, int(green))
                        vector_layer.changeAttributeValue(feature.id(), blue_idx, int(blue))
                        success_count += 1
                    
        except Exception as e:
            pass
        
        processed += 1
        
        # Raportuj postęp
        if processed % PROGRESS_UPDATE_INTERVAL == 0:
            logger.estimate_time(processed, total_features, "Dodawanie RGB")
        
        # Commit co określoną liczbę punktów aby oszczędzić RAM
        if processed % COMMIT_INTERVAL == 0:
            vector_layer.commitChanges()
            vector_layer.startEditing()
            logger.log(f"   💾 Zapisano postęp (commit) - {processed:,} punktów")
    
    # Finalny commit
    vector_layer.commitChanges()
    
    logger.end_timer("Dodawanie RGB z ortofotomapy")
    logger.log(f"✅ Przypisano RGB do {success_count:,}/{total_features:,} punktów "
               f"({100*success_count/total_features:.1f}%)")
    
    return True


# ==================== KROKI PIPELINE ====================

def step1_filter_points(input_layer, context, feedback):
    """
    Krok 1: Filtrowanie punktów z Classification != 0
    """
    logger.start_timer("KROK 1: Filtrowanie punktów (Classification != 0)")
    
    filter_params = {
        'INPUT': input_layer,
        'FILTER_EXPRESSION': 'Classification != 0',
        'FILTER_EXTENT': None,
        'OUTPUT': 'TEMPORARY_OUTPUT'
    }
    
    logger.log("   Parametry filtrowania:")
    for key, value in filter_params.items():
        logger.log(f"      {key}: {value}")
    
    logger.log("\n   ⏳ Przetwarzanie przez PDAL...")
    logger.log("   (To może zająć dużo czasu dla dużych chmur!)")
    logger.log("   (Konsola QGIS może być zamrożona - to normalne)")
    
    result = processing.run("pdal:filter", filter_params, context=context, feedback=feedback)
    
    filtered_layer = result['OUTPUT']
    logger.end_timer("KROK 1: Filtrowanie")
    
    return filtered_layer


def step2_export_to_vector(filtered_layer, output_path, available_attributes, context, feedback):
    """
    Krok 2: Konwersja do wektora z dostępnymi atrybutami
    """
    logger.start_timer("KROK 2: Eksport do wektora")
    
    # Podstawowe atrybuty, które chcemy zachować
    desired_attributes = [
        'X', 'Y', 'Z', 'Classification', 'Intensity', 
        'ReturnNumber', 'NumberOfReturns', 'Red', 'Green', 'Blue'
    ]
    
    # Wybierz tylko te atrybuty, które są dostępne
    attributes_to_export = [attr for attr in desired_attributes if attr in available_attributes]
    
    logger.log(f"   Dostępne atrybuty: {available_attributes}")
    logger.log(f"   Atrybuty do eksportu: {attributes_to_export}")
    
    # Sprawdź czy RGB jest dostępne
    has_rgb = all(attr in available_attributes for attr in ['Red', 'Green', 'Blue'])
    if has_rgb:
        logger.log("   ✅ Chmura POSIADA RGB")
    else:
        logger.log("   ⚠️  Chmura NIE POSIADA RGB - będzie dodane później z ortofotomapy")
    
    export_params = {
        'INPUT': filtered_layer,
        'ATTRIBUTE': attributes_to_export,
        'FILTER_EXPRESSION': '',
        'FILTER_EXTENT': None,
        'OUTPUT': output_path
    }
    
    logger.log("\n   ⏳ Eksportowanie punktów do wektora...")
    logger.log("   (Dla dużych chmur może to zająć 30-60 minut!)")
    
    result = processing.run("pdal:exportvector", export_params, context=context, feedback=feedback)
    
    vector_layer = result['OUTPUT']
    logger.end_timer("KROK 2: Eksport do wektora")
    
    return vector_layer, has_rgb


def step3_reproject_and_load(vector_path, project_crs, context, feedback):
    """
    Krok 3: Reprojekcja w układzie współrzędnych projektu i wczytanie jako pcv_CRS
    """
    logger.start_timer("KROK 3: Reprojekcja")
    
    project_dir = os.path.dirname(vector_path)
    reprojected_path = os.path.join(project_dir, "pcv_CRS.gpkg")
    
    reproject_params = {
        'INPUT': vector_path,
        'TARGET_CRS': project_crs,
        'OUTPUT': reprojected_path
    }
    
    logger.log("   Parametry reprojekcji:")
    for key, value in reproject_params.items():
        logger.log(f"      {key}: {value}")
    
    logger.log("\n   ⏳ Reprojekcja...")
    
    result = processing.run("native:reprojectlayer", reproject_params, context=context, feedback=feedback)
    
    pcv_layer = QgsVectorLayer(reprojected_path, "pcv_CRS", "ogr")
    if pcv_layer.isValid():
        QgsProject.instance().addMapLayer(pcv_layer)
        feature_count = pcv_layer.featureCount()
        logger.log(f"   ✅ Warstwa pcv_CRS wczytana ({feature_count:,} punktów)")
    else:
        raise Exception(f"Błąd wczytywania warstwy: {reprojected_path}")
    
    logger.end_timer("KROK 3: Reprojekcja")
    
    return pcv_layer, reprojected_path


def step4_split_by_classification(pcv_layer, output_dir, context, feedback):
    """
    Krok 4: Podział warstwy według atrybutu Classification
    """
    logger.start_timer("KROK 4: Podział według klasyfikacji")
    
    split_params = {
        'INPUT': pcv_layer,
        'FIELD': 'Classification',
        'FILE_TYPE': 0,  # GeoPackage
        'OUTPUT': output_dir,
        'PREFIX_FIELD': True
    }
    
    logger.log("   Parametry podziału:")
    for key, value in split_params.items():
        logger.log(f"      {key}: {value}")
    
    logger.log("\n   ⏳ Dzielę warstwę na osobne pliki według klasyfikacji...")
    
    result = processing.run("native:splitvectorlayer", split_params, context=context, feedback=feedback)
    
    output_layers = result['OUTPUT_LAYERS']
    logger.end_timer("KROK 4: Podział według klasyfikacji")
    logger.log(f"   ✅ Utworzono {len(output_layers)} warstw")
    
    return output_layers


def step5_load_specific_classifications(output_dir):
    """
    Krok 5: Wczytanie określonych klasyfikacji do projektu
    """
    logger.start_timer("KROK 5: Wczytywanie wybranych klasyfikacji do projektu")
    
    loaded_layers = []
    
    logger.log(f"   Wczytuję klasyfikacje: {CLASSIFICATIONS_TO_LOAD}")
    
    for classification in CLASSIFICATIONS_TO_LOAD:
        layer_name = f"Classification_{classification}"
        layer_path = os.path.join(output_dir, f"{layer_name}.gpkg")
        
        if os.path.exists(layer_path):
            layer = QgsVectorLayer(layer_path, layer_name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                loaded_layers.append(layer)
                count = layer.featureCount()
                logger.log(f"   ✅ {layer_name}: {count:,} punktów")
            else:
                logger.log(f"   ✗ Błąd wczytywania: {layer_name}")
        else:
            logger.log(f"   ⚠️  Nie znaleziono pliku: {layer_path}")
    
    logger.end_timer("KROK 5: Wczytywanie klasyfikacji")
    logger.log(f"   ✅ Wczytano {len(loaded_layers)} warstw")
    
    return loaded_layers


# ==================== GŁÓWNA FUNKCJA ====================

def main(add_rgb_from_ortho=False, orthophoto_layer_name=None):
    """
    Główna funkcja wykonująca cały pipeline
    
    KLUCZOWA ZMIANA:
    Jeśli chmura nie ma RGB, to najpierw przycina do maski, 
    a POTEM dodaje RGB - to oszczędza dużo czasu!
    
    Args:
        add_rgb_from_ortho: czy dodać RGB z ortofotomapy (True/False)
        orthophoto_layer_name: nazwa warstwy z ortofotomapą (opcjonalna)
    """
    
    print("""
╔═══════════════════════════════════════════════════════════════╗
║   ZOPTYMALIZOWANY PIPELINE PRZETWARZANIA CHMURY PUNKTÓW       ║
║   Z inteligentnym przycinaniem i monitorowaniem postępu       ║
╚═══════════════════════════════════════════════════════════════╝

⚠️  Dla dużych chmur (38M+) oczekuj 2-4 GODZIN przetwarzania!
📝  Postęp logowany do: ~/qgis_progress.log
🔍  Monitoruj: tail -f ~/qgis_progress.log
❌  Błędy libpoppler.so możesz IGNOROWAĆ!
""")
    
    try:
        logger.log("="*80)
        logger.log("🚀 ROZPOCZĘCIE PIPELINE PRZETWARZANIA CHMURY PUNKTÓW")
        logger.log("="*80)
        
        # Konfiguracja
        context = QgsProcessingContext()
        feedback = QgsProcessingFeedback()
        
        # Pobierz aktywną warstwę
        active_layer = get_active_layer()
        
        # Pobierz dostępne atrybuty
        available_attributes = get_available_point_cloud_attributes(active_layer)
        has_rgb = all(attr in available_attributes for attr in ['Red', 'Green', 'Blue'])
        
        # Pobierz CRS projektu
        project = QgsProject.instance()
        project_crs = project.crs()
        logger.log(f"\n📍 CRS projektu: {project_crs.authid()}")
        
        # Określ ścieżki wyjściowe
        if hasattr(active_layer, 'source') and active_layer.source():
            source_path = active_layer.source()
            if '|' in source_path:
                source_path = source_path.split('|')[0]
            project_dir = os.path.dirname(source_path)
        else:
            project_dir = os.path.expanduser("~/Documents")
        
        vector_output_path = os.path.join(project_dir, "points_cloud_vector.gpkg")
        
        logger.log(f"📂 Katalog projektu: {project_dir}")
        logger.log(f"📂 Ścieżka wektora: {vector_output_path}")
        
        # ============================================================
        # KROK 1: Filtrowanie punktów
        # ============================================================
        filtered_layer = step1_filter_points(active_layer, context, feedback)
        
        # ============================================================
        # KROK 2: Konwersja do wektora
        # ============================================================
        vector_layer, has_rgb_after = step2_export_to_vector(
            filtered_layer, vector_output_path, available_attributes, context, feedback
        )
        
        # ============================================================
        # KROK 3: Reprojekcja i wczytanie jako pcv_CRS
        # ============================================================
        pcv_layer, pcv_path = step3_reproject_and_load(
            vector_output_path, project_crs, context, feedback
        )
        
        # ============================================================
        # KLUCZOWA ZMIANA: Przycinanie PRZED dodaniem RGB (jeśli brak RGB)
        # ============================================================
        layer_for_rgb = pcv_layer  # Domyślnie używamy pełnej warstwy
        layer_to_split = pcv_layer  # Domyślnie nie przycinamy
        
        if not has_rgb_after:
            # Brak RGB - najpierw przytniemy, potem dodamy RGB
            logger.log("\n" + "="*80)
            logger.log("🎯 OPTYMALIZACJA: Brak RGB → Najpierw przytnę, potem dodam RGB")
            logger.log("   (To zaoszczędzi dużo czasu!)")
            logger.log("="*80)
            
            # Próba przycinania do maski
            try:
                layer1 = project.mapLayersByName(MASK_LAYER_1)[0]
                layer2 = project.mapLayersByName(MASK_LAYER_2)[0]
                merged_mask = merge_vector_layers(layer1, layer2, project)
                
                if merged_mask:
                    pcv_layer_przycieta = przytnij_warstwe_do_maski(pcv_layer, 'Scalone_warstwy')
                    pcv_layer_przycieta.setName('pcv_CRS_przycieta')
                    project.addMapLayer(pcv_layer_przycieta)
                    
                    logger.log("✅ Przycięcie zakończone pomyślnie")
                    
                    # Używamy przyciętej warstwy do dodania RGB i podziału
                    layer_for_rgb = pcv_layer_przycieta
                    layer_to_split = pcv_layer_przycieta
                else:
                    logger.log("⚠️  Nie udało się scalić warstw maski")
                    layer_for_rgb = pcv_layer
                    layer_to_split = pcv_layer
            except Exception as e:
                logger.log(f"⚠️  Przycinanie pominięte: {e}")
                logger.log("   Używam pełnej warstwy")
                layer_for_rgb = pcv_layer
                layer_to_split = pcv_layer
        else:
            # Ma RGB - przycinamy po dodaniu RGB (normalna ścieżka)
            logger.log("\n✅ Chmura już posiada RGB")
        
        # ============================================================
        # Dodawanie RGB z ortofotomapy (jeśli potrzeba)
        # ============================================================
        if not has_rgb_after and add_rgb_from_ortho:
            logger.log("\n" + "="*80)
            logger.log("📸 DODAWANIE RGB Z ORTOFOTOMAPY")
            logger.log("="*80)
            
            # Znajdź ortofotomapę jeśli nie podano
            if not orthophoto_layer_name:
                orthophoto_layer_name = find_best_orthophoto()
            
            if orthophoto_layer_name:
                success = add_rgb_from_orthophoto(layer_for_rgb, orthophoto_layer_name)
                if success:
                    logger.log("✅ RGB dodane pomyślnie!")
                else:
                    logger.log("❌ Nie udało się dodać RGB")
            else:
                logger.log("❌ Nie znaleziono ortofotomapy w projekcie")
                logger.log("   Podaj nazwę warstwy: main(add_rgb_from_ortho=True, orthophoto_layer_name='nazwa')")
        elif not has_rgb_after:
            logger.log("\n⚠️  Uwaga: Dane nie zawierają RGB!")
            logger.log("   Aby dodać RGB z ortofotomapy, wywołaj:")
            logger.log("   main(add_rgb_from_ortho=True, orthophoto_layer_name='nazwa_warstwy')")
            logger.log("   lub main(add_rgb_from_ortho=True) - auto-wykryje ortofotomapę")
        
        # ============================================================
        # Przycinanie (jeśli ma RGB lub nie dodajemy RGB)
        # ============================================================
        if has_rgb_after or not add_rgb_from_ortho:
            logger.log("\n" + "="*80)
            logger.log("✂️  PRZYCINANIE DO MASKI")
            logger.log("="*80)
            
            try:
                layer1 = project.mapLayersByName(MASK_LAYER_1)[0]
                layer2 = project.mapLayersByName(MASK_LAYER_2)[0]
                merged_mask = merge_vector_layers(layer1, layer2, project)
                
                if merged_mask:
                    pcv_layer_przycieta = przytnij_warstwe_do_maski(pcv_layer, 'Scalone_warstwy')
                    pcv_layer_przycieta.setName('pcv_CRS_przycieta')
                    project.addMapLayer(pcv_layer_przycieta)
                    
                    logger.log("✅ Przycięcie zakończone")
                    layer_to_split = pcv_layer_przycieta
                else:
                    layer_to_split = pcv_layer
            except Exception as e:
                logger.log(f"⚠️  Przycinanie pominięte: {e}")
                layer_to_split = pcv_layer
        
        # ============================================================
        # KROK 4: Podział według klasyfikacji
        # ============================================================
        output_layers = step4_split_by_classification(layer_to_split, project_dir, context, feedback)
        
        # ============================================================
        # KROK 5: Wczytanie określonych klasyfikacji
        # ============================================================
        loaded_layers = step5_load_specific_classifications(project_dir)
        
        # ============================================================
        # PODSUMOWANIE
        # ============================================================
        logger.final_summary()
        logger.log(f"📦 Utworzono {len(output_layers)} warstw z podziału")
        logger.log(f"📥 Wczytano {len(loaded_layers)} warstw do projektu:")
        for layer in loaded_layers:
            logger.log(f"   - {layer.name()}: {layer.featureCount():,} punktów")
        
        logger.log(f"\n📂 Pliki zapisane w: {project_dir}")
        logger.log(f"📝 Pełny log: {LOG_FILE}")
        
        # Odśwież widok
        if IFACE_AVAILABLE and iface:
            iface.mapCanvas().refresh()
            logger.log("\n🔄 Odświeżono widok mapy")
        
        logger.log("\n" + "🎉 "*35)
        
        return True
        
    except Exception as e:
        logger.log(f"\n{'='*80}")
        logger.log(f"❌ BŁĄD W PIPELINE: {str(e)}")
        logger.log(f"{'='*80}")
        import traceback
        logger.log(traceback.format_exc())
        return False


# ==================== DIALOG UI ====================

class PointCloudProcessingDialog(QDialog):
    """
    Dialog do konfiguracji przetwarzania chmury punktów
    """
    
    def __init__(self, has_rgb, available_orthophotos, parent=None):
        super().__init__(parent)
        self.has_rgb = has_rgb
        self.available_orthophotos = available_orthophotos
        self.selected_orthophoto = None
        self.should_add_rgb = False
        
        self.setWindowTitle("Przetwarzanie Chmury Punktów - Konfiguracja")
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Ustawienie interfejsu użytkownika"""
        layout = QVBoxLayout()
        
        # Nagłówek
        header = QLabel("🎯 Konfiguracja Pipeline Przetwarzania")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        layout.addSpacing(20)
        
        # Status RGB w chmurze
        rgb_group = QGroupBox("📊 Status RGB w Chmurze Punktów")
        rgb_layout = QVBoxLayout()
        
        if self.has_rgb:
            rgb_status = QLabel("✅ Chmura punktów POSIADA dane RGB")
            rgb_status.setStyleSheet("color: green; font-weight: bold; font-size: 12pt;")
            rgb_layout.addWidget(rgb_status)
            
            info = QLabel("Dane RGB zostaną zachowane podczas przetwarzania.")
            info.setWordWrap(True)
            rgb_layout.addWidget(info)
        else:
            rgb_status = QLabel("⚠️ Chmura punktów NIE POSIADA danych RGB")
            rgb_status.setStyleSheet("color: orange; font-weight: bold; font-size: 12pt;")
            rgb_layout.addWidget(rgb_status)
            
            info = QLabel(
                "Dane RGB mogą być dodane z ortofotomapy.\n"
                "OPTYMALIZACJA: Przycinanie nastąpi PRZED dodaniem RGB,\n"
                "co znacznie przyspieszy proces!"
            )
            info.setWordWrap(True)
            rgb_layout.addWidget(info)
        
        rgb_group.setLayout(rgb_layout)
        layout.addWidget(rgb_group)
        
        layout.addSpacing(10)
        
        # Wybór ortofotomapy (tylko jeśli brak RGB)
        if not self.has_rgb:
            ortho_group = QGroupBox("📸 Wybór Ortofotomapy")
            ortho_layout = QVBoxLayout()
            
            ortho_label = QLabel("Wybierz ortofotomapę do przypisania RGB:")
            ortho_layout.addWidget(ortho_label)
            
            self.ortho_combo = QComboBox()
            
            if self.available_orthophotos:
                self.ortho_combo.addItem("--- Nie dodawaj RGB ---", None)
                
                for ortho_name in self.available_orthophotos:
                    self.ortho_combo.addItem(ortho_name, ortho_name)
                
                # Automatycznie wybierz pierwszą ortofotomapę
                if len(self.available_orthophotos) > 0:
                    self.ortho_combo.setCurrentIndex(1)
            else:
                self.ortho_combo.addItem("--- Brak dostępnych ortofotomap ---", None)
                self.ortho_combo.setEnabled(False)
            
            ortho_layout.addWidget(self.ortho_combo)
            
            ortho_info = QLabel(
                "ℹ️ Jeśli wybierzesz ortofotomapę, RGB zostanie dodane\n"
                "po przycięciu warstwy do maski (optymalizacja!)."
            )
            ortho_info.setStyleSheet("color: #666; font-size: 9pt;")
            ortho_info.setWordWrap(True)
            ortho_layout.addWidget(ortho_info)
            
            ortho_group.setLayout(ortho_layout)
            layout.addWidget(ortho_group)
        
        layout.addSpacing(20)
        
        # Informacja o czasie
        time_info = QLabel(
            "⏱️ Szacowany czas przetwarzania: 2-4 godziny dla dużych chmur (38M+ punktów)\n"
            "📝 Postęp będzie logowany do: ~/qgis_progress.log"
        )
        time_info.setStyleSheet("color: #666; font-size: 9pt;")
        time_info.setWordWrap(True)
        layout.addWidget(time_info)
        
        layout.addSpacing(20)
        
        # Przyciski
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_btn = QPushButton("Anuluj")
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        self.ok_btn = QPushButton("Rozpocznij Przetwarzanie")
        self.ok_btn.setMinimumWidth(180)
        self.ok_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 8px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        self.ok_btn.clicked.connect(self.accept_and_process)
        button_layout.addWidget(self.ok_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def accept_and_process(self):
        """Akceptacja dialogu i przygotowanie parametrów"""
        if not self.has_rgb:
            # Pobierz wybraną ortofotomapę
            self.selected_orthophoto = self.ortho_combo.currentData()
            self.should_add_rgb = (self.selected_orthophoto is not None)
            
            if self.should_add_rgb:
                logger.log(f"✅ Użytkownik wybrał ortofotomapę: {self.selected_orthophoto}")
            else:
                logger.log("⚠️ Użytkownik wybrał: Nie dodawaj RGB")
        else:
            logger.log("✅ Chmura ma RGB - przetwarzanie bez ortofotomapy")
        
        self.accept()


def detect_rgb_in_active_layer():
    """
    Sprawdza czy aktywna warstwa chmury punktów ma RGB
    
    Returns:
        tuple: (has_rgb: bool, layer: QgsPointCloudLayer)
    """
    try:
        layer = get_active_layer()
        available_attributes = get_available_point_cloud_attributes(layer)
        has_rgb = all(attr in available_attributes for attr in ['Red', 'Green', 'Blue'])
        
        return has_rgb, layer
    except Exception as e:
        logger.log(f"❌ Błąd sprawdzania warstwy: {e}")
        return False, None


def get_all_orthophotos():
    """
    Pobiera listę wszystkich dostępnych ortofotomap w projekcie
    
    Returns:
        list: Lista nazw warstw rastrowych
    """
    project = QgsProject.instance()
    layers = project.mapLayers().values()
    
    raster_layers = [l for l in layers if isinstance(l, QgsRasterLayer) and l.isValid()]
    
    # Sortuj: najpierw RGB (3+ pasma), potem grayscale (1 pasmo)
    rgb_layers = sorted(
        [l.name() for l in raster_layers if l.bandCount() >= 3],
        key=lambda x: x.lower()
    )
    gray_layers = sorted(
        [l.name() for l in raster_layers if l.bandCount() == 1],
        key=lambda x: x.lower()
    )
    
    return rgb_layers + gray_layers


def show_processing_dialog():
    """
    Pokazuje dialog konfiguracji i uruchamia przetwarzanie
    Funkcja wywoływana automatycznie gdy skrypt jest załadowany
    """
    try:
        # Sprawdź czy QGIS jest dostępny
        if not IFACE_AVAILABLE or not iface:
            logger.log("❌ QGIS iface nie jest dostępne!")
            logger.log("   Uruchamiam w trybie bezpośrednim...")
            # Fallback - uruchom bez dialogu
            main(add_rgb_from_ortho=True)
            return
        
        logger.log("\n" + "="*80)
        logger.log("🚀 INICJALIZACJA PIPELINE PRZETWARZANIA CHMURY PUNKTÓW")
        logger.log("="*80)
        
        # Sprawdź RGB w aktywnej warstwie
        logger.log("\n🔍 Sprawdzam aktywną warstwę...")
        has_rgb, layer = detect_rgb_in_active_layer()
        
        if layer is None:
            QMessageBox.critical(
                None,
                "Błąd",
                "Nie można pobrać aktywnej warstwy!\n\n"
                "Upewnij się, że chmura punktów jest zaznaczona jako aktywna warstwa."
            )
            return
        
        logger.log(f"   Warstwa: {layer.name()}")
        logger.log(f"   RGB: {'✅ TAK' if has_rgb else '❌ NIE'}")
        
        # Pobierz dostępne ortofotomapy
        logger.log("\n🔍 Szukam dostępnych ortofotomap...")
        orthophotos = get_all_orthophotos()
        
        if orthophotos:
            logger.log(f"   Znaleziono {len(orthophotos)} ortofotomap:")
            for ortho in orthophotos:
                logger.log(f"      - {ortho}")
        else:
            logger.log("   ⚠️ Nie znaleziono ortofotomap w projekcie")
        
        # Pokaż dialog
        logger.log("\n📋 Pokazuję dialog konfiguracji...")
        dialog = PointCloudProcessingDialog(has_rgb, orthophotos)
        result = dialog.exec_()
        
        if result == QDialog.Accepted:
            logger.log("\n✅ Użytkownik zatwierdził - rozpoczynam przetwarzanie!")
            logger.log("="*80)
            
            # Uruchom przetwarzanie z wybranymi parametrami
            if dialog.should_add_rgb and dialog.selected_orthophoto:
                main(
                    add_rgb_from_ortho=True,
                    orthophoto_layer_name=dialog.selected_orthophoto
                )
            else:
                main(add_rgb_from_ortho=False)
        else:
            logger.log("\n❌ Użytkownik anulował przetwarzanie")
            logger.log("="*80)
            
    except Exception as e:
        logger.log(f"\n❌ BŁĄD w show_processing_dialog: {e}")
        import traceback
        logger.log(traceback.format_exc())
        
        if IFACE_AVAILABLE:
            QMessageBox.critical(
                None,
                "Błąd",
                f"Wystąpił błąd podczas inicjalizacji:\n\n{str(e)}"
            )


# ==================== AUTO-URUCHOMIENIE ====================

# Ten skrypt jest częścią wtyczki i uruchamiany przez exec()
# Po załadowaniu wszystkich definicji automatycznie pokazuje dialog
logger.log("\n" + "="*80)
logger.log("📦 SKRYPT ZAŁADOWANY - Uruchamiam dialog konfiguracji...")
logger.log("="*80)

show_processing_dialog()