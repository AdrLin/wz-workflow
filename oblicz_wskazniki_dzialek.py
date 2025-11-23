#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jul 22 17:16:26 2025

@author: adrian
"""
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsDataSourceUri,
    QgsFields,QgsFeature,QgsWkbTypes,QgsProcessing,
    QgsProcessingContext, QgsFeatureRequest)
from qgis import processing
from PyQt5.QtCore import QVariant
from qgis.utils import iface
from pathlib import Path
import os
from PyQt5.QtWidgets import ( QMessageBox, QFileDialog)
import time

# Zmniejsz użycie pamięci cache
from qgis.core import QgsSettings
QgsSettings().setValue('/qgis/memoryCacheSize', 200)  # MB zamiast domyślnych 300MB
   

SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

iface.mapCanvas().setRenderFlag(False)

# Pobierz CRS z projektu
project_crs = QgsProject.instance().crs()
print(f"CRS projektu: {project_crs.authid()}")

# Funkcja pomocnicza do pobierania warstwy
def get_layer_safe(layer_name):
    """Bezpiecznie pobiera warstwę z projektu"""
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if layers:
        return layers[0]
    else:
        print(f"OSTRZEŻENIE: Warstwa '{layer_name}' nie została znaleziona")
        return None


def analiza_pbc_punktow_smart(punkty_name, dzialki_name):
    """
    Inteligentna analiza - wybiera najlepszą metodę automatycznie
    """
    
    # Sprawdź czy warstwa jest w PostGIS
    punkty_layer = QgsProject.instance().mapLayersByName(punkty_name)[0]
    
    if punkty_layer.dataProvider().name() == 'postgres':
        print("🚀 Wykryto PostGIS - używam szybkiej metody SQL")
        return analiza_pbc_postgis(punkty_name, dzialki_name)
    else:
        # Sprawdź liczbę punktów
        count = punkty_layer.featureCount()
        
        if count > 500000:
            print(f"⚠️ Duża liczba punktów ({count}). Rozważ użycie PostGIS dla lepszej wydajności.")
            print("📖 Zobacz dokumentację jak skonfigurować PostGIS")
        
        print("💻 Używam standardowej metody QGIS")
        return analiza_pbc_punktow_optimized_v3(punkty_name, dzialki_name)


def analiza_pbc_postgis(punkty_name, dzialki_name):
    """Szybka metoda dla warstw PostGIS"""
    punkty_layer = QgsProject.instance().mapLayersByName(punkty_name)[0]
    dzialki_layer = QgsProject.instance().mapLayersByName(dzialki_name)[0]
    
    # Pobierz nazwę tabeli i schemat
    uri = QgsDataSourceUri(punkty_layer.source())
    schema_punkty = uri.schema()
    table_punkty = uri.table()
    
    uri_dzialki = QgsDataSourceUri(dzialki_layer.source())
    schema_dzialki = uri_dzialki.schema()
    table_dzialki = uri_dzialki.table()
    
    # SQL wykonujący całą analizę w bazie
    sql = f"""
    -- Utwórz tymczasową tabelę z buforami
    DROP TABLE IF EXISTS temp_pbc_bufory;
    CREATE TEMP TABLE temp_pbc_bufory AS
    WITH punkty_filtered AS (
        SELECT geom, "ID_DZIALKI"
        FROM "{schema_punkty}"."{table_punkty}"
    WHERE 
        ("predicted_label" = '0.0' OR 
         "predicted_label"::text = '0' OR 
         "predicted_label"::text = '0.0' OR 
         "predicted_label"::double precision = 0)          
        AND "ID_DZIALKI" IS NOT NULL
        ),
    bufory_agregowane AS (
        SELECT 
            "ID_DZIALKI",
            ST_Union(ST_Buffer(geom, 0.25, 5)) as geom
        FROM punkty_filtered
        GROUP BY "ID_DZIALKI"
    )
    SELECT 
        "ID_DZIALKI",
        ROUND(ST_Area(geom)::numeric, 2) as "PBC",
        geom
    FROM bufory_agregowane;
    
    -- Dodaj pole PBC jeśli nie istnieje
    ALTER TABLE "{schema_dzialki}"."{table_dzialki}" 
    ADD COLUMN IF NOT EXISTS "PBC" double precision;
    
    -- Zaktualizuj działki
    UPDATE "{schema_dzialki}"."{table_dzialki}" d
    SET "PBC" = COALESCE(b."PBC", 0)
    FROM temp_pbc_bufory b
    WHERE d."ID_DZIALKI" = b."ID_DZIALKI";
    """
    
    # Wykonaj SQL
    try:
        # Wykonaj przez connection
        import psycopg2
        conn = psycopg2.connect(
            host=uri.host(),
            port=uri.port(),
            database=uri.database(),
            user=uri.username(),
            password=uri.password()
        )
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Analiza zakończona w PostGIS!")
        return True
        
    except Exception as e:
        print(f"❌ Błąd PostGIS: {e}")
        print("Przechodzę na metodę standardową...")
        return analiza_pbc_punktow_optimized_v3(punkty_name, dzialki_name)


def analiza_pbc_punktow_optimized_v3(punkty_name, dzialki_name):
    """
    POPRAWIONA wersja - dissolve osobno dla każdej działki
    """    
    start_time = time.time()
    
    # Bezpieczne pobranie warstw z walidacją
    punkty_layers = QgsProject.instance().mapLayersByName(punkty_name)
    dzialki_layers = QgsProject.instance().mapLayersByName(dzialki_name)
    
    if not punkty_layers:
        raise ValueError(f"Nie znaleziono warstwy: {punkty_name}")
    if not dzialki_layers:
        raise ValueError(f"Nie znaleziono warstwy: {dzialki_name}")
    
    # Jeśli jest wiele warstw o tej samej nazwie, weź tę z największą liczbą obiektów
    punkty_layer = max(punkty_layers, key=lambda l: l.featureCount())
    dzialki_layer = max(dzialki_layers, key=lambda l: l.featureCount())
    
    total_points = punkty_layer.featureCount()
    
    if total_points == 0:
        raise ValueError(f"Warstwa {punkty_name} jest pusta!")
    
    from qgis.utils import iface
    from PyQt5.QtWidgets import QProgressDialog
    from PyQt5.QtCore import Qt
    
    progress = QProgressDialog(
        f"Analiza PBC: {total_points:,} punktów\nTo może potrwać kilka minut...",
        "Anuluj", 0, 100, iface.mainWindow()
    )
    progress.setWindowTitle("Analiza PBC")
    progress.setWindowModality(Qt.WindowModal)
    progress.setValue(0)
    
    try:
        iface.mapCanvas().setRenderFlag(False)
        
        context = QgsProcessingContext()
        context.setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)
        
        # 1. Filtrowanie
        progress.setLabelText("Krok 1/5: Filtrowanie punktów...")
        progress.setValue(10)
        
        # Proste wyrażenie dla wartości numerycznych 0 lub 0.0
        punkty_filtered = processing.run("native:extractbyexpression", {
            'INPUT': punkty_layer,
            'EXPRESSION': '"predicted_label" = 0',
            'OUTPUT': 'memory:'
        })['OUTPUT']
        
        filtered_count = punkty_filtered.featureCount()
        print(f"✅ Przefiltrowano: {filtered_count:,} punktów z {total_points:,}")
        
        if filtered_count == 0:
            raise ValueError("Filtrowanie nie zwróciło żadnych punktów! Sprawdź wartości w polu 'predicted_label'.")
        
        if progress.wasCanceled():
            return None
        
        # 2. JOIN z działkami
        progress.setLabelText("Krok 2/5: Przypisywanie do działek...")
        progress.setValue(20)
        
        punkty_z_id = processing.run("native:joinattributesbylocation", {
            'INPUT': punkty_filtered,
            'JOIN': dzialki_layer,
            'JOIN_FIELDS': ['ID_DZIALKI'],
            'METHOD': 0,
            'PREDICATE': [5],
            'DISCARD_NONMATCHING': True,
            'PREFIX': '',
            'OUTPUT': 'memory:'
        }, context=context)['OUTPUT']
        
        if progress.wasCanceled():
            return None
        
        # 3. Buffer (bez dissolve!)
        progress.setLabelText("Krok 3/5: Tworzenie buforów...")
        progress.setValue(35)
        
        bufory_all = processing.run("native:buffer", {
            'INPUT': punkty_z_id,
            'DISTANCE': 0.25,
            'SEGMENTS': 5,
            'DISSOLVE': False,  # Nie łączymy tutaj!
            'OUTPUT': 'memory:'
        }, context=context)['OUTPUT']
        
        if progress.wasCanceled():
            return None
        
        # 4. KLUCZOWE: Dissolve Z GRUPOWANIEM po ID_DZIALKI
        progress.setLabelText("Krok 4/5: Agregacja buforów per działka...")
        progress.setValue(60)
        
        from qgis.core import Qgis
        field_param = 'FIELD' if Qgis.QGIS_VERSION_INT >= 33600 else 'FIELD'
        
        # To agreguje bufory OSOBNO dla każdej działki!
        bufory_final = processing.run("native:dissolve", {
            'INPUT': bufory_all,
            field_param: ['ID_DZIALKI'],  # ← KLUCZOWE!
            'OUTPUT': 'memory:'
        }, context=context)['OUTPUT']
        
        if progress.wasCanceled():
            return None
        
        print(f"✅ Utworzono {bufory_final.featureCount()} zagregowanych poligonów")
        
        # 5. Oblicz PBC i zaktualizuj działki
        progress.setLabelText("Krok 5/5: Aktualizacja działek...")
        progress.setValue(80)
        
        # Dodaj pole
        dzialki_provider = dzialki_layer.dataProvider()
        field_names = [f.name() for f in dzialki_layer.fields()]
        
        if 'PBC' not in field_names:
            dzialki_provider.addAttributes([
                QgsField('PBC', QVariant.Double, len=10, prec=2)
            ])
            dzialki_layer.updateFields()
        
        # Słownik z wartościami PBC
        pbc_dict = {}
        for feat in bufory_final.getFeatures():
            id_dzialki = feat['ID_DZIALKI']
            if id_dzialki:
                pbc_dict[id_dzialki] = round(feat.geometry().area(), 2)
        
        # Aktualizacja wsadowa
        dzialki_layer.startEditing()
        pbc_idx = dzialki_layer.fields().indexOf('PBC')
        updates = {}
        
        for feat in dzialki_layer.getFeatures():
            updates[feat.id()] = {
                pbc_idx: pbc_dict.get(feat['ID_DZIALKI'], 0.0)
            }
        
        dzialki_layer.dataProvider().changeAttributeValues(updates)
        dzialki_layer.commitChanges()
        
        # Dodaj warstwę bufory
        QgsProject.instance().addMapLayer(bufory_final)
        bufory_final.setName('PBC_bufory_agregowane')
        
        progress.setValue(100)
        
        total_time = time.time() - start_time
        
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(
            iface.mainWindow(),
            "Analiza zakończona",
            f"✅ Analiza PBC zakończona pomyślnie!\n\n"
            f"📊 Przetworzono: {total_points:,} punktów\n"
            f"📊 Utworzono: {bufory_final.featureCount()} poligonów PBC\n"
            f"📊 Zaktualizowano: {len(pbc_dict)} działek\n"
            f"⏱️ Czas: {total_time/60:.1f} min"
        )
        
        return bufory_final
        
    finally:
        iface.mapCanvas().setRenderFlag(True)
        progress.close()


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
        # ⬅️ NIE dodajemy kopii do projektu tutaj!
        return kopia

    # Ścieżka do projektu
    project_path = QgsProject.instance().fileName()
    if not project_path:
        print("❌ Projekt niezapisany.")
        return
    
    project_directory = Path(project_path).parent
    output_folder = Path(project_directory)
    if not output_folder.exists():
        output_folder.mkdir(parents=True, exist_ok=True)
        print(f"📂 Utworzono katalog: {output_folder}")
        
    output_path = f"{output_folder}/{layer_name}.gpkg"

    # Pobierz warstwę
    warstwy = QgsProject.instance().mapLayersByName(layer_name)
    if not warstwy:
        print(f"❌ Nie znaleziono warstwy: {layer_name}")
        return
    warstwa = warstwy[0]
    
    # ⬅️ ZAPAMIĘTAJ ID ORYGINALNEJ WARSTWY DO USUNIĘCIA
    original_layer_id = warstwa.id()
    
    # Warstwa do zapisu (może być kopia lub oryginał)
    warstwa_do_zapisu = warstwa

    # Obsługa konfliktu z 'fid'
    if fid_kolizja(warstwa):
        print("⚠️ Wykryto kolizję z polem 'fid'. Tworzę kopię bez tego pola.")
        # ⬅️ Kopia ma tę samą nazwę co docelowa!
        warstwa_do_zapisu = utworz_kopie_bez_fid(warstwa, layer_name)
        # NIE dodajemy kopii do projektu - używamy jej tylko do zapisu

    # Zapis przy użyciu processing
    processing.run("native:savefeatures", {
        'INPUT': warstwa_do_zapisu,
        'OUTPUT': output_path
    })

    print(f"✅ Warstwa zapisana do: {output_path}")

    # ⬅️ USUŃ ORYGINALNĄ WARSTWĘ MEMORY
    QgsProject.instance().removeMapLayer(original_layer_id)
    print(f"🧹 Usunięto warstwę tymczasową: {layer_name}")

    # USUN STARĄ WARSTWE Z PROJEKTU (jeśli remove_old=True)
    if remove_old:
        usun_warstwe('dzialki_zgodne_z_funkcja')
    
    # Wczytaj z powrotem
    vlayer = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
    if vlayer.isValid():
        QgsProject.instance().addMapLayer(vlayer)
        print(f"✅ Warstwa '{layer_name}' wczytana ponownie do projektu.")
    else:
        print(f"❌ Nie udało się wczytać zapisanej warstwy: {layer_name}")
        print(f"   Sprawdź czy plik istnieje: {output_path}")
        
        
def remove_memory_layers():
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.dataProvider().name() == 'memory':
            QgsProject.instance().removeMapLayer(lyr.id())
            

def oblicz_wskazniki_dzialek(dzialki_layer_name, new_layer_name):   
    
    # UTWORZENIE KOPII WARSTWY DZIAŁEK BEZ POLA FID            
    layer = QgsProject.instance().mapLayersByName(dzialki_layer_name)[0]
    if layer:
        print(layer.name())
    else:
        print("Brak aktywnej warstwy")
                
    
    # OBLICZANIE WSKAŹNIKÓW ZABUDOWY
    # Ustawienia wejściowe
    dzialki_layer = QgsProject.instance().mapLayersByName(dzialki_layer_name)[0]
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
    dzialki_out = QgsVectorLayer(f"MultiPolygon?crs={epsg}", f"{dzialki_layer_name}_z_parametrami_zabudowy", "memory")
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
                        # rodzaje_zabud.add(str(budynek["rodzaj_zabudowy"]))
                        rodzaj = str(budynek["rodzaj_zabudowy"])
                        if '(' in rodzaj:
                            rodzaj = rodzaj.split('(')[0].strip()  # Bierz tylko część przed nawiasem
                        rodzaje_zabud.add(rodzaj)
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
    # layer = QgsProject.instance().mapLayersByName('dzialki_z_parametrami_zabudowy')[0]
    layer = dzialki_out
    # Nie ładuj wszystkich obiektów do pamięci naraz
    features = layer.getFeatures()  # Iterator, nie lista!
    fields = layer.fields()
    
    # Sprawdź czy są obiekty
    if not features:
        print("❌ Brak obiektów w aktywnej warstwie")
        raise Exception("Brak danych wejściowych")
    
    # Utwórz nową warstwę z taką samą geometrią i CRS
    geom_type = QgsWkbTypes.displayString(layer.wkbType())
    crs = layer.crs().authid()
    new_layer = QgsVectorLayer(f"{geom_type}?crs={crs}", new_layer_name, "memory")
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
    feature_count = layer.featureCount()
    for i, f in enumerate(features):
        if i % 1000 == 0:  # Progress info
            print(f"Przetworzono {i}/{feature_count} obiektów...")
        geom = f.geometry()
        attrs = f.attributes()
        attr_dict = {field.name(): val for field, val in zip(fields, attrs)}
    
        try:
            pole = float(attr_dict.get("POLE_EWIDENCYJNE", 0)) or 0
            zabud = float(attr_dict.get("S_POW_ZABUD", 0)) or 0 # powierzchnia zabudowy
            brutto = float(attr_dict.get("S_POW_BRUTTO", 0)) or 0 # powierzchnia brutto
            kond = float(attr_dict.get("S_POW_KOND", 0)) or 0 # suma powierzchni kondygnacji nadziemnych
            pbc = float(attr_dict.get("PBC", 0)) # powierzchnia biologicznie czynna
        except Exception as e:
            print(f"⚠️ Błąd w konwersji wartości dla feature {i}: {e}")
            continue
        wiz = round(brutto / pole, 2) if pole else 0
        wniz = round(kond / pole, 2) if pole else 0
        wpz_float = round(zabud / pole, 2) if pole else 0
        wpbc_float = round(pbc / pole, 2) if pole else 0
        if wpbc_float > 1:
            print(f"UWAGA! obliczona wartość WPBC przekracza 100% o {wpbc_float - 1} ")
            wpbc_float = 1

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
    
    # ⬅️ USUŃ WARSTWĘ TYMCZASOWĄ _z_parametrami_zabudowy
    temp_layer_name = f"{dzialki_layer_name}_z_parametrami_zabudowy"
    usun_warstwe(temp_layer_name)
    print(f"🧹 Usunięto warstwę tymczasową: {temp_layer_name}")    
    zapis_do_gpkg(new_layer_name,remove_old=False )
   
    style_name = "style/WSKAZNIKI - male literki.qml"
    style_path = os.path.join(SCRIPTS_PATH, style_name)
    apply_qml_style_to_layer(layer = new_layer_name, 
                             qml_file_path=style_path, 
                             show_messages=True)


def przytnij_punkty_pbc_do_maski(nazwa_warstwy_maski):
    """
    Przycina warstwę punktową 'scalone_punkty_PBC' do warstwy-maski.
    
    Parametry:
    ----------
    nazwa_warstwy_maski : str
        Nazwa warstwy wektorowej, która będzie używana jako maska
    
    Zwraca:
    -------
    QgsVectorLayer lub None
        Przycięta warstwa punktowa lub None w przypadku błędu
    """
    
    # Pobranie warstwy źródłowej
    warstwa_punktowa = QgsProject.instance().mapLayersByName('scalone_punkty_PBC')
    
    if not warstwa_punktowa:
        print("Błąd: Nie znaleziono warstwy 'scalone_punkty_PBC'")
        return None
    
    warstwa_punktowa = warstwa_punktowa[0]
    
    # Pobranie warstwy maski
    warstwa_maski = QgsProject.instance().mapLayersByName(nazwa_warstwy_maski)
    
    if not warstwa_maski:
        print(f"Błąd: Nie znaleziono warstwy '{nazwa_warstwy_maski}'")
        return None
    
    warstwa_maski = warstwa_maski[0]
    
    # Parametry algorytmu clip
    parametry = {
        'INPUT': warstwa_punktowa,
        'OVERLAY': warstwa_maski,
        'OUTPUT': 'memory:'  # Wynik w pamięci, można zmienić na ścieżkę do pliku
    }
    
    # Wykonanie algorytmu clip
    try:
        wynik = processing.run("native:clip", parametry)
        warstwa_wynikowa = wynik['OUTPUT']
        
        # Nadanie własnej nazwy warstwie
        warstwa_wynikowa.setName(f'scalone_punkty_PBC_przyciete_{nazwa_warstwy_maski}')
        
        # Dodanie warstwy do projektu
        QgsProject.instance().addMapLayer(warstwa_wynikowa)
        
        print(f"Pomyślnie przycięto warstwę do maski '{nazwa_warstwy_maski}'")
        return warstwa_wynikowa
        
    except Exception as e:
        print(f"Błąd podczas przycinania: {str(e)}")
        return None




def prepare_punkty_pbc():
    # Pobierz warstwy z projektu QGIS
    print("\nPobieranie warstw Classification...")
    classification_layers = []
    layer_names = ['Classification_3', 'Classification_4', 'Classification_5', 'Classification_9']
    
    for name in layer_names:
        layer = get_layer_safe(name)
        if layer:
            classification_layers.append(layer)
            print(f"  ✓ {name} - znaleziono ({layer.featureCount()} obiektów)")
        else:
            print(f"  ✗ {name} - brak warstwy")
    
    # Sprawdź czy są jakieś warstwy do scalenia
    if not classification_layers:
        print("BŁĄD: Nie znaleziono żadnej warstwy Classification do scalenia!")
        raise Exception("Brak warstw Classification w projekcie")
    
    print(f"\nZnaleziono {len(classification_layers)} warstw do scalenia")
    
    # Krok 1: Scal znalezione warstwy Classification
    print("\nScalanie warstw Classification...")
    merged_layer = processing.run("native:mergevectorlayers", {
        'LAYERS': classification_layers,
        'CRS': project_crs,
        'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
    })['OUTPUT']
    
    print(f"Scalono {merged_layer.featureCount()} obiektów")
    
    # Krok 2: Dodaj kolumnę 'predicted_label' i wypełnij wartością 0
    print("\nDodawanie kolumny 'predicted_label'...")
    merged_with_field = processing.run("native:fieldcalculator", {
        'INPUT': merged_layer,
        'FIELD_NAME': 'predicted_label',
        'FIELD_TYPE': 2,  # 1 = Integer, 2 = String
        'FIELD_LENGTH': 10,
        'FIELD_PRECISION': 0,
        'FORMULA': "0.0",
        'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
    })['OUTPUT']
    
    print("Kolumna dodana i wypełniona wartością 0")
    
    # Krok 3: Pobierz warstwę 'punkty_pbc_wyniki_predykcji'
    print("\nPobieranie warstwy 'punkty_pbc_wyniki_predykcji'...")
    punkty_pbc_dzialki = get_layer_safe('punkty_pbc_wyniki_predykcji')
    
    if not punkty_pbc_dzialki:
        print("BŁĄD: Nie znaleziono warstwy 'punkty_pbc_wyniki_predykcji'!")
        raise Exception("Brak warstwy 'punkty_pbc_wyniki_predykcji' w projekcie")
    
    print(f"  ✓ punkty_pbc_wyniki_predykcji - znaleziono ({punkty_pbc_dzialki.featureCount()} obiektów)")
    
    # Krok 4: Pobierz warstwę 'punkty_pbc_wyniki_predykcji_teren_inwestycji'
    print("\nPobieranie warstwy 'punkty_pbc_wyniki_predykcji_teren_inwestycji'...")
    
    
        # raise Exception("Brak warstwy 'punkty_pbc_wyniki_predykcji_teren_inwestycji' w projekcie")
    
    
    # Krok 5: Złącz warstwę 'punkty_pbc_wyniki_predykcji' i 'punkty_pbc_wyniki_predykcji_teren_inwestycji'
    try:
        punkty_pbc_teren = get_layer_safe('punkty_pbc_wyniki_predykcji_teren_inwestycji')
        print(f"  ✓ punkty_pbc_wyniki_predykcji_teren_inwestycji - znaleziono ({punkty_pbc_teren.featureCount()} obiektów)")
    
        print("\nŁączenie warstw 'punkty_pbc_wyniki_predykcji'...")
        merged_pbc = processing.run("native:mergevectorlayers", {
            'LAYERS': [punkty_pbc_dzialki, punkty_pbc_teren],
            'CRS': project_crs,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        })['OUTPUT']
    except:
        merged_pbc = punkty_pbc_dzialki
    if not punkty_pbc_teren:
        print("BŁĄD: Nie znaleziono warstwy 'punkty_pbc_wyniki_predykcji_teren_inwestycji'!")
    

    
    # Krok 6: Złącz warstwę wynikową i 'punkty_pbc'
    print("\nŁączenie warstw wynikowych")
    final_layer = processing.run("native:mergevectorlayers", {
        'LAYERS': [merged_with_field, merged_pbc],
        'CRS': project_crs,
        'OUTPUT': 'memory:'
    })['OUTPUT']
    print(f"Warstwa finalna zawiera {final_layer.featureCount()} obiektów")
    
    # Dodaj wynikową warstwę do projektu
    final_layer.setName('scalone_punkty_PBC')
    QgsProject.instance().addMapLayer(final_layer)
    # zapis_do_gpkg('scalone_punkty_PBC',remove_old=False)
        
    print("\n✓ Gotowe! Warstwa została dodana do projektu.")


# OSZACOWANIE PBC    
prepare_punkty_pbc()
przytnij_punkty_pbc_do_maski('dzialki_zgodne_z_funkcja')     
analiza_pbc_punktow_smart(punkty_name ='scalone_punkty_PBC_przyciete_dzialki_zgodne_z_funkcja',
                    dzialki_name = 'dzialki_zgodne_z_funkcja'
                    )
# obliczanie wskaznikow
oblicz_wskazniki_dzialek(dzialki_layer_name="dzialki_zgodne_z_funkcja", 
                         new_layer_name="dzialki_ze_wskaznikami")

# to samo dla działki przedmiotowej
try:
    przytnij_punkty_pbc_do_maski('granica_terenu')     
    
    analiza_pbc_punktow_smart(punkty_name ='scalone_punkty_PBC_przyciete_granica_terenu',
                        dzialki_name = 'granica_terenu'
                        )
    # obliczanie wskaznikow
    oblicz_wskazniki_dzialek(dzialki_layer_name="granica_terenu", 
                             new_layer_name="granica_terenu_wskazniki")
except:
    print("Brak wskaźników dla działki przedmiotowej")

iface.mapCanvas().setRenderFlag(True)
