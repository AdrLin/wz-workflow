import os
import processing
from qgis.core import (
    QgsProject, QgsField, QgsVectorLayer
)
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtCore import QVariant
from qgis.utils import iface

# Ścieżka do pliku stylu - zmień na swoją
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))
style_name = "style/granica obszaru analizowanego.qml"
STYL_PATH = os.path.join(SCRIPTS_PATH, style_name)
# STYL_PATH = "/home/adrian/Documents/JXPROJEKT/style/granica obszaru analizowanego.qml"

class FrontDzialkiController:
    def __init__(self):
        self.front_layer = None
        self.granica_terenu_layer = None
        self.line_measured = False
        self.front_length = 0.0
        
    def create_front_layer(self):
        """Tworzy warstwę liniową dla frontu działki"""
        # Tworzenie nowej warstwy wektorowej typu LineString
        self.front_layer = QgsVectorLayer('LineString?crs=EPSG:2180', 'front_dzialki', 'memory')
        
        if not self.front_layer.isValid():
            print("❌ Błąd: Nie udało się utworzyć warstwy front_dzialki!")
            return None
        
        # Pobieranie dostawcy danych warstwy
        provider = self.front_layer.dataProvider()
        
        # Dodawanie pola dla długości
        field_length = QgsField('dlugosc', QVariant.Double, 'double', 10, 2)
        provider.addAttributes([field_length])
        self.front_layer.updateFields()
        
        # Dodawanie warstwy do projektu
        QgsProject.instance().addMapLayer(self.front_layer)
        
        # Przełączenie warstwy w tryb edycji
        self.front_layer.startEditing()
        
        print(f"✅ Utworzono warstwę '{self.front_layer.name()}' w trybie edycji")
        return self.front_layer
    
    def setup_auto_measurement(self):
        """Konfiguruje automatyczne mierzenie i zamykanie edycji po narysowaniu linii"""
        if not self.front_layer:
            return
            
        length_field_index = self.front_layer.fields().indexFromName('dlugosc')
        
        if length_field_index == -1:
            print("❌ Błąd: Nie znaleziono pola 'dlugosc'")
            return
        
        def on_feature_added(feature_id):
            """Wywoływana po dodaniu nowej linii"""
            if self.front_layer.isEditable() and not self.line_measured:
                feature = self.front_layer.getFeature(feature_id)
                if feature.hasGeometry():
                    # Obliczanie długości geometrii
                    length = feature.geometry().length()
                    self.front_length = length
                    
                    # Aktualizacja pola długości
                    self.front_layer.changeAttributeValue(feature_id, length_field_index, round(length, 2))
                    
                    print(f"📏 Zmierzono front działki: {round(length, 2)} m")
                    self.line_measured = True
                    self.front_layer.featureAdded.disconnect(on_feature_added)  # 🔴 Odłącz sygnał
                    # Zapisanie zmian i zamknięcie trybu edycji
                    self.front_layer.commitChanges()
                    print("💾 Zapisano zmiany w warstwie front_dzialki")
                    
                    # Utworzenie otoczki
                    self.create_buffer()
        
        # Podłączanie sygnału
        self.front_layer.featureAdded.connect(on_feature_added)
        
        print("✅ Skonfigurowano automatyczne mierzenie frontu działki")
    
    def get_granica_terenu_layer(self):
        """Znajduje warstwę granica_terenu w projekcie"""
        warstwy = QgsProject.instance().mapLayersByName("granica_terenu")
        if warstwy:
            self.granica_terenu_layer = warstwy[0]
            print(f"✅ Znaleziono warstwę: {self.granica_terenu_layer.name()}")
            return True
        else:
            print("❌ Nie znaleziono warstwy 'granica_terenu'")
            return False
    
    def create_buffer(self):
        """Tworzy otoczkę wokół warstwy granica_terenu"""
        if not self.get_granica_terenu_layer():
            return
            
        if self.front_length <= 0:
            print("❌ Błąd: Długość frontu działki nie została zmierzona")
            return
        
        # Obliczenie promienia bufora (trzykrotność długości frontu)
        buffer_distance = self.front_length * 3
        if buffer_distance < 50:
            buffer_distance = 50
        elif buffer_distance >200:
            buffer_distance = 200
        print(f"🔧 Tworzenie otoczki z promieniem: {round(buffer_distance, 2)} m")
        
        # Przygotowanie ścieżki wyjściowej
        project_path = QgsProject.instance().fileName()
        project_directory = os.path.dirname(project_path)
        output_path = os.path.join(project_directory, "granica_obszaru_analizowanego.gpkg")
        
        # Parametry dla algorytmu Buffer
        params = {
            'INPUT': self.granica_terenu_layer,
            'DISTANCE': buffer_distance,
            'SEGMENTS': 5,
            'END_CAP_STYLE': 0,  # Round
            'JOIN_STYLE': 0,     # Round
            'MITER_LIMIT': 2,
            'DISSOLVE': False,
            'SEPARATE_DISJOINT': False,
            'OUTPUT': output_path
        }
        
        try:
            # Uruchomienie algorytmu
            print("🔄 Uruchamianie algorytmu 'Otoczka'...")
            result = processing.run("native:buffer", params)
            
            if result['OUTPUT']:
                print(f"✅ Utworzono otoczkę: {output_path}")
                
                # Wczytanie warstwy do projektu
                self.load_and_style_buffer(output_path)
            else:
                print("❌ Błąd podczas tworzenia otoczki")
                
        except Exception as e:
            print(f"❌ Błąd podczas uruchamiania algorytmu: {str(e)}")
    
    def load_and_style_buffer(self, gpkg_path):
        """Wczytuje warstwę otoczki do projektu i nadaje stylizację"""
        layer_name = "granica_obszaru_analizowanego"
        
        # Wczytanie warstwy
        buffer_layer = QgsVectorLayer(gpkg_path, layer_name, "ogr")
        
        if buffer_layer.isValid():
            # Dodanie do projektu
            QgsProject.instance().addMapLayer(buffer_layer)
            print(f"✅ Wczytano warstwę: {layer_name}")
            
            # Aplikacja stylu jeśli plik istnieje
            if os.path.exists(STYL_PATH):
                success, msg = buffer_layer.loadNamedStyle(STYL_PATH)
                if success:
                    buffer_layer.reload()
                    buffer_layer.triggerRepaint()
                    print("🎨 Stylizacja załadowana!")
                else:
                    print(f"⚠️ Błąd stylizacji: {msg}")
            else:
                print(f"⚠️ Nie znaleziono pliku stylu: {STYL_PATH}")
                
            # Odświeżenie mapy
            iface.mapCanvas().refresh()
            
        else:
            print("❌ Błąd wczytania warstwy otoczki")
    
    def start_process(self):
        """Rozpoczyna cały proces"""
        # Sprawdź czy warstwa granica_terenu istnieje
        if not self.get_granica_terenu_layer():
            QMessageBox.warning(
                None,
                "Błąd",
                "Nie znaleziono warstwy 'granica_terenu' w projekcie!"
            )
            return False
        
        # Usuń poprzednie warstwy front_dzialki jeśli istnieją
        self.remove_existing_front_layers()
        
        # Utwórz warstwę frontu działki
        if not self.create_front_layer():
            return False
            
        # Skonfiguruj automatyczne mierzenie
        self.setup_auto_measurement()
        
        # Ustaw jako aktywną warstwę
        iface.setActiveLayer(self.front_layer)
        
        return True
    
    def remove_existing_front_layers(self):
        """Usuwa istniejące warstwy front_dzialki"""
        layers_to_remove = []
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == "front_dzialki":
                layers_to_remove.append(layer.id())
        
        for layer_id in layers_to_remove:
            QgsProject.instance().removeMapLayer(layer_id)
            print("🗑️ Usunięto poprzednią warstwę front_dzialki")


# Globalna instancja kontrolera
front_controller = None

def uruchom_front_dzialki():
    """Główna funkcja uruchamiająca proces tworzenia frontu działki i otoczki"""
    global front_controller
    
    # Utwórz nowy kontroler
    front_controller = FrontDzialkiController()
    
    # Rozpocznij proces
    success = front_controller.start_process()
    
    if success:
        # Instrukcje dla użytkownika
        QMessageBox.information(
            None, 
            "Front działki", 
            "Proces rozpoczęty!\n\n"
            "Instrukcje:\n"
            "1. Warstwa 'front_dzialki' jest aktywna i w trybie edycji\n"
            "2. Użyj narzędzia 'Dodaj obiekt liniowy'\n"
            "3. Narysuj JEDNĄ linię reprezentującą front działki\n"
            "4. Linia zostanie automatycznie zmierzona\n"
            "5. Tryb edycji zamknie się automatycznie\n"
            "6. Utworzona zostanie otoczka z buforem 3x długość frontu\n\n"
            "UWAGA: Narysuj tylko JEDNĄ linię!"
        )
        
        print("🚀 Proces uruchomiony - możesz rysować front działki")
    else:
        print("❌ Nie udało się uruchomić procesu")

            
            
# Uruchomienie skryptu
uruchom_front_dzialki()
