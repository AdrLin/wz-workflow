from pathlib import Path
from qgis.core import QgsProject, QgsVectorFileWriter, QgsCoordinateTransformContext, QgsVectorLayer

project_path = QgsProject.instance().fileName() 
if project_path:
    project_directory = Path(project_path).parent
    print(f"Katalog projektu: {project_directory}")
else:
    print("Projekt nie został jeszcze zapisany.")
    # Możesz ustawić domyślną ścieżkę lub zakończyć działanie
    project_directory = Path.cwd()  # Użyj bieżącego katalogu jako fallback

# Nazwa i ścieżka do pliku geopackage (poprawiona składnia)
temp_layer =iface.activeLayer()
layer_name = temp_layer.name()
output_path = str(project_directory / f"{layer_name}.gpkg")

# Sprawdź czy warstwa tymczasowa istnieje
# temp_layer = QgsProject.instance().mapLayersByName(layer_name)

if temp_layer:
    # temp_layer = temp_layer[0]
    # Zapisz warstwę tymczasową do pliku geopackage
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.fileEncoding = 'UTF-8'
    options.layerName = layer_name
    
    # Poprawiona składnia zapisu
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        temp_layer, 
        output_path, 
        QgsCoordinateTransformContext(), 
        options
    )
    
    # Sprawdź wynik zapisu
    if result[0] == QgsVectorFileWriter.NoError:
        print(f"Warstwa została pomyślnie zapisana do: {output_path}")
        
        # Usuń starą warstwę tymczasową z projektu
        QgsProject.instance().removeMapLayer(temp_layer)
        
        # Wczytaj zapisaną warstwę do projektu
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