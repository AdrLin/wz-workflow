#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skrypt do pomiaru linii zabudowy w QGIS
Tworzy warstwę liniową z automatycznym obliczaniem długości

@author: adrian
"""

from qgis.core import (
    QgsProject, QgsField, QgsVectorLayer, QgsFeature, QgsFields,
    QgsVectorFileWriter, QgsCoordinateTransformContext
)
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtCore import QVariant
from qgis.utils import iface


class LineMeasurementController:
    def __init__(self):
        self.measurement_layer = None
        
    def create_line_layer(self):
        """Tworzy warstwę do rysowania linii zabudowy z automatycznym obliczaniem długości"""
        try:
            # Tworzenie nowej warstwy wektorowej typu LineString
            self.measurement_layer = QgsVectorLayer('LineString?crs=EPSG:2177', 'linie_zabudowy', 'memory')
            
            if not self.measurement_layer.isValid():
                print("❌ Błąd: Nie udało się utworzyć warstwy!")
                return None
            
            # Pobieranie dostawcy danych warstwy
            provider = self.measurement_layer.dataProvider()
            
            # Dodawanie pola distance
            fields = [
                QgsField('distance', QVariant.Double, 'double', 10, 2)
            ]
            provider.addAttributes(fields)
            self.measurement_layer.updateFields()
            
            # Dodawanie warstwy do projektu
            QgsProject.instance().addMapLayer(self.measurement_layer)
            
            # Przełączenie warstwy w tryb edycji
            self.measurement_layer.startEditing()
            
            print(f"✅ Utworzono warstwę '{self.measurement_layer.name()}' w trybie edycji")
            return self.measurement_layer
            
        except Exception as e:
            print(f"❌ Błąd podczas tworzenia warstwy: {e}")
            return None
    
    def setup_auto_length_calculation(self):
        """Konfiguruje automatyczne obliczanie długości linii"""
        if not self.measurement_layer or not self.measurement_layer.isValid():
            return
            
        try:
            # Znajdowanie indeksu pola distance
            distance_field_index = self.measurement_layer.fields().indexFromName('distance')
            
            if distance_field_index == -1:
                print("❌ Błąd: Nie znaleziono pola 'distance'")
                return
            
            # Sprawdź czy sygnały już są podłączone i odłącz je
            try:
                self.measurement_layer.featureAdded.disconnect()
                self.measurement_layer.geometryChanged.disconnect()
            except Exception:
                pass  # nosec B110 - celowe: sygnal moze nie byc podlaczony
            
            # Podłącz sygnały z zabezpieczeniami
            self.measurement_layer.featureAdded.connect(self.safe_on_feature_added)
            self.measurement_layer.geometryChanged.connect(self.safe_on_geometry_changed)
            
            print("✅ Skonfigurowano automatyczne obliczanie długości")
            
        except Exception as e:
            print(f"❌ Błąd podczas konfiguracji sygnałów: {e}")
    
    def safe_on_feature_added(self, feature_id):
        """Bezpieczna wersja obsługi dodania nowego obiektu"""
        try:
            if not self.measurement_layer or not self.measurement_layer.isValid():
                return
            if not self.measurement_layer.isEditable():
                return
                
            feature = self.measurement_layer.getFeature(feature_id)
            if not feature.hasGeometry():
                return
            
            # Znajdowanie indeksu pola distance
            distance_field_index = self.measurement_layer.fields().indexFromName('distance')
            
            if distance_field_index == -1:
                return
            
            # Obliczanie długości geometrii
            length = feature.geometry().length()
            
            # Aktualizacja pola distance
            self.measurement_layer.changeAttributeValue(feature_id, distance_field_index, round(length, 2))
            
            print(f"📏 Dodano linię o długości: {round(length, 2)} m")
            
        except Exception as e:
            print(f"❌ Błąd w safe_on_feature_added: {e}")
    
    def safe_on_geometry_changed(self, feature_id, geometry):
        """Bezpieczna wersja obsługi zmiany geometrii"""
        try:
            if not self.measurement_layer or not self.measurement_layer.isValid():
                return
            if not self.measurement_layer.isEditable() or not geometry:
                return
            
            # Znajdowanie indeksu pola distance
            distance_field_index = self.measurement_layer.fields().indexFromName('distance')
            if distance_field_index == -1:
                return
            
            # Obliczanie nowej długości
            length = geometry.length()
            # Aktualizacja pola distance
            self.measurement_layer.changeAttributeValue(feature_id, distance_field_index, round(length, 2))
            print(f"🔄 Zaktualizowano długość: {round(length, 2)} m")
            
        except Exception as e:
            print(f"❌ Błąd w safe_on_geometry_changed: {e}")
    
    def start_measurement_process(self):
        """Rozpoczyna proces mierzenia linii zabudowy"""
        try:
            # Utworzenie warstwy do rysowania
            if not self.create_line_layer():
                return False
                
            # Konfiguracja automatycznego obliczania
            self.setup_auto_length_calculation()
            
            # Ustawienie aktywnej warstwy
            iface.setActiveLayer(self.measurement_layer)
            
            print("🚀 Rozpoczęto proces rysowania linii zabudowy")
            return True
            
        except Exception as e:
            print(f"❌ Błąd podczas uruchamiania procesu: {e}")
            return False
    
    def finish_measurement(self):
        """Zakończenie procesu mierzenia"""
        try:
            print("🔄 Kończenie pomiarów...")
            
            # Odłącz sygnały
            print("🔄 Odłączanie sygnałów...")
            if self.measurement_layer and self.measurement_layer.isValid():
                try:
                    self.measurement_layer.featureAdded.disconnect()
                    self.measurement_layer.geometryChanged.disconnect()
                    print("✅ Sygnały odłączone")
                except Exception as signal_error:
                    print(f"⚠️ Problem z odłączaniem sygnałów: {signal_error}")
                
                # Zakończ edycję warstwy
                print("🔄 Zakończenie edycji warstwy...")
                if self.measurement_layer.isEditable():
                    self.measurement_layer.commitChanges()
                    print("✅ Zmiany zapisane w warstwie")
            
            print("✅ Zakończono pomiary linii zabudowy")
            
            try:
                iface.messageBar().pushSuccess("Zakończono", "Pomiary linii zabudowy zostały zapisane!")
            except Exception as msg_error:
                print(f"⚠️ Problem z messageBar: {msg_error}")
            
        except Exception as e:
            print(f"❌ Błąd podczas zakończenia: {e}")
            import traceback
            traceback.print_exc()


# Globalna instancja kontrolera
line_controller = None

def uruchom_pomiar_linii():
    """Główna funkcja uruchamiająca proces pomiaru linii zabudowy"""
    global line_controller
    
    try:
        print("🔄 Uruchamianie procesu pomiaru linii zabudowy...")
        
        # Utwórz nowy kontroler
        print("🔄 Tworzenie nowego kontrolera...")
        line_controller = LineMeasurementController()
        
        # Rozpocznij proces
        print("🔄 Rozpoczynanie procesu mierzenia...")
        success = line_controller.start_measurement_process()
        
        if success:
            print("✅ Proces uruchomiony pomyślnie")
            # Instrukcje dla użytkownika
            try:
                QMessageBox.information(
                    None, 
                    "Pomiar linii zabudowy", 
                    "Proces rozpoczęty!\n\n"
                    "Instrukcje:\n"
                    "1. Warstwa 'linie_zabudowy' jest już aktywna i w trybie edycji\n"
                    "2. Użyj narzędzia 'Dodaj obiekt liniowy' (F2)\n"
                    "3. Narysuj linię zabudowy\n"
                    "4. Długość zostanie automatycznie obliczona i zapisana w polu 'distance'\n"
                    "5. Możesz rysować kolejne linie według potrzeby\n"
                    "6. Zakończ edycję gdy skończysz (Ctrl+S lub kliknij 'Zapisz zmiany')"
                )
            except Exception as dialog_error:
                print(f"⚠️ Problem z dialogiem informacyjnym: {dialog_error}")
        else:
            print("❌ Nie udało się uruchomić procesu")
            try:
                QMessageBox.warning(None, "Błąd", "Nie udało się uruchomić procesu pomiaru!")
            except Exception as dialog_error:
                print(f"⚠️ Problem z dialogiem błędu: {dialog_error}")
            
    except Exception as e:
        print(f"❌ Błąd w uruchom_pomiar_linii: {e}")
        import traceback
        traceback.print_exc()
        try:
            QMessageBox.critical(None, "Błąd krytyczny", f"Wystąpił błąd: {str(e)}")
        except:
            print("❌ Nie można wyświetlić dialogu błędu")

def zakoncz_pomiar_linii():
    """Funkcja do ręcznego zakończenia procesu pomiaru"""
    global line_controller
    try:
        if line_controller:
            line_controller.finish_measurement()
            line_controller = None
        else:
            print("❌ Kontroler nie jest zainicjalizowany")
    except Exception as e:
        print(f"❌ Błąd w zakoncz_pomiar_linii: {e}")

# Uruchomienie skryptu
uruchom_pomiar_linii()