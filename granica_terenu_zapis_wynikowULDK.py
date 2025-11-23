from pathlib import Path
from qgis.core import (QgsProject, QgsVectorFileWriter, QgsCoordinateTransformContext, 
                       QgsField, QgsVectorLayer, QgsFeature,
                       QgsCoordinateTransform, QgsGeometry)
import os
from qgis.utils import iface
from PyQt5.QtWidgets import QMessageBox, QFileDialog
from PyQt5.QtCore import QVariant
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))


def remove_memory_layers():
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.dataProvider().name() == 'memory':
            QgsProject.instance().removeMapLayer(lyr.id())
            
            
def scalanie_wszystkich_dzialek_z_warstwy(warstwa):
    # Pobierz wszystkie obiekty z warstwy
    all_feats = list(warstwa.getFeatures())
    
    if len(all_feats) < 2:
        print("❌ Warstwa musi zawierać minimum dwa poligony.")
        return
    
    warstwa.startEditing()
    
    # Agreguj geometrię wszystkich obiektów
    combined_geometry = all_feats[0].geometry()
    for feat in all_feats[1:]:
        combined_geometry = combined_geometry.combine(feat.geometry())
    
    # Agreguj ID_DZIALKI i NUMER_DZIALKI ze wszystkich obiektów
    ids = [str(f["ID_DZIALKI"]) for f in all_feats]
    numery = [str(f["NUMER_DZIALKI"]) for f in all_feats]
    new_id = "; ".join(ids)
    new_numer = "; ".join(numery)
    
    # Oblicz powierzchnię połączonej geometrii
    pole_m2 = round(combined_geometry.area(), 2)
    
    # Utwórz nowy obiekt
    new_feat = QgsFeature(warstwa.fields())
    new_feat.setGeometry(combined_geometry)
    
    # Bazuj na atrybutach z pierwszego obiektu
    for field in warstwa.fields():
        name = field.name()
        if name == "ID_DZIALKI":
            new_feat[name] = new_id
        elif name == "NUMER_DZIALKI":
            new_feat[name] = new_numer
        elif name == "POLE_EWIDENCYJNE":
            new_feat[name] = pole_m2
        else:
            new_feat[name] = all_feats[0][name]
    
    # Usuń wszystkie stare obiekty
    for f in all_feats:
        warstwa.deleteFeature(f.id())
    
    # Dodaj nowy scalony obiekt
    warstwa.addFeature(new_feat)
    
    warstwa.commitChanges()
    warstwa.triggerRepaint()
    
    print(f"✅ Wszystkie działki ({len(all_feats)}) zostały połączone w jeden poligon.")
    print(f"   Nowe ID_DZIALKI: {new_id}")
    print(f"   Nowe NUMER_DZIALKI: {new_numer}")
    print(f"   Powierzchnia: {pole_m2} m²")



def apply_qml_style_to_layer(layer, qml_file_path=None, show_messages=True):
    """
    Aplikuje styl QML do warstwy wektorowej.
    
    Args:
        layer: Obiekt QgsVectorLayer lub nazwa warstwy (str)
        qml_file_path: Ścieżka do pliku QML (str). Jeśli None, otworzy dialog wyboru pliku
        show_messages: Czy pokazywać komunikaty o błędach/sukcesie (bool)
    
    Returns:
        bool: True jeśli stylizacja została zastosowana pomyślnie, False w przeciwnym razie
    """
    
    # Konwersja nazwy warstwy na obiekt warstwy jeśli potrzeba
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
    
    # Sprawdzenie czy warstwa jest wektorowa
    if not isinstance(layer, QgsVectorLayer):
        if show_messages:
            QMessageBox.warning(None, "Błąd", "Wybrana warstwa nie jest warstwą wektorową")
        return False
    
    # Wybór pliku QML jeśli nie został podany
    if qml_file_path is None:
        qml_file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Wybierz plik stylu QML",
            "",
            "Pliki QML (*.qml);;Wszystkie pliki (*)"
        )
        
        if not qml_file_path:
            return False
    
    # Sprawdzenie czy plik istnieje
    if not os.path.exists(qml_file_path):
        if show_messages:
            QMessageBox.warning(None, "Błąd", f"Plik QML nie istnieje: {qml_file_path}")
        return False
    
    # Aplikacja stylu
    try:
        result = layer.loadNamedStyle(qml_file_path)
        
        if result[1]:  # result[1] zawiera informację o powodzeniu operacji
            # Odświeżenie warstwy
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



# Pobierz aktywną warstwę
layer = QgsProject.instance().mapLayersByName('Wyniki wyszukiwania ULDK')[0]

# Sprawdź czy warstwa jest wybrana i czy jest warstwą wektorową
if layer is None:
    print("Brak aktywnej warstwy!")
elif not layer.isValid():
    print("Warstwa nie jest prawidłowa!")
elif layer.type() != 0:  # 0 = warstwa wektorowa
    print("Aktywna warstwa nie jest warstwą wektorową!")
else:
    # Sprawdź czy pole 'teryt' istnieje
    field_names = [field.name() for field in layer.fields()]
    if 'teryt' not in field_names:
        print("Pole 'teryt' nie istnieje w warstwie!")
    else:
        # Rozpocznij edycję warstwy
        layer.startEditing()
        
        try:
            # Dodaj pole ID_DZIALKI (tekst)
            if 'ID_DZIALKI' not in field_names:
                field_id = QgsField('ID_DZIALKI', QVariant.String, len=500)
                layer.addAttribute(field_id)
                print("Dodano pole ID_DZIALKI")
            else:
                print("Pole ID_DZIALKI już istnieje")
                
            # Dodaj pole ID_DZIALKI (tekst)
            if 'NUMER_DZIALKI' not in field_names:
                field_id = QgsField('NUMER_DZIALKI', QVariant.String, len=500)
                layer.addAttribute(field_id)
                print("Dodano pole NUMER_DZIALKI")
            else:
                print("Pole NUMER_DZIALKI już istnieje")
            
            # Dodaj pole POLE_EWIDENCYJNE (liczba rzeczywista)
            if 'POLE_EWIDENCYJNE' not in field_names:
                field_pole = QgsField('POLE_EWIDENCYJNE', QVariant.Double, len=10, prec=2)
                layer.addAttribute(field_pole)
                print("Dodano pole POLE_EWIDENCYJNE")
            else:
                print("Pole POLE_EWIDENCYJNE już istnieje")
            
            # Odśwież pola warstwy
            layer.updateFields()
            
            # Pobierz indeksy pól
            teryt_idx = layer.fields().indexFromName('teryt')
            id_dzialki_idx = layer.fields().indexFromName('ID_DZIALKI')
            nr_idx = layer.fields().indexFromName('nr_dzialki')
            numer_dzialki_idx = layer.fields().indexFromName('NUMER_DZIALKI')
            pole_ewid_idx = layer.fields().indexFromName('POLE_EWIDENCYJNE')
            
            # Wypełnij pola dla wszystkich obiektów
            for feature in layer.getFeatures():
                # Skopiuj wartość z pola 'teryt' do 'ID_DZIALKI'
                teryt_value = feature[teryt_idx]
                layer.changeAttributeValue(feature.id(), id_dzialki_idx, teryt_value)
                
                # Skopiuj wartość z pola 'nr_dzialki' do 'NUMER_DZIALKI'
                nr_value = feature[nr_idx]
                layer.changeAttributeValue(feature.id(), numer_dzialki_idx, nr_value)
                
                # Oblicz pole powierzchni i zaokrągl do 2 miejsc po przecinku
                area_value = round(feature.geometry().area(), 2)
                layer.changeAttributeValue(feature.id(), pole_ewid_idx, area_value)
            
            # Zatwierdź zmiany
            layer.commitChanges()
            print(f"Pomyślnie wypełniono pola dla {layer.featureCount()} obiektów")
            
        except Exception as e:
            # W przypadku błędu, cofnij zmiany
            layer.rollBack()
            print(f"Wystąpił błąd: {str(e)}")
            
        # Odśwież warstwę w interfejsie
        layer.triggerRepaint()
        iface.layerTreeView().refreshLayerSymbology(layer.id())



project_path = QgsProject.instance().fileName() 
if project_path:
    project_directory = Path(project_path).parent
    print(f"Katalog projektu: {project_directory}")
else:
    print("Projekt nie został jeszcze zapisany.")
    project_directory = Path.cwd()

# Nazwa i ścieżka do pliku geopackage
temp_layer = layer
layer_name = "granica_terenu"
output_path = str(project_directory / f"{layer_name}.gpkg")

if temp_layer:
    # ALTERNATYWNA WERSJA - TRANSFORMACJA W PAMIĘCI PRZED ZAPISEM:
    
    # Pobierz CRS projektu
    project_crs = QgsProject.instance().crs()
    layer_crs = temp_layer.crs()
    
    print(f"CRS warstwy wejściowej: {layer_crs.authid()} - {layer_crs.description()}")
    print(f"CRS projektu: {project_crs.authid()} - {project_crs.description()}")
    
    # Jeśli CRS się różnią, stwórz nową warstwę z transformacją
    if layer_crs != project_crs:
        print(f"Transformuję geometrię z {layer_crs.authid()} do {project_crs.authid()}")
        
        # Stwórz transformer
        transformer = QgsCoordinateTransform(layer_crs, project_crs, QgsProject.instance())
        
        # Pobierz typ geometrii z pierwszego obiektu
        first_feature = next(temp_layer.getFeatures(), None)
        if first_feature is None:
            print("Błąd: Brak obiektów w warstwie źródłowej")
            layer_to_save = temp_layer
        else:
            geom_type = first_feature.geometry().wkbType()
            print(f"Typ geometrii: {geom_type}")
            
            # Stwórz nową warstwę tymczasową w CRS projektu - użyj wkbType zamiast geometryType
            temp_transformed_layer = QgsVectorLayer(f"Polygon?crs={project_crs.authid()}", 
                                                   "temp_transformed", "memory")
            
            # Sprawdź czy warstwa została utworzona
            if not temp_transformed_layer.isValid():
                print("Błąd: Nie można utworzyć warstwy tymczasowej")
                layer_to_save = temp_layer
            else:
                # Skopiuj pola
                temp_transformed_layer.dataProvider().addAttributes(temp_layer.fields())
                temp_transformed_layer.updateFields()
                
                # Skopiuj i transformuj obiekty
                temp_transformed_layer.startEditing()
                transformed_count = 0
                try:
                    for feature in temp_layer.getFeatures():
                        print(f"Przetwarzam obiekt ID: {feature.id()}")
                        
                        # Pobierz geometrię
                        geom = feature.geometry()
                        if geom.isNull():
                            print("Ostrzeżenie: Pusta geometria, pomijam obiekt")
                            continue
                        
                        print(f"Geometria przed transformacją: {geom.asWkt()[:100]}...")
                        
                        # Skopiuj geometrię i transformuj
                        transformed_geom = QgsGeometry(geom)
                        transform_result = transformed_geom.transform(transformer)
                        
                        if transform_result != 0:
                            print(f"Błąd transformacji geometrii: {transform_result}")
                            continue
                        
                        print(f"Geometria po transformacji: {transformed_geom.asWkt()[:100]}...")
                        
                        # Stwórz nowy obiekt
                        new_feature = QgsFeature(temp_transformed_layer.fields())
                        new_feature.setGeometry(transformed_geom)
                        
                        # Skopiuj atrybuty
                        for field in temp_layer.fields():
                            field_name = field.name()
                            if field_name in [f.name() for f in temp_transformed_layer.fields()]:
                                new_feature[field_name] = feature[field_name]
                        
                        temp_transformed_layer.addFeature(new_feature)
                        transformed_count += 1
                    
                    temp_transformed_layer.commitChanges()
                    print(f"Utworzono transformowaną warstwę z {transformed_count} obiektami")
                    
                    if transformed_count > 0:
                        layer_to_save = temp_transformed_layer
                    else:
                        print("Brak przetransformowanych obiektów, używam warstwy oryginalnej")
                        layer_to_save = temp_layer
                    
                except Exception as e:
                    print(f"Błąd podczas transformacji: {str(e)}")
                    temp_transformed_layer.rollBack()
                    layer_to_save = temp_layer
    else:
        print("CRS są identyczne - brak potrzeby transformacji")
        layer_to_save = temp_layer
    
    # Przygotuj opcje zapisu
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.fileEncoding = 'UTF-8'
    options.layerName = layer_name
    # CRS już jest ustawiony w warstwie
    
    # Zapis
    print(f"Zapisuję warstwę z {layer_to_save.featureCount()} obiektami")
    print(f"CRS warstwy do zapisu: {layer_to_save.crs().authid()}")
    
    try:
        # Sprawdź czy katalog istnieje
        output_dir = Path(output_path).parent
        if not output_dir.exists():
            output_dir.mkdir(parents=True)
            print(f"Utworzono katalog: {output_dir}")
        
        # Usuń istniejący plik jeśli istnieje
        if Path(output_path).exists():
            Path(output_path).unlink()
            print(f"Usunięto istniejący plik: {output_path}")
        
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer_to_save, 
            output_path, 
            QgsCoordinateTransformContext(),
            options
        )
        print(f"Wynik zapisu: {result[0]} - '{result[1]}'")
        
        # Sprawdź czy plik został utworzony
        if Path(output_path).exists():
            print(f"Plik został utworzony: {output_path}")
            print(f"Rozmiar pliku: {Path(output_path).stat().st_size} bajtów")
        else:
            print(f"Plik nie został utworzony: {output_path}")
        
    except Exception as e:
        print(f"Wyjątek podczas zapisu: {str(e)}")
        result = (QgsVectorFileWriter.WriterError, str(e))
    
    # Sprawdź wynik zapisu
    if result[0] == QgsVectorFileWriter.NoError:
        print(f"Warstwa została pomyślnie zapisana do: {output_path}")
        
        # Usuń starą warstwę z projektu (jeśli istnieje)
        layers_to_remove = []
        for layer_id, layer_obj in QgsProject.instance().mapLayers().items():
            if layer_obj.name() == layer_name:
                layers_to_remove.append(layer_id)
        
        for layer_id in layers_to_remove:
            QgsProject.instance().removeMapLayer(layer_id)
            print(f"Usunięto starą warstwę: {layer_id}")
        
        # Wczytaj zapisaną warstwę do projektu
        saved_layer = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
        if saved_layer.isValid():
            print(f"CRS wczytanej warstwy: {saved_layer.crs().authid()} - {saved_layer.crs().description()}")
            print(f"Liczba obiektów: {saved_layer.featureCount()}")
            print(f"Zasięg warstwy: {saved_layer.extent().toString()}")
            
            QgsProject.instance().addMapLayer(saved_layer)
            
            # ZASTOSUJ MECHANIZM Z FUNKCJI apply_qml_style_to_layer:
            saved_layer.triggerRepaint()
            iface.layerTreeView().refreshLayerSymbology(saved_layer.id())
            
            # Przenieś widok mapy na zasięg warstwy
            iface.mapCanvas().setExtent(saved_layer.extent())
            iface.mapCanvas().refresh()
            
            print("Warstwa została pomyślnie wczytana do projektu z CRS projektu.")
            print("Zastosowano mechanizm odświeżania z funkcji apply_qml_style_to_layer.")
        else:
            print("Błąd podczas wczytywania warstwy.")
            print(f"Źródło danych: {saved_layer.source()}")
            print(f"Provider: {saved_layer.providerType()}")
    else:
        print(f"Błąd podczas zapisywania warstwy: {result[1]}")
        print("Sprawdź czy:")
        print("1. Ścieżka zapisu jest dostępna")
        print("2. Nie ma problemów z prawami dostępu")
        print("3. Warstwa źródłowa ma prawidłowe geometrie")
else:
    print("Nie znaleziono warstwy tymczasowej.")
    
style_name = "style/granica terenu planowanej inwestycji.qml"
style_path = os.path.join(SCRIPTS_PATH, style_name)
apply_qml_style_to_layer(
    "granica_terenu",style_path)


# Skrypt do sprawdzania liczby obiektów w warstwie 'granica_terenu' i scalania w QGIS
# Pobierz aktywny projekt QGIS
project = QgsProject.instance()

# Znajdź warstwę o nazwie 'granica_terenu'
layer = None
for layer_id, layer_obj in project.mapLayers().items():
    if layer_obj.name() == 'granica_terenu':
        layer = layer_obj
        break

# Sprawdź czy warstwa została znaleziona
if layer is None:
    print("Błąd: Nie znaleziono warstwy o nazwie 'granica_terenu'")
else:
    # Sprawdź liczbę obiektów w warstwie
    feature_count = layer.featureCount()
    print(f"Warstwa 'granica_terenu' zawiera {feature_count} obiektów")
    
    # Jeśli jest więcej niż 1 obiekt, wykonaj scalanie
    if feature_count > 1:
        print("Wykryto więcej niż 1 obiekt. Uruchamiam funkcję scalania...")
        
        # Wywołanie funkcji scalania (definicja zostanie dodana ręcznie)
        scalanie_wszystkich_dzialek_z_warstwy(layer)
        
        print("Scalanie zakończone.")
    else:
        print("Warstwa zawiera 1 lub mniej obiektów. Scalanie nie jest konieczne.")
    

#remove_memory_layers()
