import string
import os
from qgis.core import (
    QgsProject,
    QgsField,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsWkbTypes,
    QgsMapLayer, QgsFields, QgsFeature
)
from qgis.PyQt.QtCore import QVariant
import processing

def process_polygon_vertices(input_layer, qml_file_path=None):
    """
    Przetwarza wierzchołki warstwy poligonowej:
    1. Wydobywa wierzchołki
    2. Usuwa wierzchołki z distance = 0
    3. Dodaje etykiety alfabetyczne od południa
    4. Zapisuje lub pozostawia w edycji w zależności od liczby wierzchołków
    """
    
    if not input_layer or input_layer.type() != QgsMapLayer.VectorLayer:
        print("Błąd: Wybierz prawidłową warstwę wektorową")
        return None
    
    if input_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
        print("Błąd: Warstwa musi zawierać poligony")
        return None
    
    print(f"Przetwarzanie warstwy: {input_layer.name()}")
    
        # Sprawdź czy projekt jest zapisany
    if not QgsProject.instance().fileName():
        print("Błąd: Projekt musi być zapisany przed uruchomieniem skryptu!")
        print("Zapisz projekt (Ctrl+S) i spróbuj ponownie.")
        return None
    
    project_folder = os.path.dirname(QgsProject.instance().fileName())
    project_crs = QgsProject.instance().crs()
    print(f"Folder projektu: {project_folder}")
    print(f"CRS projektu: {project_crs.authid()}")
    
        # Krok 1: Wydobądź wierzchołki do tymczasowej warstwy
    print("Krok 1: Wydobywanie wierzchołków...")
    vertices_result = processing.run("native:extractvertices", {
        'INPUT': input_layer,
        'OUTPUT': 'TEMPORARY_OUTPUT'
    })
    
    vertices_temp = vertices_result['OUTPUT']
    if isinstance(vertices_temp, str):
        temp_layer = QgsVectorLayer(vertices_temp, "temp", "ogr")
    else:
        temp_layer = vertices_temp
    
    # Krok 2: Filtruj wierzchołki z distance = 0
    fields = temp_layer.fields()
    field_names = [field.name() for field in fields]
    has_distance = 'distance' in field_names
    
    features_to_keep = []
    for feature in temp_layer.getFeatures():
        if has_distance:
            distance_value = feature.attribute('distance')
            if distance_value != 0 and distance_value != 0.0 and distance_value is not None:
                features_to_keep.append(feature)
        else:
            features_to_keep.append(feature)
    
    print(f"Po filtrowaniu pozostało {len(features_to_keep)} wierzchołków")
    
    # Krok 3: Sortuj wierzchołki według Y (od południa)
        # Krok 3: Sortuj wierzchołki według kolejności w poligonie (counter-clockwise od południa)
    print("Sortowanie wierzchołków według kolejności w poligonie...")
    
    # Pobierz pierwszy poligon z warstwy wejściowej
    first_feature = next(input_layer.getFeatures())
    polygon_geom = first_feature.geometry()
    
    if polygon_geom.isMultipart():
        ring = polygon_geom.asMultiPolygon()[0][0]
    else:
        ring = polygon_geom.asPolygon()[0]
    
    # Usuń ostatni punkt (który jest duplikatem pierwszego)
    if len(ring) > 0 and ring[0] == ring[-1]:
        ring = ring[:-1]
    
    # Znajdź punkt najbardziej wysunięty na południe (najmniejsza Y)
    south_point_idx = 0
    min_y = ring[0].y()
    for i, point in enumerate(ring):
        if point.y() < min_y:
            min_y = point.y()
            south_point_idx = i
    
    # Przearanżuj ring żeby zaczynał od punktu południowego
    ordered_ring = ring[south_point_idx:] + ring[:south_point_idx]
    
    print(f"Punkt startowy (południe): {ordered_ring[0]}")
    
    # Dopasuj features do uporządkowanych punktów geometrii
    ordered_features = []
    tolerance = 0.0001  # Tolerancja dla porównania współrzędnych
    
    for ring_point in ordered_ring:
        for feature in features_to_keep:
            feature_point = feature.geometry().asPoint()
            if (abs(feature_point.x() - ring_point.x()) < tolerance and 
                abs(feature_point.y() - ring_point.y()) < tolerance):
                ordered_features.append(feature)
                break
    
    features_to_keep = ordered_features
    print(f"Uporządkowano {len(features_to_keep)} wierzchołków counter-clockwise od południa")
        
    # Krok 4: Utwórz nową warstwę GPKG w folderze projektu
    output_path = os.path.join(project_folder, "wierzcholki.gpkg")
    
    # Przygotuj pola dla nowej warstwy
    new_fields = QgsFields()
    for field in temp_layer.fields():
        # Pomiń pole fid - będzie automatycznie utworzone
        if field.name().lower() != 'fid':
            new_fields.append(field)
    
    # Dodaj pole etykieta jeśli nie istnieje
    if 'etykieta' not in field_names:
        new_fields.append(QgsField("etykieta", QVariant.String, len=10))
    
    # Utwórz nową warstwę
    vertices_layer = QgsVectorLayer(f"Point?crs={project_crs.authid()}", "wierzcholki_temp", "memory")
    vertices_provider = vertices_layer.dataProvider()
    vertices_provider.addAttributes(new_fields.toList())
    vertices_layer.updateFields()
    
    
    # Krok 5: Dodaj przefiltrowane features z etykietami i vertex_index
    alphabet = string.ascii_uppercase
    new_features = []
    
    for i, feature in enumerate(features_to_keep):
        new_feature = QgsFeature(vertices_layer.fields())
        
        # Skopiuj geometrię
        new_feature.setGeometry(feature.geometry())
        
        # Skopiuj wszystkie atrybuty z oryginalnego feature (oprócz fid)
        for field in temp_layer.fields():
            field_name = field.name()
            if field_name.lower() != 'fid':  # Pomiń fid
                if new_feature.fields().indexOf(field_name) != -1:
                    new_feature.setAttribute(field_name, feature.attribute(field_name))
       
        # Ustaw vertex_index
        vertex_index_idx = new_feature.fields().indexOf('vertex_index')
        if vertex_index_idx != -1:
            new_feature.setAttribute('vertex_index', i + 1)
        
        # Ustaw etykietę
        if i < len(alphabet):
            etykieta = alphabet[i]
        else:
            first_index = (i // 26) - 1
            second_index = i % 26
            if first_index >= 0:
                etykieta = alphabet[first_index] + alphabet[second_index]
            else:
                etykieta = alphabet[second_index]
        
        etykieta_idx = new_feature.fields().indexOf('etykieta')
        if etykieta_idx != -1:
            new_feature.setAttribute('etykieta', etykieta)
        
        new_features.append(new_feature)
    
    # Dodaj features do warstwy
    vertices_provider.addFeatures(new_features)
    
    # Krok 6: Zapisz do pliku GPKG
    print(f"Zapisywanie do: {output_path}")
    transform_context = QgsProject.instance().transformContext()
    save_options = QgsVectorFileWriter.SaveVectorOptions()
    save_options.driverName = "GPKG"
    save_options.fileEncoding = "UTF-8"
    
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        vertices_layer,
        output_path,
        transform_context,
        save_options
    )
    
    if error[0] != QgsVectorFileWriter.NoError:
        print(f"Błąd zapisu: {error}")
        return None
    
    # Krok 7: Wczytaj zapisaną warstwę do projektu
    final_layer = QgsVectorLayer(output_path, "Wierzchołki", "ogr")
    if not final_layer.isValid():
        print("Błąd: Nie udało się wczytać zapisanej warstwy")
        return None
    
    # Ustaw CRS projektu
    final_layer.setCrs(project_crs)
    
    # Krok 8: Dodaj do projektu
    QgsProject.instance().addMapLayer(final_layer)
    
    # Krok 9: Zastosuj stylizację QML
    if qml_file_path and os.path.exists(qml_file_path):
        success, error_msg = final_layer.loadNamedStyle(qml_file_path)
        if success:
            print(f"Zastosowano styl z pliku: {qml_file_path}")
        else:
            print(f"Nie udało się zastosować stylu: {error_msg}")
    
    # Krok 10: Sprawdź liczbę wierzchołków vs boki poligonu
    original_features = list(input_layer.getFeatures())
    polygon_vertices_count = 0
    
    if len(original_features) > 0:
        first_polygon = original_features[0].geometry()
        if first_polygon.isMultipart():
            if first_polygon.asMultiPolygon():
                polygon_vertices_count = len(first_polygon.asMultiPolygon()[0][0]) - 1
        else:
            if first_polygon.asPolygon():
                polygon_vertices_count = len(first_polygon.asPolygon()[0]) - 1
        
        print(f"Liczba boków poligonu: {polygon_vertices_count}")
        print(f"Liczba wierzchołków: {len(features_to_keep)}")
    
    # Krok 11: Włącz tryb edycji
    final_layer.startEditing()
    print("Warstwa w trybie edycji")
    
    # Odśwież widok
    final_layer.triggerRepaint()
    iface.mapCanvas().refresh()
    
    print("Przetwarzanie zakończone pomyślnie!")
    print(f"Warstwa zapisana jako: {output_path}")
    return final_layer
    
    # Funkcja do uruchomienia dla aktywnej warstwy
def run_for_active_layer(qml_file_path=None):
    """
    Uruchom przetwarzanie dla aktywnej warstwy
    
    Args:
        qml_file_path (str): Ścieżka do pliku QML ze stylizacją (opcjonalne)
    """
    layer = QgsProject.instance().mapLayersByName('granica_terenu')[0]
    return process_polygon_vertices(layer, qml_file_path)

# Uruchom dla aktywnej warstwy

    # run_for_active_layer("/ścieżka/do/pliku/style.qml")  # Ze stylizacją
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))
style_name = "style/wierzcholki2.qml"
style_path = os.path.join(SCRIPTS_PATH, style_name)
result_layer = run_for_active_layer(style_path)  # Bez stylizacji


