import processing
from PyQt5.QtCore import QVariant
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, 
    QgsFields,QgsFeature,QgsWkbTypes
)
from qgis.utils import iface
from pathlib import Path
import os
from PyQt5.QtWidgets import ( QMessageBox, QFileDialog
)
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))


def analiza_ppnz_punktow(punkty_name, dzialki_name):
    """
    Skrypt do analizy punktów PPNZ - filtrowanie, łączenie z działkami, 
    tworzenie buforów, agregacja i obliczenie powierzchni
    """
    
    # 1. Pobranie warstw z projektu
    punkty_layer = QgsProject.instance().mapLayersByName(punkty_name)[0]
    dzialki_layer = QgsProject.instance().mapLayersByName(dzialki_name)[0]
    
    print("Rozpoczynam analizę punktów PPNZ...")
    
    # 2. Filtrowanie punktów o predicted_label = 0
    print("Krok 1: Filtrowanie punktów o predicted_label = 1...")
    punkty_filtered = processing.run("native:extractbyexpression", {
        'INPUT': punkty_layer,
        'EXPRESSION': '"predicted_label" = 1',
        'OUTPUT': 'TEMPORARY_OUTPUT'
    })['OUTPUT']
    
    # 3. Łączenie atrybutów według lokalizacji (przypisanie ID_DZIALKI)
    print("Krok 2: Łączenie atrybutów według lokalizacji...")
    punkty_z_id = processing.run("native:joinattributesbylocation", {
        'INPUT': punkty_filtered,
        'JOIN': dzialki_layer,
        'JOIN_FIELDS': ['ID_DZIALKI'],
        'METHOD': 0,  # jeden do jednego
        'PREDICATE': [5],  # are within
        'DISCARD_NONMATCHING': False,
        'PREFIX': '',
        'OUTPUT': 'TEMPORARY_OUTPUT'
    })['OUTPUT']
    
    # 4. Tworzenie buforów o promieniu 25 cm (0.25 m)
    print("Krok 3: Tworzenie buforów o promieniu 25 cm...")
    bufory = processing.run("native:buffer", {
        'INPUT': punkty_z_id,
        'DISTANCE': 0.25,
        'SEGMENTS': 5,
        'END_CAP_STYLE': 0,  # okrągłe
        'JOIN_STYLE': 0,     # okrągłe
        'MITER_LIMIT': 2,
        'DISSOLVE': False,
        'SEPARATE_DISJOINT': False,
        'OUTPUT': 'TEMPORARY_OUTPUT'
    })['OUTPUT']
    
    # 5. Agregacja według ID_DZIALKI
    print("Krok 4: Agregacja buforów według ID_DZIALKI...")
    bufory_agregowane = processing.run("native:dissolve", {
    'INPUT': bufory,
    'FIELD': ['ID_DZIALKI'],
    'OUTPUT': 'TEMPORARY_OUTPUT'
    })['OUTPUT']
    
    # 6. Obliczenie powierzchni i dodanie pola PPNZ
    print("Krok 5: Obliczanie powierzchni...")
    # Dodanie pola PPNZ
    layer_z_PPNZ = processing.run("native:fieldcalculator", {
        'INPUT': bufory_agregowane,
        'FIELD_NAME': 'PPNZ',
        'FIELD_TYPE': 0,  # decimal number
        'FIELD_LENGTH': 10,
        'FIELD_PRECISION': 2,
        'FORMULA': 'round($area, 2)',
        'OUTPUT': 'TEMPORARY_OUTPUT'
    })['OUTPUT']
    
    # 7. Przypisanie wartości PPNZ do działek
    print("Krok 6: Przypisywanie wartości PPNZ do działek...")
    
    # Najpierw dodajemy pole PPNZ do warstwy działek (jeśli nie istnieje)
    dzialki_provider = dzialki_layer.dataProvider()
    field_names = [field.name() for field in dzialki_layer.fields()]
    
    if 'PPNZ' not in field_names:
        dzialki_provider.addAttributes([QgsField('PPNZ', QVariant.Double, len=10, prec=2)])
        dzialki_layer.updateFields()
    
    # Pobranie wartości PPNZ z warstwy zagregowanej
    ppnz_dict = {}
    for feature in layer_z_PPNZ.getFeatures():
        id_dzialki = feature['ID_DZIALKI']
        ppnz_value = feature['PPNZ']
        if id_dzialki:
            ppnz_dict[id_dzialki] = ppnz_value
    
    # Aktualizacja warstwy działek
    dzialki_layer.startEditing()
    
    for feature in dzialki_layer.getFeatures():
        id_dzialki = feature['ID_DZIALKI']
        if id_dzialki in ppnz_dict:
            feature['PPNZ'] = ppnz_dict[id_dzialki]
            dzialki_layer.updateFeature(feature)
        else:
            # Jeśli brak wartości PPNZ dla działki, ustawiamy 0
            feature['PPNZ'] = 0.0
            dzialki_layer.updateFeature(feature)
    
    dzialki_layer.commitChanges()
    
    # 8. Dodanie warstwy z buforami do projektu (opcjonalne)
    QgsProject.instance().addMapLayer(layer_z_PPNZ)
    layer_z_PPNZ.setName('PPNZ_bufory_agregowane')
    
    print("Analiza zakończona pomyślnie!")
    print(f"Przetworzono {len(ppnz_dict)} działek z wartościami PPNZ")
    print("Warstwa 'PPNZ_bufory_agregowane' została dodana do projektu")
    print(f"Pole 'PPNZ' zostało dodane/zaktualizowane w warstwie {dzialki_name}")


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



def usun_warstwe(nazwa_warstwy):
    """
    Usuwa warstwę z projektu QGIS na podstawie nazwy
    
    Args:
        nazwa_warstwy (str): Nazwa warstwy do usunięcia
    
    Returns:
        bool: True jeśli warstwa została usunięta, False jeśli nie znaleziono
    """
    # Pobierz instancję aktualnego projektu
    projekt = QgsProject.instance()
    
    # Znajdź warstwę po nazwie
    warstwy = projekt.mapLayersByName(nazwa_warstwy)
    
    if warstwy:
        # Usuń pierwszą znalezioną warstwę o tej nazwie
        warstwa = warstwy[0]
        projekt.removeMapLayer(warstwa.id())
        print(f"Usunięto warstwę: {nazwa_warstwy}")
        return True
    else:
        print(f"Nie znaleziono warstwy o nazwie: {nazwa_warstwy}")
        return False
    
    
def zapis_do_gpkg(layer_name, remove_old=False):
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

    # Ścieżka do projektu
    project_path = QgsProject.instance().fileName()
    if not project_path:
        print("❌ Projekt niezapisany.")
        return
    
    project_directory = Path(project_path).parent
    output_folder = Path(project_directory)
    # Tworzenie katalogu jeśli nie istnieje
    if not output_folder.exists():
        output_folder.mkdir(parents=True, exist_ok=True)
        print(f"📂 Utworzono katalog: {output_folder}")
    else:
        print(f"📁 Katalog już istnieje: {output_folder}")
        
    output_path = f"{output_folder}/{layer_name}.gpkg"

    # Pobierz warstwę
    warstwy = QgsProject.instance().mapLayersByName(layer_name)
    if not warstwy:
        print(f"❌ Nie znaleziono warstwy: {layer_name}")
        return
    warstwa = warstwy[0]

    # Obsługa konfliktu z 'fid'
    if fid_kolizja(warstwa):
        print("⚠️ Wykryto kolizję z polem 'fid'. Tworzę kopię bez tego pola.")
        warstwa = utworz_kopie_bez_fid(warstwa, f"{layer_name}_safe")

    # Zapis przy użyciu processing
    processing.run("native:savefeatures", {
    'INPUT': warstwa,
    'OUTPUT': output_path})

    print(f"✅ Warstwa zapisana do: {output_path}")

    # USUN STARĄ WARSTWE Z PROJEKTU
    #if remove_old == True:
        #usun_warstwe('granica_terenu')
    # Wczytaj z powrotem
    vlayer = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
    if vlayer.isValid():
        QgsProject.instance().addMapLayer(vlayer)
        print("✅ Warstwa wczytana ponownie do projektu.")
    else:
        print("❌ Nie udało się wczytać zapisanej warstwy.")


def remove_memory_layers():
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.dataProvider().name() == 'memory':
            QgsProject.instance().removeMapLayer(lyr.id())
            

def oblicz_wskazniki_dzialek():   
    
    # UTWORZENIE KOPII WARSTWY DZIAŁEK BEZ POLA FID            
    layer = QgsProject.instance().mapLayersByName("granica_terenu")[0]
    if layer:
        print(layer.name())
    else:
        print("Brak aktywnej warstwy")
                
    layer_name = layer.name()
    zapis_do_gpkg(layer_name, remove_old=True)
    #remove_memory_layers()
    
    
    # OBLICZANIE WSKAŹNIKÓW ZABUDOWY
    # Ustawienia wejściowe
    dzialki_layer = QgsProject.instance().mapLayersByName('granica_terenu')[0]
    budynki_layer = QgsProject.instance().mapLayersByName('budynki_w_obszarze')[0]
    
    # Sprawdź geometrię
    geom_type = QgsWkbTypes.displayString(dzialki_layer.wkbType())
    epsg = dzialki_layer.crs().authid()
    
    # Przygotuj pola (kopiujemy wszystkie z warstwy wejściowej)
    new_fields = QgsFields()
    for field in dzialki_layer.fields():
        new_fields.append(QgsField(field.name(), field.type()))
    
    # Dodaj nowe pola z analizą budynków
    new_fields.append(QgsField("S_POW_ZABUD", QVariant.Double))
    new_fields.append(QgsField("S_POW_BRUTTO", QVariant.Double))
    new_fields.append(QgsField("S_POW_KOND", QVariant.Double))
    new_fields.append(QgsField("RODZAJ_ZABUDOWY", QVariant.String))

    
    # Tworzymy warstwę wynikową – typ MultiPolygon
    dzialki_out = QgsVectorLayer(f"MultiPolygon?crs={epsg}", "dzialka_z_parametrami_zabudowy", "memory")
    dzialki_out.dataProvider().addAttributes(new_fields)
    dzialki_out.updateFields()
    
    # Próg przecięcia powierzchni budynku
    PROG_PROCENT = 0.1
    
    # Analiza działek
    for dzialka in dzialki_layer.getFeatures():
        geom_d = dzialka.geometry()
    
        suma_pow_zabud = 0
        suma_brutto = 0
        suma_kond = 0
        rodzaje_zabud = set()
    
        for budynek in budynki_layer.getFeatures():
            geom_b = budynek.geometry()
            if geom_b and geom_b.intersects(geom_d):
                czesc_wspolna = geom_b.intersection(geom_d)
                if czesc_wspolna and czesc_wspolna.area() / geom_b.area() >= PROG_PROCENT:
                    if QgsWkbTypes.geometryType(czesc_wspolna.wkbType()) == QgsWkbTypes.PolygonGeometry and czesc_wspolna.area() > 0:
                        pow = czesc_wspolna.area()
                        suma_pow_zabud += pow
                        liczba_kond = budynek["KONDYGNACJE_NADZIEMNE"] or 1
                        suma_kond += pow * float(liczba_kond)
                        liczba_kond_pod = budynek["KONDYGNACJE_PODZIEMNE"] or 0
                        suma_brutto += pow * (float(liczba_kond) + float(liczba_kond_pod))
                        rodzaje_zabud.add(str(budynek["rodzaj_zabudowy"]))
                    else:
                        print(f"⚠️ Pominięto geometrię wspólną budynku ID {budynek.id()} — nie jest poligonem lub ma zerową powierzchnię.")

        # Nowy obiekt
        nowy_feat = QgsFeature(dzialki_out.fields())
        nowy_feat.setGeometry(geom_d)
    
        # Przeniesienie oryginalnych atrybutów
        for field in dzialki_layer.fields():
            nowy_feat.setAttribute(field.name(), dzialka[field.name()])
    
        # Dodanie obliczonych atrybutów
        nowy_feat["S_POW_ZABUD"] = suma_pow_zabud
        nowy_feat["S_POW_BRUTTO"] = suma_brutto
        nowy_feat["S_POW_KOND"] = suma_kond
        nowy_feat["RODZAJ_ZABUDOWY"] = "; ".join(
        sorted(rodzaje_zabud, key=lambda x: (x != "zabudowa mieszkaniowa", x)))
    
        dzialki_out.dataProvider().addFeature(nowy_feat)
    
    # Dodaj do projektu
    QgsProject.instance().addMapLayer(dzialki_out)
    
    
    # OBLICZANIE WSKAŹNIKÓW URBANISTYCZNYCH
    layer = QgsProject.instance().mapLayersByName('dzialka_z_parametrami_zabudowy')[0]
    features = list(layer.getFeatures())
    fields = layer.fields()
    
    # Sprawdź czy są obiekty
    if not features:
        print("❌ Brak obiektów w aktywnej warstwie")
        raise Exception("Brak danych wejściowych")
    
    # Utwórz nową warstwę z taką samą geometrią i CRS
    geom_type = QgsWkbTypes.displayString(layer.wkbType())
    crs = layer.crs().authid()
    new_layer = QgsVectorLayer(f"{geom_type}?crs={crs}", "granica_terenu_wskazniki", "memory")
    provider = new_layer.dataProvider()
    
    # Skopiuj oryginalne pola + nowe wskaźniki
    new_fields = QgsFields()
    for field in fields:
        new_fields.append(QgsField(field.name(), field.type()))
    
    # Nowe pola
    new_fields.append(QgsField("PBC", QVariant.Double))
    new_fields.append(QgsField("WIZ", QVariant.Double))
    new_fields.append(QgsField("WNIZ", QVariant.Double))
    new_fields.append(QgsField("wpz_float", QVariant.Double))
    new_fields.append(QgsField("wpbc_float", QVariant.Double))
    new_fields.append(QgsField("WPZ", QVariant.String))
    new_fields.append(QgsField("WPBC", QVariant.String))
    new_fields.append(QgsField("Lp.", QVariant.Int))
    
    provider.addAttributes(new_fields)
    new_layer.updateFields()
    
    # Obliczenia i tworzenie nowych feature'ów
    for i, f in enumerate(features):
        geom = f.geometry()
        attrs = f.attributes()
        attr_dict = {field.name(): val for field, val in zip(fields, attrs)}
    
        try:
            pole = float(attr_dict.get("POLE_EWIDENCYJNE", 0)) or 0
            zabud = float(attr_dict.get("S_POW_ZABUD", 0)) or 0 # powierzchnia zabudowy
            brutto = float(attr_dict.get("S_POW_BRUTTO", 0)) or 0 # powierzchnia brutto
            kond = float(attr_dict.get("S_POW_KOND", 0)) or 0 # suma powierzchni kondygnacji nadziemnych
            ppnz = float(attr_dict.get("PPNZ", 0)) # powierzchnia przekształcona niebędąca zabudową
        except Exception as e:
            print(f"⚠️ Błąd w konwersji wartości dla feature {i}: {e}")
            continue
        pbc = (pole - (ppnz + zabud)) if pole else 0
        wiz = round(brutto / pole, 2) if pole else 0
        wniz = round(kond / pole, 2) if pole else 0
        wpz_float = round(zabud / pole, 2) if pole else 0
        wpbc_float = round(pbc / pole, 2) if pole else 0
        wpz = f"{round((zabud / pole) * 100):.0f}%" if pole else "0%"
        wpbc = f"{round((pbc / pole) * 100):.0f}%" if pole else "0%"
        
        # Stwórz nowy feature
        new_feat = QgsFeature(new_layer.fields())
        new_feat.setGeometry(geom)
        for j, field in enumerate(fields):
            new_feat.setAttribute(j, f[field.name()])
        new_feat.setAttribute("PBC", pbc)
        new_feat.setAttribute("WIZ", wiz)
        new_feat.setAttribute("WNIZ", wniz)
        new_feat.setAttribute("wpz_float", wpz_float)
        new_feat.setAttribute("wpbc_float", wpbc_float)
        new_feat.setAttribute("WPZ", wpz)
        new_feat.setAttribute("WPBC", wpbc)
        new_feat.setAttribute("Lp.", i + 1)
    
        provider.addFeatures([new_feat])
    
    new_layer.updateExtents()
    QgsProject.instance().addMapLayer(new_layer)
    
    print("✅ Warstwa została utworzona poprawnie.")
    zapis_do_gpkg('granica_terenu_wskazniki')
    remove_memory_layers()
    style_name = "style/WSKAZNIKI_teren_inwestycji.qml"
    style_path = os.path.join(SCRIPTS_PATH, style_name)
    apply_qml_style_to_layer(layer = 'granica_terenu_wskazniki', 
                             qml_file_path=style_path, 
                             show_messages=True)


# Uruchomienie skryptu
analiza_ppnz_punktow(punkty_name='punkty_pbc_wyniki_predykcji_teren_inwestycji',
                    dzialki_name='granica_terenu')

oblicz_wskazniki_dzialek()