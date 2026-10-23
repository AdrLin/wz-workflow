#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Jul 19 09:24:57 2025
NAPRAWIONY - dodano walidację join i lepsze logowanie

@author: adrian
"""

import csv
import os
from qgis.core import (QgsProject, QgsVectorLayer, QgsFeature, 
                       Qgis,QgsMessageLog,
    QgsFields, QgsField, QgsVectorFileWriter, 
    QgsCoordinateTransformContext)
from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QComboBox, QPushButton, QLabel, QHBoxLayout, QLineEdit
import processing
from pathlib import Path
from qgis.PyQt.QtCore import QVariant
import time
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QMessageBox, QFileDialog

# Ścieżka do pliku CSV
project_path = QgsProject.instance().fileName()
project_directory = Path(project_path).parent
csv_file = os.path.join(project_directory, "klasyfikacja_dachow.csv")
nazwa_pola = "ID_BUDYNKU"
kategorie = ["płaski", "jednospadowy", "dwuspadowy", "czterospadowy", "wielospadowy", "Pomiń", "Inny", "Zakończ"]
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))


    
# Skrypt do dodania kolumny "nachylenie" do warstwy QGIS
# i wypełnienia jej wartościami z kolumny "nachylenie_chmura" (NULL -> 0)

def add_nachylenie_column(layer_name):
    """
    Dodaje kolumnę 'nachylenie' 
    i wypełnia ją wartościami z kolumny 'nachylenie_chmura' (NULL zamienia na 0)
    """
    # Pobranie warstwy z aktualnego projektu
    layer = QgsProject.instance().mapLayersByName(layer_name)
    
    if not layer:
        print(f"Błąd: Nie znaleziono warstwy o nazwie '{layer_name}'")
        return False
    
    layer = layer[0]  # Pierwszy element z listy warstw
    
    # Sprawdzenie czy warstwa ma kolumnę źródłową
    source_field = "nachylenie_chmura"
    target_field = "nachylenie"
    
    fields = layer.fields()
    source_field_exists = fields.indexFromName(source_field) != -1
    target_field_exists = fields.indexFromName(target_field) != -1
    
    if not source_field_exists:
        print(f"Błąd: Nie znaleziono kolumny źródłowej '{source_field}'")
        return False
    
    # Rozpoczęcie edycji warstwy
    layer.startEditing()
    
    try:
        # Dodanie nowej kolumny jeśli nie istnieje
        if not target_field_exists:
            new_field = QgsField(target_field, QVariant.Double)
            layer.dataProvider().addAttributes([new_field])
            layer.updateFields()
            print(f"Dodano nową kolumnę '{target_field}'")
        else:
            print(f"Kolumna '{target_field}' już istnieje - aktualizowanie wartości")
        
        # Pobranie indeksów kolumn
        source_idx = layer.fields().indexFromName(source_field)
        target_idx = layer.fields().indexFromName(target_field)
        
        # Aktualizacja wartości dla wszystkich obiektów
        updated_count = 0
        null_count = 0
        
        for feature in layer.getFeatures():
            source_value = feature[source_idx]
            
            # Sprawdzenie czy wartość jest NULL i zamiana na 0
            if source_value is None or source_value == '':
                new_value = 0
                null_count += 1
            else:
                try:
                    new_value = int(source_value)
                except (ValueError, TypeError):
                    new_value = 0
                    null_count += 1
            
            # Aktualizacja wartości w nowej kolumnie
            layer.changeAttributeValue(feature.id(), target_idx, new_value)
            updated_count += 1
        
        # Zatwierdzenie zmian
        layer.commitChanges()
        
        print("Operacja zakończona pomyślnie!")
        print(f"Zaktualizowano {updated_count} rekordów")
        print(f"Zamieniono {null_count} wartości NULL na 0")
        
        return True
        
    except Exception as e:
        # Cofnięcie zmian w przypadku błędu
        layer.rollBack()
        print(f"Błąd podczas wykonywania operacji: {str(e)}")
        return False


def zapis_do_gpkg(temp_layer):
    project_path = QgsProject.instance().fileName() 
    if project_path:
        project_directory = Path(project_path).parent
        print(f"Katalog projektu: {project_directory}")
    else:
        print("Projekt nie został jeszcze zapisany.")
        project_directory = Path.cwd()

    layer_name = temp_layer.name()
    output_path = str(project_directory / f"{layer_name}.gpkg")

    if temp_layer:
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.fileEncoding = 'UTF-8'
        options.layerName = layer_name
        
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            temp_layer, 
            output_path, 
            QgsCoordinateTransformContext(), 
            options
        )
        
        if result[0] == QgsVectorFileWriter.WriterError.NoError:
            print(f"Warstwa została pomyślnie zapisana do: {output_path}")
            QgsProject.instance().removeMapLayer(temp_layer)
            
            saved_layer = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
            if saved_layer.isValid():
                QgsProject.instance().addMapLayer(saved_layer)
                print("Warstwa została pomyślnie wczytana do projektu.")
            else:
                print("Błąd podczas wczytywania warstwy.")
        else:
            print(f"Błąd podczas zapisywania warstwy: {result[1]}")
    else:
        print("Nie znaleziono warstwy tymczasowej.")


# Tworzymy plik CSV, jeśli nie istnieje
if not os.path.exists(csv_file):
    with open(csv_file, mode="w", newline="", encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["ID_BUDYNKU", "Kategoria"])

        
def popraw_nachylenie_dla_plaskich(warstwa):
    nazwy = ("Kategoria", "nachylenie", "nachylenie_od", "nachylenie_do", "nachylenie_przedzial")
    idx = {n: warstwa.fields().indexFromName(n) for n in nazwy}
    if idx["Kategoria"] == -1 or idx["nachylenie"] == -1:
        print("❌ Nie znaleziono wymaganych pól w warstwie.")
        return
    ma_przedzialy = all(idx[n] != -1 for n in ("nachylenie_od", "nachylenie_do", "nachylenie_przedzial"))

    licznik = 0
    warstwa.startEditing()
    for f in warstwa.getFeatures():
        if f["Kategoria"] != "płaski":
            continue
        try:
            if float(f["nachylenie"] or 0) > 5:
                warstwa.changeAttributeValue(f.id(), idx["nachylenie"], 5)
            if ma_przedzialy and float(f["nachylenie_do"] or 0) > 5:
                warstwa.changeAttributeValue(f.id(), idx["nachylenie_od"], 0)
                warstwa.changeAttributeValue(f.id(), idx["nachylenie_do"], 5)
                warstwa.changeAttributeValue(f.id(), idx["nachylenie_przedzial"], "0-5")
                licznik += 1
        except (TypeError, ValueError) as e:
            print(f"⚠️ Błąd przy analizie feature ID {f.id()}: {e}")
    warstwa.commitChanges()
    print(f"🔧 Poprawiono nachylenie dla {licznik} dachów płaskich > 5°")



def przewidz_kategorie(feature):
    """
    NAPRAWIONE - dodano sprawdzenie czy atrybuty istnieją
    """
    # Sprawdź czy feature ma wymagane atrybuty
    field_names = [f.name() for f in feature.fields()]
    
    if "PREDYKCJA" not in field_names:
        print(f"⚠️ Brak kolumny PREDYKCJA w warstwie! Dostępne kolumny: {field_names}")
        return ["czterospadowy", 0.0]
    
    if "PEWNOSC" not in field_names:
        print(f"⚠️ Brak kolumny PEWNOSC w warstwie! Dostępne kolumny: {field_names}")
        return ["czterospadowy", 0.0]
    
    # Pobierz wartości bezpośrednio jako Python types
    prediction = feature.attribute("PREDYKCJA")
    pewnosc = feature.attribute("PEWNOSC")
    
    # Konwersja z zabezpieczeniem przed None
    prediction_str = str(prediction) if prediction is not None else "czterospadowy"
    
    try:
        pewnosc_float = float(pewnosc) if pewnosc is not None else 0.0
    except (ValueError, TypeError):
        pewnosc_float = 0.0
    
    return [prediction_str, pewnosc_float]



class KategoriaDialog(QDialog):
    def __init__(self, id_poligonu, sugerowana_kategoria, pewnosc_predykcji, nachylenie, kategorie, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Wybór kategorii dla {id_poligonu}")
        layout = QVBoxLayout()
        try:
            nach_txt = f"{float(nachylenie):.1f}°"
        except (TypeError, ValueError):
            nach_txt = "—"
        self.label = QLabel(
            f"Dach {id_poligonu}\n"
            f"sugerowana: {sugerowana_kategoria}; prawdopodobieństwo: {pewnosc_predykcji}\n"
            f"nachylenie: {nach_txt}"
        )
        layout.addWidget(self.label)
        self.combo = QComboBox()
        self.combo.addItems(kategorie)
        self.combo.setCurrentText(sugerowana_kategoria)
        layout.addWidget(self.combo)
        self.input_other_category = QLineEdit()
        self.input_other_category.setPlaceholderText("Wpisz kategorię (jeśli 'Inny')")
        self.input_other_category.setEnabled(False)
        layout.addWidget(self.input_other_category)
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Anuluj")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        self.combo.currentTextChanged.connect(self.on_category_change)
        self.move(100, 100)
        
    def on_category_change(self):
        if self.combo.currentText() == "Inny":
            self.input_other_category.setEnabled(True)
        else:
            self.input_other_category.setEnabled(False)
    
    def get_selected_category(self):
        if self.combo.currentText() == "Inny":
            return self.input_other_category.text()
        return self.combo.currentText()


def remove_memory_layers():
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.dataProvider().name() == 'memory':
            QgsProject.instance().removeMapLayer(lyr.id())
     
            
def get_prediction_data_dir():
    """Zwraca ścieżkę do katalogu prediction_data w folderze projektu QGIS"""
    prediction_dir = project_directory / "prediction_data"
    
    # Utwórz folder jeśli nie istnieje
    prediction_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Katalog predykcji (w projekcie): {prediction_dir}")
    return str(prediction_dir)


def wczytaj_csv_do_qgis(sciezka_csv, nazwa_kolumny_x=None, nazwa_kolumny_y=None, 
                        separator=None, crs_kod='EPSG:2180', nazwa_warstwy=None, 
                        kodowanie='UTF-8', auto_detect=True):
    """
    Wczytuje plik CSV jako warstwę do QGIS z automatyczną detekcją separatora
    """
    from urllib.parse import quote
    
    # Sprawdź czy plik istnieje
    if not os.path.exists(sciezka_csv):
        print(f"Błąd: Plik {sciezka_csv} nie istnieje!")
        return None
    
    # Automatyczna detekcja separatora
    if separator is None and auto_detect:
        try:
            with open(sciezka_csv, 'r', encoding=kodowanie) as file:
                first_line = file.readline().strip()
                separators = [' ', ',', ';', '\t', '|']
                separator_counts = {}
                
                for sep in separators:
                    count = first_line.count(sep)
                    if count > 0:
                        separator_counts[sep] = count
                
                if separator_counts:
                    separator = max(separator_counts.items(), key=lambda x: x[1])[0]
                    print(f"Wykryty separator: '{separator}' (wystąpienia: {separator_counts[separator]})")
                else:
                    separator = ' '
                    print("Nie wykryto separatora, używam spacji")
        except Exception as e:
            print(f"Błąd przy detekcji separatora: {e}")
            separator = ' '
    
    if separator is None:
        separator = ' '
    
    if nazwa_warstwy is None:
        nazwa_warstwy = os.path.splitext(os.path.basename(sciezka_csv))[0]
    
    sciezka_zakodowana = quote(sciezka_csv.replace('\\', '/'))
    
    separator_mapping = {
        ' ': '%20',
        ',': ',',
        ';': ';',  
        '\t': '\\t',
        '|': '|'
    }
    
    separator_uri = separator_mapping.get(separator, separator)
    
    if nazwa_kolumny_x and nazwa_kolumny_y:
        uri = f"file:///{sciezka_zakodowana}?delimiter={separator_uri}&xField={nazwa_kolumny_x}&yField={nazwa_kolumny_y}&crs={crs_kod}&encoding={kodowanie}"
    else:
        uri = f"file:///{sciezka_zakodowana}?delimiter={separator_uri}&encoding={kodowanie}"
    
    print(f"URI: {uri}")
    
    warstwa = QgsVectorLayer(uri, nazwa_warstwy, "delimitedtext")
    
    if not warstwa.isValid():
        print(f"Błąd: Nie można wczytać warstwy z pliku {sciezka_csv}")
        kodowania_do_sprawdzenia = ['UTF-8', 'Windows-1250', 'ISO-8859-2', 'CP1252']
        for kod in kodowania_do_sprawdzenia:
            if kod != kodowanie:
                print(f"Próbuję z kodowaniem: {kod}")
                if nazwa_kolumny_x and nazwa_kolumny_y:
                    uri_test = f"file:///{sciezka_zakodowana}?delimiter={separator_uri}&xField={nazwa_kolumny_x}&yField={nazwa_kolumny_y}&crs={crs_kod}&encoding={kod}"
                else:
                    uri_test = f"file:///{sciezka_zakodowana}?delimiter={separator_uri}&encoding={kod}"
                
                warstwa_test = QgsVectorLayer(uri_test, nazwa_warstwy, "delimitedtext")
                if warstwa_test.isValid():
                    warstwa = warstwa_test
                    kodowanie = kod
                    print(f"✓ Udało się z kodowaniem: {kod}")
                    break
        
        if not warstwa.isValid():
            print("Sprawdź czy nazwy kolumn i separator są poprawne")
            try:
                with open(sciezka_csv, 'r', encoding='utf-8', errors='ignore') as f:
                    print("Pierwsze 3 linie pliku:")
                    for i, line in enumerate(f):
                        if i >= 3:
                            break
                        print(f"  {i+1}: {repr(line.strip())}")
            except Exception:
                # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
                pass  # nosec B110
            return None
    
    QgsProject.instance().addMapLayer(warstwa)
    
    print(f"✓ Wczytano warstwę: {nazwa_warstwy}")
    print(f"  - Liczba obiektów: {warstwa.featureCount()}")
    print(f"  - CRS: {warstwa.crs().authid()}")
    print(f"  - Separator: '{separator}'")
    print(f"  - Kodowanie: {kodowanie}")
    print(f"  - Kolumny: {[field.name() for field in warstwa.fields()]}")
    
    QgsMessageLog.logMessage(
        f"Wczytano warstwę CSV: {nazwa_warstwy} ({warstwa.featureCount()} obiektów)",
        "CSV Loader", 
        Qgis.MessageLevel.Info
    )
    
    return warstwa

def wait_for_file(timeout_s=600):
    """
    Czeka na pojawienie sie pliku building_predictions.csv w katalogu PREDICTION_DIR.

    WAZNE: nie blokujemy glownego watku GUI. Zwykla petla z time.sleep()
    zamraza cala aplikacje QGIS ("brak odpowiedzi"), bo interfejs nie moze
    przetwarzac zdarzen. Dlatego w kazdej iteracji oddajemy sterowanie do
    petli zdarzen Qt (processEvents), dzieki czemu okno pozostaje responsywne,
    a uzytkownik widzi postep.
    """
    from qgis.PyQt.QtWidgets import QApplication

    prediction_dir = PREDICTION_DIR
    file_path = Path(prediction_dir) / "building_predictions.csv"

    print(f"Oczekiwanie na plik: {file_path}")

    waited = 0
    poll = 0.5  # sekundy — czestsze sprawdzanie, ale bez blokady GUI
    while waited < timeout_s:
        if file_path.exists() and file_path.is_file():
            print(f"Plik znaleziony: {file_path}")
            return str(file_path)

        # oddaj sterowanie GUI, zeby QGIS nie pokazywal "brak odpowiedzi"
        QApplication.processEvents()
        time.sleep(poll)
        waited += poll

        # co ~5 s wypisz komunikat, zeby nie zasypywac konsoli
        if int(waited) % 5 == 0 and abs(waited - int(waited)) < poll:
            print(f"   ...czekam na klasyfikator ({int(waited)}s / limit {timeout_s}s)")

    # przekroczono limit czasu — klasyfikator prawdopodobnie sie nie uruchomil
    print(f"❌ Przekroczono limit {timeout_s}s oczekiwania na {file_path.name}.")
    print("   Sprawdz, czy klasyfikator dachow uruchomil sie poprawnie "
          "(interpreter Pythona, TensorFlow, model CNN).")
    return None
            
def apply_qml_style_to_layer(layer, qml_file_path=None, show_messages=True):
    """
    Aplikuje styl QML do warstwy wektorowej.
    """
    
    if isinstance(layer, str):
        layer_name = layer
        layer = None
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == layer_name:
                layer = lyr
                break
        
        if layer is None:
            if show_messages:
                QMessageBox.warning(None, "Błąd", f"Nie znaleziono warstwy: {layer_name}")
            return False
    
    if not isinstance(layer, QgsVectorLayer):
        if show_messages:
            QMessageBox.warning(None, "Błąd", "Wybrana warstwa nie jest warstwą wektorową")
        return False
    
    if qml_file_path is None:
        qml_file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Wybierz plik stylu QML",
            "",
            "Pliki QML (*.qml);;Wszystkie pliki (*)"
        )
        
        if not qml_file_path:
            return False
    
    if not os.path.exists(qml_file_path):
        if show_messages:
            QMessageBox.warning(None, "Błąd", f"Plik QML nie istnieje: {qml_file_path}")
        return False
    
    try:
        result = layer.loadNamedStyle(qml_file_path)
        
        if result[1]:
            layer.triggerRepaint()
            iface.layerTreeView().refreshLayerSymbology(layer.id())
            
            if show_messages:
                QMessageBox.information(None, "Sukces", 
                    f"Styl został pomyślnie zastosowany do warstwy: {layer.name()}")
            return True
        else:
            if show_messages:
                QMessageBox.warning(None, "Błąd", 
                    f"Nie udało się załadować stylu: {result[0]}")
            return False
            
    except Exception as e:
        if show_messages:
            QMessageBox.critical(None, "Błąd", f"Wystąpił błąd podczas ładowania stylu: {str(e)}")
        return False


def validate_join_result(layer, expected_fields):
    """
    NOWA FUNKCJA - sprawdza czy join się powiódł
    """
    if layer is None:
        print("❌ Warstwa jest None - join nie powiódł się!")
        return False
    
    field_names = [f.name() for f in layer.fields()]
    print(f"📋 Kolumny w warstwie po join: {field_names}")
    
    missing_fields = []
    for field in expected_fields:
        if field not in field_names:
            missing_fields.append(field)
    
    if missing_fields:
        print(f"❌ Brakujące kolumny po join: {missing_fields}")
        return False
    
    # Sprawdź czy wartości nie są wszystkie NULL
    sample_feature = next(layer.getFeatures())
    for field in expected_fields:
        value = sample_feature.attribute(field)
        print(f"  - {field}: {value} (typ: {type(value).__name__})")
    
    return True


def debug_id_matching(layer1_name, layer2_name, field_name="ID_BUDYNKU"):
    """
    NOWA FUNKCJA - sprawdza zgodność ID między warstwami
    """
    layer1 = QgsProject.instance().mapLayersByName(layer1_name)
    layer2 = QgsProject.instance().mapLayersByName(layer2_name)
    
    if not layer1 or not layer2:
        print(f"❌ Nie znaleziono warstw: {layer1_name} lub {layer2_name}")
        return
    
    layer1 = layer1[0]
    layer2 = layer2[0]
    
    # Pobierz ID z obu warstw
    ids1 = set()
    ids2 = set()
    
    for f in layer1.getFeatures():
        val = f.attribute(field_name)
        ids1.add(str(val))
    
    for f in layer2.getFeatures():
        val = f.attribute(field_name)
        ids2.add(str(val))
    
    print("\n🔍 DIAGNOSTYKA ID:")
    print(f"  {layer1_name}: {len(ids1)} unikalnych ID")
    print(f"  {layer2_name}: {len(ids2)} unikalnych ID")
    
    # Przykładowe ID
    print(f"  Przykładowe ID z {layer1_name}: {list(ids1)[:3]}")
    print(f"  Przykładowe ID z {layer2_name}: {list(ids2)[:3]}")
    
    # Wspólne ID
    common = ids1.intersection(ids2)
    print(f"  Wspólne ID: {len(common)}")
    
    if len(common) == 0:
        print("  ⚠️ BRAK WSPÓLNYCH ID! Join nie będzie działać!")
        # Sprawdź czy typy są różne
        sample1 = list(ids1)[0] if ids1 else ""
        sample2 = list(ids2)[0] if ids2 else ""
        print(f"  Porównanie: '{sample1}' vs '{sample2}'")
    else:
        print(f"  ✓ Znaleziono {len(common)} wspólnych ID")


def debug_id_matching_custom(layer1_name, layer2_name, field1_name, field2_name):
    """
    NOWA FUNKCJA - sprawdza zgodność ID między warstwami z różnymi nazwami pól
    """
    layer1 = QgsProject.instance().mapLayersByName(layer1_name)
    layer2 = QgsProject.instance().mapLayersByName(layer2_name)
    
    if not layer1 or not layer2:
        print(f"❌ Nie znaleziono warstw: {layer1_name} lub {layer2_name}")
        return 0
    
    layer1 = layer1[0]
    layer2 = layer2[0]
    
    # Pobierz ID z obu warstw
    ids1 = set()
    ids2 = set()
    
    for f in layer1.getFeatures():
        val = f.attribute(field1_name)
        ids1.add(str(val))
    
    for f in layer2.getFeatures():
        val = f.attribute(field2_name)
        ids2.add(str(val))
    
    print(f"  {layer1_name}.{field1_name}: {len(ids1)} unikalnych ID")
    print(f"  {layer2_name}.{field2_name}: {len(ids2)} unikalnych ID")
    
    # Przykładowe ID
    print(f"  Przykładowe ID z {field1_name}: {list(ids1)[:3]}")
    print(f"  Przykładowe ID z {field2_name}: {list(ids2)[:3]}")
    
    # Wspólne ID
    common = ids1.intersection(ids2)
    print(f"  Wspólne ID: {len(common)}")
    
    if len(common) == 0:
        print("  ⚠️ BRAK WSPÓLNYCH ID! Join nie będzie działać!")
    else:
        print(f"  ✓ Znaleziono {len(common)} wspólnych ID - join powinien działać!")
    
    return len(common)


PREDICTION_DIR = get_prediction_data_dir()

    
# Czekaj na plik
file_path = wait_for_file()

if file_path is None:
    # klasyfikator nie zdazyl / nie uruchomil sie — nie brniemy dalej
    print("❌ Nie doczekano sie wynikow klasyfikacji dachow. Krok przerwany.")
    raise RuntimeError(
        "Klasyfikacja dachow nie utworzyla pliku building_predictions.csv "
        "w wyznaczonym czasie. Sprawdz logi klasyfikatora (interpreter Pythona, "
        "TensorFlow, sciezka modelu CNN)."
    )

# TUTAJ ROZPOCZYNA SIĘ WŁAŚCIWY KOD PROGRAMU
print("=" * 50)
print("PLIK ZNALEZIONY! Wykonywanie dalszego kodu...")
print("=" * 50)
   
try:    
    prediction_layer = wczytaj_csv_do_qgis(
        f"{PREDICTION_DIR}/building_predictions.csv",
        nazwa_kolumny_x=None,
        nazwa_kolumny_y=None,
        nazwa_warstwy="Predykcje_budynkow"
    )

except Exception as e:
    print(f"Błąd podczas przetwarzania pliku: {e}")

# NOWE: Diagnostyka przed joinem
print("\n" + "=" * 50)
print("DIAGNOSTYKA PRZED JOINEM")
print("=" * 50)
debug_id_matching('budynki_z_szer_elew_front', 'Predykcje_budynkow', 'ID_BUDYNKU')

# NAPRAWKA: Normalizuj ID_BUDYNKU w warstwie budynków (zamień / na _)
print("\n🔧 Normalizacja ID_BUDYNKU (zamiana '/' na '_')...")
budynki_layer = QgsProject.instance().mapLayersByName('budynki_z_szer_elew_front')[0]

# Dodaj kolumnę z znormalizowanym ID
budynki_layer.startEditing()
# Dodaj nowe pole jeśli nie istnieje
if budynki_layer.fields().indexFromName('ID_BUDYNKU_NORM') == -1:
    budynki_layer.dataProvider().addAttributes([QgsField('ID_BUDYNKU_NORM', QVariant.String)])
    budynki_layer.updateFields()

# Wypełnij znormalizowanymi wartościami
idx_orig = budynki_layer.fields().indexFromName('ID_BUDYNKU')
idx_norm = budynki_layer.fields().indexFromName('ID_BUDYNKU_NORM')

for feature in budynki_layer.getFeatures():
    orig_id = str(feature.attribute('ID_BUDYNKU'))
    norm_id = orig_id.replace('/', '_')
    budynki_layer.changeAttributeValue(feature.id(), idx_norm, norm_id)

budynki_layer.commitChanges()
print("✓ Dodano kolumnę ID_BUDYNKU_NORM z znormalizowanymi ID")

# Teraz diagnostyka po normalizacji
print("\n🔍 DIAGNOSTYKA PO NORMALIZACJI:")
debug_id_matching_custom('budynki_z_szer_elew_front', 'Predykcje_budynkow', 'ID_BUDYNKU_NORM', 'ID_BUDYNKU')

params = {
    'INPUT': QgsProject.instance().mapLayersByName('budynki_z_szer_elew_front')[0],
    'FIELD': 'ID_BUDYNKU_NORM',  # ZMIANA: używamy znormalizowanego ID
    'INPUT_2': QgsProject.instance().mapLayersByName('Predykcje_budynkow')[0],
    'FIELD_2': 'ID_BUDYNKU',
    'FIELDS_TO_COPY': ['PREDYKCJA', 'PEWNOSC'],
    'METHOD': 1,
    'DISCARD_NONMATCHING': False,
    'PREFIX': '',
    'OUTPUT': 'memory:budynki_with_predictions'
}

print("\n🔗 Wykonywanie join...")
joined_layer = processing.run("native:joinattributestable", params)['OUTPUT']
joined_layer.setName('budynki_z_predykcjami')

# NOWE: Walidacja joinu
print("\n" + "=" * 50)
print("WALIDACJA JOINU")
print("=" * 50)
join_valid = validate_join_result(joined_layer, ['PREDYKCJA', 'PEWNOSC'])

if not join_valid:
    print("❌ JOIN NIE POWIÓDŁ SIĘ! Sprawdź zgodność ID_BUDYNKU między warstwami.")
    # Opcjonalnie: przerwij skrypt lub kontynuuj z ostrzeżeniem
else:
    print("✓ Join zakończony pomyślnie")

QgsProject.instance().addMapLayer(joined_layer)
print(f"✓ Warstwa 'budynki_z_predykcjami' dodana do projektu")

style_name = "style/budynki_do_analizy.qml"
style_path = os.path.join(SCRIPTS_PATH, style_name)
apply_qml_style_to_layer("budynki_z_predykcjami", style_path)

# GŁÓWNA CZĘŚĆ KODU
add_nachylenie_column('budynki_z_predykcjami')

warstwa_poligonowa = QgsProject.instance().mapLayersByName('budynki_z_predykcjami')[0]

if not warstwa_poligonowa:
    print("❌ Nie wybrano aktywnej warstwy!")
    exit()

# NOWE: Wyświetl informacje o warstwie
print(f"\n📊 Warstwa do klasyfikacji: {warstwa_poligonowa.name()}")
print(f"   Liczba obiektów: {warstwa_poligonowa.featureCount()}")
print(f"   Kolumny: {[f.name() for f in warstwa_poligonowa.fields()]}")

# Wczytaj wcześniej zaklasyfikowane budynki
zaklasyfikowane_budynki = set()
if os.path.exists(csv_file):
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            zaklasyfikowane_budynki.add(row['ID_BUDYNKU'])
    print(f"📂 Wczytano {len(zaklasyfikowane_budynki)} wcześniej zaklasyfikowanych dachów.")

wszystkie_features = list(warstwa_poligonowa.getFeatures())
niezaklasyfikowane_features = []

for feature in wszystkie_features:
    id_poligonu = str(feature[nazwa_pola])
    if id_poligonu not in zaklasyfikowane_budynki:
        niezaklasyfikowane_features.append(feature)

print(f"🔍 Znaleziono {len(niezaklasyfikowane_features)} niezaklasyfikowanych dachów do przetworzenia.")
print(f"📊 Pomijam {len(wszystkie_features) - len(niezaklasyfikowane_features)} już zaklasyfikowanych dachów.")

if not niezaklasyfikowane_features:
    print("✅ Wszystkie dachy są już zaklasyfikowane!")
else:
    # NOWE: Sprawdź pierwszy feature przed rozpoczęciem
    if niezaklasyfikowane_features:
        first_feature = niezaklasyfikowane_features[0]
        pred_result = przewidz_kategorie(first_feature)
        print(f"\n🧪 Test predykcji dla pierwszego budynku:")
        print(f"   Predykcja: {pred_result[0]}, Pewność: {pred_result[1]}")
    
    for feature in niezaklasyfikowane_features:
        id_poligonu = str(feature[nazwa_pola])
        
        # Wyświetl dach na mapie
        bbox = feature.geometry().boundingBox()
        margines = max(bbox.width() * 0.4, bbox.height() * 0.4)  
        nowy_bbox = bbox.buffered(margines)  
        iface.mapCanvas().setExtent(nowy_bbox)
        warstwa_poligonowa.removeSelection()
        warstwa_poligonowa.select(feature.id())
        iface.mapCanvas().refresh()
        
        # Wyświetl dialog
        sugerowana_kategoria, pewnosc_predykcji = przewidz_kategorie(feature)
        idx_n = feature.fields().indexFromName('nachylenie')
        nachylenie = feature['nachylenie'] if idx_n != -1 else None
        dialog = KategoriaDialog(id_poligonu, sugerowana_kategoria, pewnosc_predykcji,
                                 nachylenie, kategorie, iface.mainWindow())
        
        dialog.show()
        result = dialog.exec()
        
        if result == QDialog.DialogCode.Accepted:
            kategoria = dialog.get_selected_category()
        elif result == QDialog.DialogCode.Rejected:
            print("🛑 Przerwano wybór kategorii!")
            break
            
        if kategoria == "Zakończ":
            print("🛑 Zakończenie procesu przez użytkownika.")
            break
            
        if kategoria == "Pomiń":
            print(f"🚀 Pominięto dach {id_poligonu}")
            continue
            
        # Zapisz do CSV
        with open(csv_file, mode="a", newline="", encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([id_poligonu, kategoria])
            
        print(f"✅ Zapisano: {id_poligonu} (kategoria: {kategoria})")
        
        zaklasyfikowane_budynki.add(id_poligonu)

print("🎉 Proces klasyfikacji zakończony!")

# === RESZTA KODU ===
with open(csv_file, newline='', encoding='utf-8') as f: 
    reader = csv.DictReader(f) 
    fieldnames = reader.fieldnames
    
    fields = QgsFields() 
    for name in fieldnames: 
        if name != "id": 
            fields.append(QgsField(name, QVariant.String))
            
    csv_memory_layer = QgsVectorLayer("None", "klasyfikacja_dachow", "memory") 
    csv_memory_layer.dataProvider().addAttributes(fields) 
    csv_memory_layer.updateFields()     
     
    features = [] 
    for row in reader: 
        feat = QgsFeature() 
        feat.initAttributes(len(fields)) 
        for i, name in enumerate(fieldnames): 
            if name != "id": 
                feat[i] = row[name] 
        features.append(feat)  
            
    csv_memory_layer.dataProvider().addFeatures(features) 
    csv_memory_layer.updateExtents()         
                
    QgsProject.instance().addMapLayer(csv_memory_layer) 

# DODAJE KLASYFIKACJE DACHÓW DO WARSTWY BUDYNKÓW 
try:
    params = { 
        'INPUT': QgsProject.instance().mapLayersByName('budynki_z_predykcjami')[0], 
        'FIELD': 'ID_BUDYNKU', 
        'INPUT_2': QgsProject.instance().mapLayersByName('klasyfikacja_dachow')[0], 
        'FIELD_2': 'ID_BUDYNKU', 
        'FIELDS_TO_COPY': ['Kategoria'], 
        'METHOD': 1, 
        'DISCARD_NONMATCHING': False, 
        'PREFIX': '', 
        'OUTPUT': 'memory:budynki_parametry' 
    }

    joined_layer = processing.run("native:joinattributestable", params)['OUTPUT'] 
    QgsProject.instance().addMapLayer(joined_layer) 
    zapis_do_gpkg(joined_layer)
    layer = QgsProject.instance().mapLayersByName("budynki_parametry")[0]
    popraw_nachylenie_dla_plaskich(layer)
except Exception as e:
    print(f"Błąd podczas łączenia z warstwą budynków: {e}")

# DODAJE KLASYFIKACJE DACHÓW DO WARSTWY PUNKTÓW 
try:
    params = { 
        'INPUT': QgsProject.instance().mapLayersByName('Classification_6_with_IDs')[0], 
        'FIELD': 'ID_BUDYNKU', 
        'INPUT_2': QgsProject.instance().mapLayersByName('klasyfikacja_dachow')[0], 
        'FIELD_2': 'ID_BUDYNKU', 
        'FIELDS_TO_COPY': ['Kategoria'], 
        'METHOD': 1, 
        'DISCARD_NONMATCHING': False, 
        'PREFIX': '', 
        'OUTPUT': 'memory:Classification_6_with_roofsKategories' 
    }

    joined_layer = processing.run("native:joinattributestable", params)['OUTPUT']
    QgsProject.instance().addMapLayer(joined_layer) 
    zapis_do_gpkg(joined_layer)
except Exception as e:
    print(f"Nie znaleziono warstwy 'Classification_6_with_IDs' lub błąd: {e}")
    
remove_memory_layers()