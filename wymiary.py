from qgis.core import (QgsVectorLayer, QgsField, QgsProject)
from qgis.PyQt.QtCore import QVariant
from qgis.utils import iface
from PyQt5.QtWidgets import QMessageBox


def create_wymiary_layer():
    """
    Tworzy nową warstwę wektorową 'wymiary' z geometrią liniową
    i polem 'l' do automatycznego obliczania długości linii
    """
    
    # Tworzenie nowej warstwy wektorowej typu LineString
    layer = QgsVectorLayer('LineString?crs=EPSG:2180', 'wymiary', 'memory')
    
    # Sprawdzenie czy warstwa została poprawnie utworzona
    if not layer.isValid():
        print("Błąd: Nie udało się utworzyć warstwy!")
        return None
    
    # Pobieranie dostawcy danych warstwy
    provider = layer.dataProvider()
    
    # Dodawanie pola 'l' typu rzeczywistego (double) do przechowywania długości
    field_l = QgsField('l', QVariant.Double, 'double', 10, 3)
    provider.addAttributes([field_l])
    layer.updateFields()
    
    # Dodawanie warstwy do projektu
    QgsProject.instance().addMapLayer(layer)
    
    # Przełączenie warstwy w tryb edycji
    layer.startEditing()
    
    print(f"Utworzono warstwę '{layer.name()}' w trybie edycji")
    print(f"Pola warstwy: {[field.name() for field in layer.fields()]}")
    
    return layer

def setup_auto_length_calculation(layer):
    """
    Konfiguruje automatyczne obliczanie długości dla pola 'l'
    """
    # Znajdowanie indeksu pola 'l'
    l_field_index = layer.fields().indexFromName('l')
    
    if l_field_index == -1:
        print("Błąd: Nie znaleziono pola 'l'")
        return
    
    # Funkcja wywoływana po dodaniu obiektu
    def on_feature_added(feature_id):
        if layer.isEditable():
            feature = layer.getFeature(feature_id)
            if feature.hasGeometry():
                # Obliczanie długości geometrii
                length = feature.geometry().length()
                # Aktualizacja pola 'l'
                layer.changeAttributeValue(feature_id, l_field_index, round(length))
    
    # Funkcja wywoływana po zmianie geometrii
    def on_geometry_changed(feature_id, geometry):
        if layer.isEditable() and geometry:
            # Obliczanie nowej długości
            length = geometry.length()
            # Aktualizacja pola 'l'
            layer.changeAttributeValue(feature_id, l_field_index, round(length))
    
    # Podłączanie sygnałów do automatycznego obliczania długości
    layer.featureAdded.connect(on_feature_added)
    layer.geometryChanged.connect(on_geometry_changed)
    
    print("Skonfigurowano automatyczne obliczanie długości linii")

QMessageBox.information(
    None, 
    "Wymiarowanie frontu działki i promienia obszaru analizy", 
    "Proces rozpoczęty!\n\n"
    "Instrukcje:\n"
    "1. Warstwa 'granica_obszaru_analizowanego' jest już aktywna i w trybie edycji\n"
    "2. Użyj narzędzia 'Dodaj obiekt liniowy'\n"
    "3. Narysuj linię wymiarowe\n"
    "4. Długość zostanie automatycznie obliczona i zapisana\n"
    "5. Możesz rysować kolejne linie według potrzeby\n"
    "6. Zakończ edycję gdy skończysz (Ctrl+S lub kliknij 'Zapisz wymiary')"
) 
# Główne wykonanie skryptu
 # Tworzenie warstwy
wymiary_layer = create_wymiary_layer()
    
if wymiary_layer:
    # Konfiguracja automatycznego obliczania długości
    setup_auto_length_calculation(wymiary_layer)
        
    # Ustawienie aktywnej warstwy w interfejsie
    iface.setActiveLayer(wymiary_layer)
        
    print("Warstwa 'wymiary' jest gotowa do użycia!")
    print("Możesz teraz rysować linie - długości będą obliczane automatycznie w polu 'l'")
else:
    print("Nie udało się utworzyć warstwy")
   