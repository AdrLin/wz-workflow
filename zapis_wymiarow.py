from pathlib import Path
from qgis.core import QgsProject, QgsVectorFileWriter, QgsCoordinateTransformContext, QgsVectorLayer
import os
from qgis.utils import iface
from PyQt5.QtWidgets import QMessageBox, QFileDialog
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

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


project_path = QgsProject.instance().fileName() 
if project_path:
    project_directory = Path(project_path).parent
    print(f"Katalog projektu: {project_directory}")
else:
    print("Projekt nie został jeszcze zapisany.")
    # Możesz ustawić domyślną ścieżkę lub zakończyć działanie
    project_directory = Path.cwd()  # Użyj bieżącego katalogu jako fallback

# Nazwa i ścieżka do pliku geopackage (poprawiona składnia)
temp_layer =QgsProject.instance().mapLayersByName("wymiary")[0]
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


style_name = "style/wymiary - grubsza strzalka.qml"
style_path = os.path.join(SCRIPTS_PATH, style_name)
apply_qml_style_to_layer("wymiary",style_path)

    
    
