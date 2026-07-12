#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jul 22 17:16:26 2025

@author: adrian
"""
from qgis.core import (QgsPointXY,
    QgsProject, QgsVectorLayer, QgsField,QgsSpatialIndex,
    QgsFields,QgsFeature,QgsWkbTypes,QgsGeometry,
    QgsFeatureRequest)
from qgis import processing
from PyQt5.QtWidgets import QProgressDialog, QApplication
from PyQt5.QtCore import QVariant
from qgis.utils import iface
from pathlib import Path
import os
from PyQt5.QtWidgets import ( QMessageBox, QFileDialog)
import time
from PyQt5.QtCore import Qt
import math
# Zmniejsz użycie pamięci cache
from qgis.core import QgsSettings
QgsSettings().setValue('/qgis/memoryCacheSize', 200)  # MB zamiast domyślnych 300MB
   

SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

iface.mapCanvas().setRenderFlag(False)

# Pobierz CRS z projektu
project_crs = QgsProject.instance().crs()
print(f"CRS projektu: {project_crs.authid()}")


def punkty_na_heksagony(layer_name, hex_size=0.36):
    """Zamienia warstwę punktową na warstwę poligonów heksagonalnych (memory layer)."""
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        print(f"  ⚠️  Brak warstwy: {layer_name}")
        return None
    layer = layers[0]
    crs = layer.crs().authid()

    # Wektoryzowane przypisanie punktów do heksagonów
    coords = {}
    for feat in layer.getFeatures():
        pt = feat.geometry().asPoint()
        x, y = pt.x(), pt.y()
        q = (2/3 * x) / hex_size
        r = (-1/3 * x + math.sqrt(3)/3 * y) / hex_size
        q_r = round(q)
        r_r = round(r)
        s_r = round(-q - r)
        q_d, r_d, s_d = abs(q_r - q), abs(r_r - r), abs(s_r - (-q - r))
        if q_d > r_d and q_d > s_d:
            q_r = -r_r - s_r
        elif r_d > s_d:
            r_r = -q_r - s_r
        coords[(q_r, r_r)] = True  # deduplikacja

    # Twórz poligony
    hex_layer = QgsVectorLayer(f"Polygon?crs={crs}", f"{layer_name}_hex", "memory")
    provider = hex_layer.dataProvider()
    provider.addAttributes([QgsField("hex_q", QVariant.Int), QgsField("hex_r", QVariant.Int)])
    hex_layer.updateFields()

    features = []
    for (q, r) in coords:
        cx = hex_size * 1.5 * q
        cy = hex_size * (math.sqrt(3)/2 * q + math.sqrt(3) * r)
        pts = []
        for i in range(6):
            angle = math.radians(60 * i)
            pts.append(QgsPointXY(cx + hex_size * math.cos(angle), cy + hex_size * math.sin(angle)))
        pts.append(pts[0])

        feat = QgsFeature(hex_layer.fields())
        feat.setGeometry(QgsGeometry.fromPolygonXY([pts]))
        feat.setAttribute("hex_q", int(q))
        feat.setAttribute("hex_r", int(r))
        features.append(feat)

    provider.addFeatures(features)
    hex_layer.updateExtents()
    print(f"  ✓ {layer_name} → {len(features)} heksagonów")
    return hex_layer

def analiza_pbc_per_dzialka(dzialki_layer_name, nazwa_maski=None):
    """
    Oblicza PBC dla każdej działki.
    Wszystkie warstwy (punktowe i predykcyjne) są traktowane jako heksagony.

    Parametry
    ---------
    dzialki_layer_name : str
        Nazwa warstwy działek (np. 'dzialki_zgodne_z_funkcja')
    nazwa_maski : str lub None
        Jeśli podano — używa tej warstwy jako działek (np. 'granica_terenu').
    """

    start_time = time.time()

    # === 1. Pobierz warstwę działek ===
    target_name = nazwa_maski if nazwa_maski else dzialki_layer_name
    dzialki_layers = QgsProject.instance().mapLayersByName(target_name)
    if not dzialki_layers:
        raise ValueError(f"Nie znaleziono warstwy działek: {target_name}")
    dzialki_layer = dzialki_layers[0]
    n_dzialek = dzialki_layer.featureCount()
    print(f"\n📐 Działki: {target_name} ({n_dzialek} obiektów)")

    # === 2. Przygotuj źródła heksagonów PBC ===
    print("\n📐 Konwersja warstw punktowych na heksagony...")
    all_hex_sources = []

    # Warstwy punktowe → heksagony (wszystkie = PBC)
    for layer_name in ['Classification_3', 'Classification_4',
                       'Classification_5', 'Classification_9']:
        hex_layer = punkty_na_heksagony(layer_name, hex_size=0.36)
        if hex_layer:
            all_hex_sources.append({
                'layer':  hex_layer,
                'index':  QgsSpatialIndex(hex_layer.getFeatures()),
                'filter': None,
                'name':   layer_name,
            })

    # Warstwy predykcji PBC (już są heksagonami, filtrowane po predicted_label)
    for layer_name, filtr in [
        ('heksagony_pbc_predykcja',       '"predicted_label" = 0'),
        ('heksagony_pbc_predykcja_teren', '"predicted_label" = 0'),
    ]:
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if not layers:
            print(f"  ⚠️  Pominięto (brak): {layer_name}")
            continue
        layer = layers[0]
        all_hex_sources.append({
            'layer':  layer,
            'index':  QgsSpatialIndex(layer.getFeatures()),
            'filter': filtr,
            'name':   layer_name,
        })
        print(f"  ✓ {layer_name} ({layer.featureCount():,} hex)")

    if not all_hex_sources:
        raise ValueError("Brak jakichkolwiek warstw PBC!")

    # === 3. Dodaj pole PBC jeśli nie istnieje ===
    provider = dzialki_layer.dataProvider()
    if 'PBC' not in [f.name() for f in dzialki_layer.fields()]:
        provider.addAttributes([QgsField('PBC', QVariant.Double, len=10, prec=2)])
        dzialki_layer.updateFields()
        print("  ✓ Dodano pole PBC")

    pbc_idx = dzialki_layer.fields().indexOf('PBC')

    # === 4. Progress dialog ===
    progress = QProgressDialog(
        f"Analiza PBC per działka\n0 / {n_dzialek}",
        "Anuluj", 0, n_dzialek, iface.mainWindow()
    )
    progress.setWindowTitle("Analiza PBC")
    progress.setWindowModality(Qt.WindowModal)
    progress.setValue(0)

    # === 5. Pętla po działkach ===
    updates       = {}
    pbc_dict      = {}
    empty_dzialki = 0

    try:
        iface.mapCanvas().setRenderFlag(False)

        for i, dzialka in enumerate(dzialki_layer.getFeatures()):

            if progress.wasCanceled():
                print("⛔ Anulowano przez użytkownika")
                break

            if i % 10 == 0:
                elapsed = time.time() - start_time
                eta = (elapsed / max(i, 1)) * (n_dzialek - i)
                progress.setLabelText(
                    f"Analiza PBC per działka\n"
                    f"{i} / {n_dzialek}  |  ETA: {eta/60:.1f} min"
                )
                progress.setValue(i)
                QApplication.processEvents()

            if i % 100 == 0 and i > 0:
                elapsed = time.time() - start_time
                eta = (elapsed / i) * (n_dzialek - i)
                print(f"  [{i}/{n_dzialek}] "
                      f"elapsed: {elapsed/60:.1f} min | "
                      f"ETA: {eta/60:.1f} min | "
                      f"PBC>0: {len(pbc_dict)}")

            geom_dzialki = dzialka.geometry()
            if not geom_dzialki or geom_dzialki.isEmpty():
                continue

            # --- Zbierz heksagony PBC w obrębie działki ---
            hex_geoms = []

            for src in all_hex_sources:
                bbox = geom_dzialki.boundingBox()
                candidate_ids = src['index'].intersects(bbox)
                if not candidate_ids:
                    continue

                request = QgsFeatureRequest().setFilterFids(candidate_ids)
                if src['filter']:
                    request.setFilterExpression(src['filter'])

                for feat in src['layer'].getFeatures(request):
                    geom_hex = feat.geometry()
                    if not geom_hex or not geom_dzialki.intersects(geom_hex):
                        continue
                    clipped = geom_hex.intersection(geom_dzialki)
                    if clipped and not clipped.isEmpty():
                        hex_geoms.append(clipped)

            # --- Oblicz PBC ---
            if hex_geoms:
                union = QgsGeometry.unaryUnion(hex_geoms)
                pbc_area = round(union.area(), 2) if union and not union.isEmpty() else 0.0
            else:
                pbc_area = 0.0
                empty_dzialki += 1

            updates[dzialka.id()] = {pbc_idx: pbc_area}
            pbc_dict[dzialka.id()] = pbc_area

        # === 6. Batch update działek ===
        dzialki_layer.startEditing()
        provider.changeAttributeValues(updates)
        dzialki_layer.commitChanges()

    finally:
        iface.mapCanvas().setRenderFlag(True)
        progress.close()

    # === 7. Raport ===
    total_time = time.time() - start_time
    print("\n✅ Analiza PBC zakończona!")
    print(f"   Działek przetworzonych : {n_dzialek}")
    print(f"   Działek z PBC > 0      : {len(pbc_dict)}")
    print(f"   Działek bez heksagonów : {empty_dzialki}")
    print(f"   Czas                   : {total_time/60:.1f} min")

    return pbc_dict




# Funkcja pomocnicza do pobierania warstwy
def get_layer_safe(layer_name):
    """Bezpiecznie pobiera warstwę z projektu"""
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if layers:
        return layers[0]
    else:
        print(f"OSTRZEŻENIE: Warstwa '{layer_name}' nie została znaleziona")
        return None



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










# OSZACOWANIE PBC    
analiza_pbc_per_dzialka('dzialki_zgodne_z_funkcja')
# obliczanie wskaznikow
oblicz_wskazniki_dzialek(dzialki_layer_name="dzialki_zgodne_z_funkcja", 
                         new_layer_name="dzialki_ze_wskaznikami")

# to samo dla działki przedmiotowej
try:
    analiza_pbc_per_dzialka('granica_terenu')

    # obliczanie wskaznikow
    oblicz_wskazniki_dzialek(dzialki_layer_name="granica_terenu", 
                             new_layer_name="granica_terenu_wskazniki")
except:
    print("Brak wskaźników dla działki przedmiotowej")

iface.mapCanvas().setRenderFlag(True)
