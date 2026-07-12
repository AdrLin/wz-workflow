#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Aug  6 17:00:52 2025
Poprawiona wersja z zabezpieczeniami przed crashem

@author: adrian
"""

import os
import csv
import processing
from qgis.core import (
    QgsProject, QgsField, QgsVectorLayer, QgsFeature, QgsFields,
    QgsVectorFileWriter, QgsCoordinateTransformContext
)
from PyQt5.QtWidgets import ( QMessageBox
)
from qgis.PyQt.QtCore import QVariant
from qgis.utils import iface
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))


class DrawingController:
    def __init__(self):
        self.current_building_id = None
        self.drawing_layer = None
        self.buildings_layer = None
        self.current_building_index = 0  # Zmienione z iteratora na index
        self.buildings_list = []  # Lista wszystkich budynków
        self.measured_ids = set()
        self.csv_file = None
        self.csv_writer = None
        self.rubber_band = None
        
    def create_elewacja_layer(self):
        """Tworzy warstwę do rysowania szerokości elewacji z automatycznym obliczaniem długości"""
        try:
            # Tworzenie nowej warstwy wektorowej typu LineString
            self.drawing_layer = QgsVectorLayer('LineString?crs=EPSG:2177', 'szer_elew_front', 'memory')
            
            if not self.drawing_layer.isValid():
                print("❌ Błąd: Nie udało się utworzyć warstwy!")
                return None
            
            # Pobieranie dostawcy danych warstwy
            provider = self.drawing_layer.dataProvider()
            
            # Dodawanie pól
            fields = [
                QgsField('ID_BUDYNKU', QVariant.String),
                QgsField('dlugosc', QVariant.Double, 'double', 10, 2)
            ]
            provider.addAttributes(fields)
            self.drawing_layer.updateFields()
            
            # Dodawanie warstwy do projektu
            QgsProject.instance().addMapLayer(self.drawing_layer)
            
            # Przełączenie warstwy w tryb edycji
            self.drawing_layer.startEditing()
            
            print(f"✅ Utworzono warstwę '{self.drawing_layer.name()}' w trybie edycji")
            return self.drawing_layer
            
        except Exception as e:
            print(f"❌ Błąd podczas tworzenia warstwy: {e}")
            return None
    
    def setup_auto_length_calculation(self):
        """Konfiguruje automatyczne obliczanie długości i przypisywanie ID budynku"""
        if not self.drawing_layer or not self.drawing_layer.isValid():
            return
            
        try:
            # Znajdowanie indeksów pól
            id_field_index = self.drawing_layer.fields().indexFromName('ID_BUDYNKU')
            length_field_index = self.drawing_layer.fields().indexFromName('dlugosc')
            
            if id_field_index == -1 or length_field_index == -1:
                print("❌ Błąd: Nie znaleziono wymaganych pól")
                return
            
            # Sprawdź czy sygnały już są podłączone i odłącz je
            try:
                self.drawing_layer.featureAdded.disconnect()
                self.drawing_layer.geometryChanged.disconnect()
            except:
                pass  # Ignoruj jeśli nie były podłączone
            
            # Podłącz sygnały z zabezpieczeniami
            self.drawing_layer.featureAdded.connect(self.safe_on_feature_added)
            self.drawing_layer.geometryChanged.connect(self.safe_on_geometry_changed)
            
            print("✅ Skonfigurowano automatyczne obliczanie długości")
            
        except Exception as e:
            print(f"❌ Błąd podczas konfiguracji sygnałów: {e}")
    
    def safe_on_feature_added(self, feature_id):
        """Bezpieczna wersja obsługi dodania nowego obiektu"""
        try:
            if not self.drawing_layer or not self.drawing_layer.isValid():
                return
            if not self.drawing_layer.isEditable() or not self.current_building_id:
                return
            if not self.csv_writer or not self.csv_file:
                return
                
            feature = self.drawing_layer.getFeature(feature_id)
            if not feature.hasGeometry():
                return
            
            # Znajdowanie indeksów pól
            id_field_index = self.drawing_layer.fields().indexFromName('ID_BUDYNKU')
            length_field_index = self.drawing_layer.fields().indexFromName('dlugosc')
            
            if id_field_index == -1 or length_field_index == -1:
                return
            
           # Obliczanie długości geometrii
            length = feature.geometry().length()

            # Walidacja pomiaru
            MIN_SZEROKOSC = 2.0  # [m] — spójne z progiem w wczytaj_csv
            if length < MIN_SZEROKOSC:
                print(f"⚠️ Odrzucono pomiar {self.current_building_id}: "
                      f"{round(length, 2)} m — poniżej progu {MIN_SZEROKOSC} m (lub zero). "
                      f"Narysuj linię jeszcze raz.")
                # Usuń błędny obiekt z warstwy — zostaje podświetlony ten sam budynek
                self.drawing_layer.deleteFeature(feature_id)
                iface.messageBar().pushWarning(
                    "Błędny pomiar",
                    f"Szerokość {round(length, 2)} m jest nieprawidłowa. "
                    f"Narysuj linię elewacji ponownie (min. {MIN_SZEROKOSC} m)."
                )
                return  # NIE zapisuj, NIE przechod do next_building
            
            # Aktualizacja pól
            self.drawing_layer.changeAttributeValue(feature_id, id_field_index, self.current_building_id)
            self.drawing_layer.changeAttributeValue(feature_id, length_field_index, round(length, 2))
            
            # Zapisz do CSV
            self.csv_writer.writerow([self.current_building_id, round(length, 2)])
            self.csv_file.flush()
            
            # Dodaj do zmierzonych
            self.measured_ids.add(self.current_building_id)
            
            print(f"📏 Zapisano: {self.current_building_id} → {round(length, 2)} m")
            
            # Przejdź do kolejnego budynku
            self.next_building()
            
        except Exception as e:
            print(f"❌ Błąd w safe_on_feature_added: {e}")
    
    def safe_on_geometry_changed(self, feature_id, geometry):
        """Bezpieczna wersja obsługi zmiany geometrii"""
        try:
            if not self.drawing_layer or not self.drawing_layer.isValid():
                return
            if not self.drawing_layer.isEditable() or not geometry:
                return
            
            # Znajdowanie indeksu pola długości
            length_field_index = self.drawing_layer.fields().indexFromName('dlugosc')
            if length_field_index == -1:
                return
            
            # Obliczanie nowej długości
            length = geometry.length()
            # Aktualizacja pola długości
            self.drawing_layer.changeAttributeValue(feature_id, length_field_index, round(length, 2))
            print(f"🔄 Zaktualizowano długość: {round(length, 2)} m")
            
        except Exception as e:
            print(f"❌ Błąd w safe_on_geometry_changed: {e}")
    
    def start_measurement_process(self):
        """Rozpoczyna proces mierzenia budynków"""
        try:
            # Wczytanie warstwy budynków
            self.buildings_layer = self.wczytaj_warstwe("budynki_zgodne_z_funkcja")
            if not self.buildings_layer:
                print("❌ Brak warstwy wejściowej.")
                return False
            
            # Przygotowanie listy budynków (bezpieczniejsze niż iterator)
            self.buildings_list = list(self.buildings_layer.getFeatures())
            self.current_building_index = 0
            
            # Przygotowanie ścieżek plików
            project_path = QgsProject.instance().fileName()
            if not project_path:
                print("❌ Projekt nie został zapisany. Zapisz projekt przed uruchomieniem.")
                return False
                
            project_directory = os.path.dirname(project_path)
            csv_path = os.path.join(project_directory, "budynki_szer_elew_front.csv")
            
            # Wczytanie już zmierzonych budynków
            self.measured_ids = self.wczytaj_csv(csv_path)
            
            # Przygotowanie writera CSV
            self.csv_file, self.csv_writer = self.przygotuj_writer(csv_path)
            if not self.csv_file or not self.csv_writer:
                return False
            
            # Utworzenie warstwy do rysowania
            if not self.create_elewacja_layer():
                return False
                
            # Konfiguracja automatycznego obliczania
            self.setup_auto_length_calculation()
            
            # Ustawienie aktywnej warstwy
            iface.setActiveLayer(self.drawing_layer)
            
            # Przejście do pierwszego budynku
            self.next_building()
            
            print("🚀 Rozpoczęto proces rysowania elewacji")
            return True
            
        except Exception as e:
            print(f"❌ Błąd podczas uruchamiania procesu: {e}")
            return False
    
    def wczytaj_warstwe(self, nazwa):
        """Bezpieczniejsze wczytywanie warstw"""
        try:
            warstwy = QgsProject.instance().mapLayersByName(nazwa)
            if not warstwy:
                print(f"❌ Nie znaleziono warstwy: {nazwa}")
                return None
            
            layer = warstwy[0]
            if not layer.isValid():
                print(f"❌ Warstwa {nazwa} jest nieprawidłowa")
                return None
                
            return layer
        except Exception as e:
            print(f"❌ Błąd wczytywania warstwy {nazwa}: {e}")
            return None
    
    def wczytaj_csv(self, path):
        """Bezpieczne wczytywanie CSV — pomija rekordy z brakiem lub podejrzaną szerokością"""
        budynki = set()
        MIN_SZEROKOSC = 2.0  # [m] — budynki poniżej tego progu wymagają ponownego pomiaru
        try:
            if os.path.exists(path):
                with open(path, newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if 'ID_BUDYNKU' not in row:
                            continue
                        building_id = row['ID_BUDYNKU']
                        szerokosc_str = row.get('szer_elew_front', '').strip()
                        try:
                            szerokosc = float(szerokosc_str)
                        except (ValueError, TypeError):
                            szerokosc = None
    
                        if szerokosc is not None and szerokosc >= MIN_SZEROKOSC:
                            budynki.add(building_id)
                        else:
                            print(f"⚠️ Budynek {building_id}: "
                                  f"szerokość '{szerokosc_str}' → wymaga ponownego pomiaru")
        except Exception as e:
            print(f"❌ Błąd wczytywania CSV: {e}")
        return budynki
    
    def przygotuj_writer(self, path):
        """Bezpieczniejsze zarządzanie plikami"""
        try:
            nowy_plik = not os.path.exists(path) or os.stat(path).st_size == 0
            file = open(path, mode='a', newline='', encoding='utf-8')
            writer = csv.writer(file)
            if nowy_plik:
                writer.writerow(["ID_BUDYNKU", "szer_elew_front"])
            return file, writer
        except Exception as e:
            print(f"❌ Błąd otwierania pliku CSV: {e}")
            return None, None
    
    def next_building(self):
        """Bezpieczniejsze przechodzenie do kolejnego budynku"""
        try:
            # Znajdź następny niezmierzony budynek
            while self.current_building_index < len(self.buildings_list):
                feature = self.buildings_list[self.current_building_index]
                building_id = feature["ID_BUDYNKU"]
                
                self.current_building_index += 1
                
                if building_id not in self.measured_ids:
                    self.current_building_id = building_id
                    self.highlight_building(feature)
                    print(f"🏢 Budynek do zmierzenia: {building_id}")
                    return
                else:
                    print(f"⏭️ Budynek {building_id} już zmierzony — pomijam.")
            
            # Koniec budynków - zakończ proces
            self.finish_measurement()
            
        except Exception as e:
            print(f"❌ Błąd w next_building: {e}")
            self.finish_measurement()
    
    def highlight_building(self, feature):
        """Podświetla budynek używając rubber band (bardziej widoczne)"""
        try:
            from qgis.gui import QgsRubberBand
            from qgis.core import QgsWkbTypes
            from PyQt5.QtGui import QColor
            
            if not self.buildings_layer or not self.buildings_layer.isValid():
                return
            
            building_id = feature["ID_BUDYNKU"]
            
            # Usuń poprzedni rubber band jeśli istnieje
            if hasattr(self, 'rubber_band') and self.rubber_band:
                self.rubber_band.reset()
            
            # Stwórz nowy rubber band (żółta obwódka)
            self.rubber_band = QgsRubberBand(iface.mapCanvas(), QgsWkbTypes.PolygonGeometry)
            self.rubber_band.setColor(QColor(255, 255, 0, 100))  # Żółty z przezroczystością
            self.rubber_band.setWidth(5)
            self.rubber_band.setToGeometry(feature.geometry(), self.buildings_layer)
            
            # Przybliż do budynku
            bbox = feature.geometry().boundingBox()
            bbox.scale(1.5)
            iface.mapCanvas().setExtent(bbox)
            iface.mapCanvas().refresh()
            
            # Komunikat
            iface.messageBar().pushInfo(
                "Rysowanie elewacji", 
                f"Budynek {building_id} - narysuj linię elewacji frontowej"
            )
            
            # Ustaw warstwę rysunkową jako aktywną
            iface.setActiveLayer(self.drawing_layer)
            
            print(f"✅ Podświetlono budynek {building_id}")
            
        except Exception as e:
            print(f"❌ Błąd podczas podświetlania: {e}")
            import traceback
            traceback.print_exc()
    
    def finish_measurement(self):
        """Poprawione czyszczenie zasobów z debugowaniem"""
        try:
            print("🔄 Kończenie pomiarów...")
            
            # Zamknij plik CSV
            print("🔄 Zamykanie pliku CSV...")
            if hasattr(self, 'csv_file') and self.csv_file:
                self.csv_file.close()
                self.csv_file = None
                self.csv_writer = None
            print("✅ Plik CSV zamknięty")
            if hasattr(self, 'rubber_band') and self.rubber_band:
                self.rubber_band.reset()
                self.rubber_band = None
            # Odłącz sygnały - NAJPIERW!
            print("🔄 Odłączanie sygnałów...")
            if self.drawing_layer and self.drawing_layer.isValid():
                try:
                    self.drawing_layer.featureAdded.disconnect()
                    self.drawing_layer.geometryChanged.disconnect()
                    print("✅ Sygnały odłączone")
                except Exception as signal_error:
                    print(f"⚠️ Problem z odłączaniem sygnałów: {signal_error}")
                
                # Zakończ edycję warstwy
                print("🔄 Zakończenie edycji warstwy...")
                if self.drawing_layer.isEditable():
                    self.drawing_layer.commitChanges()
                    print("✅ Zmiany zapisane w warstwie")
            
            # Wyczyść zaznaczenie
            print("🔄 Czyszczenie zaznaczenia...")
            if self.buildings_layer and self.buildings_layer.isValid():
                self.buildings_layer.removeSelection()
                print("✅ Zaznaczenie wyczyszczone")
            
            # Wyczyść referencje
            print("🔄 Czyszczenie referencji...")
            self.buildings_list = []
            self.current_building_index = 0
            self.current_building_id = None
            print("✅ Referencje wyczyszczone")
            
            print("✅ Zakończono pomiary elewacji")
            
            # BEZPIECZNE wywołanie messageBar
            try:
                iface.messageBar().pushSuccess("Zakończono", "Wszystkie budynki zostały zmierzone!")
            except Exception as msg_error:
                print(f"⚠️ Problem z messageBar: {msg_error}")
            
            # ODŁÓŻ łączenie danych - zrób to później lub wcale
            print("🔄 Rozpoczynam łączenie danych...")
            # Zamiast od razu wywoływać, dodaj opóźnienie
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(1000, self.safe_join_and_save_results)
            
        except Exception as e:
            print(f"❌ Błąd podczas zakończenia: {e}")
            import traceback
            traceback.print_exc()
    
    def safe_join_and_save_results(self):
        """Stabilna wersja łączenia danych - proven to work!"""
        try:
            print("🔄 Rozpoczynanie łączenia danych...")
            
            project_path = QgsProject.instance().fileName()
            project_directory = os.path.dirname(project_path)
            csv_path = os.path.join(project_directory, "budynki_szer_elew_front.csv")
            
            # Wczytaj CSV do memory
            print("🔄 Wczytywanie CSV do warstwy memory...")
            warstwa_pomiarowa = self.wczytaj_warstwe_csv_do_memory(csv_path, "budynki_szer_elew_front")
            if not warstwa_pomiarowa:
                print("❌ Nie udało się wczytać danych pomiarowych")
                return
            
            # Małe opóźnienie dla stabilności
            from qgis.PyQt.QtCore import QTimer, QEventLoop
            loop = QEventLoop()
            QTimer.singleShot(300, loop.quit)
            loop.exec_()
            
            # Połącz dane
            print("🔄 Łączenie danych...")
            joined_layer = self.dolacz_pomiary_stable(self.buildings_layer, warstwa_pomiarowa)
            if not joined_layer:
                print("❌ Nie udało się połączyć danych")
                return
            
            # Małe opóźnienie
            loop = QEventLoop()
            QTimer.singleShot(300, loop.quit)
            loop.exec_()
            
            # Zapisz i stylizuj
            print("🔄 Zapisywanie i stylizacja...")
            style_name = "style/budynki_do_analizy.qml"
            styl_path = os.path.join(SCRIPTS_PATH, style_name)
            # styl_path = "/home/adrian/Documents/JXPROJEKT/style/budynki_do_analizy.qml"
            gpkg_path = os.path.join(project_directory, "budynki_z_szer_elew_front.gpkg")
            layer_name = "budynki_z_szer_elew_front"
            
            self.stylizuj_i_zapisz_stable(joined_layer, styl_path, gpkg_path, layer_name)
            
            # Wyczyść memory layers
            remove_memory_layers()
            
            print("🎉 Proces zakończony pomyślnie!")
            
            try:
                iface.messageBar().pushSuccess(
                    "Zakończono", 
                    f"Warstwa zapisana jako: {layer_name}.gpkg"
                )
            except:
                print("✅ Warstwa zapisana pomyślnie")
            QMessageBox.information(
                None, 
                "Wymiarowanie frontu działki i promienia obszaru analizy", 
                "Proces rozpoczęty!\n\n"
                "Instrukcje:\n"
                "1. Po dokonaniu pomiarów elewacji frontowych pobierz chmurę punktów dla projektu.\n"
                "2. Ustaw chmurę jako aktywną warstwę przed kliknięciem 'Dalej'\n"
                )
        except Exception as e:
            print(f"❌ Błąd w safe_join_and_save_results: {e}")
            import traceback
            traceback.print_exc()
    
    def wczytaj_warstwe_csv_do_memory(self, path, nazwa_layer):
        """Bezpieczne wczytywanie CSV do warstwy memory"""
        try:
            if not os.path.exists(path):
                print(f"❌ Plik CSV nie istnieje: {path}")
                return None
                
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                if not fieldnames:
                    print("❌ Plik CSV jest pusty lub uszkodzony")
                    return None
                    
                fields = QgsFields()
                for name in fieldnames:
                    if name != "id":
                        # Sprawdź czy pole to szer_elew_front i ustaw typ Double
                        if name == "szer_elew_front":
                            fields.append(QgsField(name, QVariant.Double))
                        else:
                            fields.append(QgsField(name, QVariant.String))
                        
                memory_layer = QgsVectorLayer("None", nazwa_layer, "memory")
                memory_layer.dataProvider().addAttributes(fields)
                memory_layer.updateFields()
                
                # Deduplikacja: dla każdego ID_BUDYNKU zostaw OSTATNI (najnowszy) wpis
                # Append mode w CSV powoduje, że poprawny pomiar jest na końcu, zły na początku
                rows_by_id = {}
                for row in reader:
                    building_id = row.get('ID_BUDYNKU', '').strip()
                    if building_id:
                        rows_by_id[building_id] = row  # nadpisuje poprzedni — ostatni wygrywa

                features = []
                for row in rows_by_id.values():
                    feat = QgsFeature()
                    feat.initAttributes(len(fields))
                    for i, name in enumerate(fieldnames):
                        if name != "id":
                            value = row[name]
                            if name == "szer_elew_front":
                                try:
                                    value = float(value) if value and value.strip() else None
                                except ValueError:
                                    value = None
                            feat[i] = value
                    features.append(feat)
                    
                memory_layer.dataProvider().addFeatures(features)
                memory_layer.updateExtents()
                QgsProject.instance().addMapLayer(memory_layer)
                return memory_layer
                
        except Exception as e:
            print(f"❌ Błąd wczytywania CSV do memory: {e}")
            return None

    def dolacz_pomiary_stable(self, warstwa_bazowa, warstwa_pomiarowa):
        """Stabilna wersja łączenia danych"""
        try:
            params = {
                'INPUT': warstwa_bazowa,
                'FIELD': 'ID_BUDYNKU',
                'INPUT_2': warstwa_pomiarowa,
                'FIELD_2': 'ID_BUDYNKU',
                'FIELDS_TO_COPY': ['szer_elew_front'],
                'METHOD': 1,
                'DISCARD_NONMATCHING': False,
                'PREFIX': '',
                'OUTPUT': 'memory:budynki_z_szer_elew_front'
            }
            
            wynik = processing.run("native:joinattributestable", params)['OUTPUT']
            QgsProject.instance().addMapLayer(wynik)
            print("🔗 Dane pomiarowe dołączone.")
            return wynik
            
        except Exception as e:
            print(f"❌ Błąd łączenia danych: {e}")
            return None

    def stylizuj_i_zapisz_stable(self, layer, styl_path, output_path, layer_name):
        """Stabilna wersja stylizowania i zapisywania"""
        try:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = 'GPKG'
            options.fileEncoding = 'UTF-8'
            options.layerName = layer_name
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, output_path, QgsCoordinateTransformContext(), options
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                print(f"❌ Błąd zapisu: {error[1]}")
                return
            
            final_layer = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
            if final_layer.isValid():
                QgsProject.instance().addMapLayer(final_layer)
                if os.path.exists(styl_path):
                    success, msg = final_layer.loadNamedStyle(styl_path)
                    if success:
                        final_layer.reload()
                        final_layer.triggerRepaint()
                        print("🎨 Stylizacja załadowana!")
                    else:
                        print(f"⚠️ Problem ze stylizacją: {msg}")
                else:
                    print("⚠️ Plik stylu nie istnieje, pomijam stylizację")
                print("✅ Warstwa zapisana i dodana do projektu")
            else:
                print("❌ Błąd wczytania zapisanej warstwy.")
                
        except Exception as e:
            print(f"❌ Błąd podczas stylizowania i zapisu: {e}")


# Globalna instancja kontrolera
drawing_controller = None

def uruchom_rysowanie_elewacji():
    """Główna funkcja uruchamiająca proces rysowania elewacji"""
    global drawing_controller
    
    try:
        print("🔄 Uruchamianie procesu rysowania elewacji...")
        
        # Usuń poprzednie warstwy memory jeśli istnieją
        print("🔄 Usuwanie poprzednich warstw memory...")
        remove_memory_layers()
        
        # Utwórz nowy kontroler
        print("🔄 Tworzenie nowego kontrolera...")
        drawing_controller = DrawingController()
        
        # Rozpocznij proces
        print("🔄 Rozpoczynanie procesu mierzenia...")
        success = drawing_controller.start_measurement_process()
        
        if success:
            print("✅ Proces uruchomiony pomyślnie")
            # Instrukcje dla użytkownika
            try:
                QMessageBox.information(
                    None, 
                    "Rysowanie elewacji", 
                    "Proces rozpoczęty!\n\n"
                    "Instrukcje:\n"
                    "1. Warstwa 'szer_elew_front' jest już aktywna i w trybie edycji\n"
                    "2. Użyj narzędzia 'Dodaj obiekt liniowy' (F2)\n"
                    "3. Narysuj linię szerokości elewacji frontowej\n"
                    "4. Linia zostanie automatycznie zmierzona i zapisana\n"
                    "5. Automatycznie przejdziesz do kolejnego budynku\n"
                    "6. Powtarzaj aż do końca"
                )
            except Exception as dialog_error:
                print(f"⚠️ Problem z dialogiem informacyjnym: {dialog_error}")
        else:
            print("❌ Nie udało się uruchomić procesu")
            try:
                QMessageBox.warning(None, "Błąd", "Nie udało się uruchomić procesu rysowania!")
            except Exception as dialog_error:
                print(f"⚠️ Problem z dialogiem błędu: {dialog_error}")
            
    except Exception as e:
        print(f"❌ Błąd w uruchom_rysowanie_elewacji: {e}")
        import traceback
        traceback.print_exc()
        try:
            QMessageBox.critical(None, "Błąd krytyczny", f"Wystąpił błąd: {str(e)}")
        except:
            print("❌ Nie można wyświetlić dialogu błędu")

def remove_memory_layers():
    """Usuwa warstwy tymczasowe z pamięci"""
    try:
        layers_to_remove = []
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.dataProvider().name() == 'memory':
                layers_to_remove.append(lyr.id())
        
        for layer_id in layers_to_remove:
            QgsProject.instance().removeMapLayer(layer_id)
            
    except Exception as e:
        print(f"❌ Błąd usuwania warstw memory: {e}")

def nastepny_budynek():
    """Funkcja pomocnicza do ręcznego przechodzenia do kolejnego budynku"""
    global drawing_controller
    try:
        if drawing_controller:
            drawing_controller.next_building()
        else:
            print("❌ Kontroler nie jest zainicjalizowany")
    except Exception as e:
        print(f"❌ Błąd w nastepny_budynek: {e}")

def zakoncz_pomiary_bezpiecznie():
    """Bezpieczna wersja kończenia pomiarów - tylko zapisanie CSV"""
    global drawing_controller
    try:
        if not drawing_controller:
            print("❌ Kontroler nie jest zainicjalizowany")
            return
            
        print("🔄 Bezpieczne kończenie pomiarów...")
        
        # Zamknij plik CSV
        if hasattr(drawing_controller, 'csv_file') and drawing_controller.csv_file:
            drawing_controller.csv_file.close()
            drawing_controller.csv_file = None
            drawing_controller.csv_writer = None
            print("✅ Plik CSV zamknięty")
        
        # Odłącz sygnały
        if (drawing_controller.drawing_layer and 
            drawing_controller.drawing_layer.isValid()):
            try:
                drawing_controller.drawing_layer.featureAdded.disconnect()
                drawing_controller.drawing_layer.geometryChanged.disconnect()
                print("✅ Sygnały odłączone")
            except:
                pass
                
            if drawing_controller.drawing_layer.isEditable():
                drawing_controller.drawing_layer.commitChanges()
                print("✅ Zmiany zapisane w warstwie")
        
        # Wyczyść zaznaczenie
        if (drawing_controller.buildings_layer and 
            drawing_controller.buildings_layer.isValid()):
            drawing_controller.buildings_layer.removeSelection()
            print("✅ Zaznaczenie wyczyszczone")
        
        print("✅ Pomiary zakończone bezpiecznie. Dane w CSV.")
        print("ℹ️ Łączenie danych zostało pominięte aby uniknąć crashu.")
        
    except Exception as e:
        print(f"❌ Błąd w zakoncz_pomiary_bezpiecznie: {e}")
        import traceback
        traceback.print_exc()


# Uruchomienie skryptu
uruchom_rysowanie_elewacji()