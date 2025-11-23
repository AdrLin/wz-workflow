#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Jul 20 07:54:35 2025

@author: adrian
"""

# Skrypt do utworzenia dwóch warstw wektorowych w QGIS
# Geometria: liniowa, nazwy: "olz" i "wymiarowanie"
# Zapisane jako GPKG w folderze projektu, wczytane i w trybie edycji

import os
from qgis.core import QgsVectorLayer, QgsProject, QgsVectorFileWriter, QgsField, QgsDefaultValue
from qgis.PyQt.QtCore import QVariant
from qgis.utils import iface
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

def create_line_layers_gpkg():
    """
    Tworzy dwie warstwy wektorowe z geometrią liniową,
    zapisuje je jako GPKG w folderze projektu,
    wczytuje do projektu i pozostawia w trybie edycji
    """
    style_name1 = "style/obowiazujaca  linia zabudowy.qml"
    style_name2="style/wymiary.qml"
    style_path1 = os.path.join(SCRIPTS_PATH, style_name1)
    style_path2 = os.path.join(SCRIPTS_PATH, style_name2)

    # Lista nazw warstw do utworzenia z opcjonalnymi ścieżkami do stylów QML
    layer_configs = {
        "olz": {
            "style_path": style_path1  # np. r"C:\sciezka\do\styl_olz.qml"
        },
        "wymiarowanie": {
            "style_path": style_path2  # np. r"C:\sciezka\do\styl_wymiarowanie.qml"
        }
    }
    
    # Pobranie ścieżki projektu
    project_path = QgsProject.instance().homePath()
    if not project_path:
        print("Projekt nie jest zapisany. Proszę najpierw zapisać projekt.")
        return
    
    # Pobranie CRS projektu
    project_crs = QgsProject.instance().crs()
    
    for name, config in layer_configs.items():
        # Ścieżka do pliku GPKG
        gpkg_path = os.path.join(project_path, f"{name}.gpkg")
        
        # Utworzenie tymczasowej warstwy do zapisu
        temp_layer = QgsVectorLayer(f"LineString?crs={project_crs.authid()}", name, "memory")
        
        # Dodanie atrybutu 'l' dla warstwy wymiarowanie
        if name == "wymiarowanie" and temp_layer.isValid():
            # Rozpoczęcie edycji na tymczasowej warstwie
            temp_layer.startEditing()
            
            # Dodanie pola 'l' (długość)
            field_l = QgsField("l", QVariant.Double, "double", 10, 2)
            temp_layer.dataProvider().addAttributes([field_l])
            temp_layer.updateFields()
            
            # Zakończenie edycji tymczasowej warstwy
            temp_layer.commitChanges()
        
        if temp_layer.isValid():
            # Zapisanie warstwy jako GPKG
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = name
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                temp_layer,
                gpkg_path,
                QgsProject.instance().transformContext(),
                options
            )
            
            if error[0] == QgsVectorFileWriter.NoError:
                # Wczytanie warstwy z pliku GPKG
                layer = QgsVectorLayer(gpkg_path, name, "ogr")
                
                if layer.isValid():
                    # Dodanie warstwy do projektu
                    QgsProject.instance().addMapLayer(layer)
                    
                    # Załadowanie stylu QML jeśli ścieżka została podana
                    style_path = config.get("style_path")
                    if style_path and os.path.exists(style_path):
                        layer.loadNamedStyle(style_path)
                        print(f"Załadowano styl z: {style_path}")
                    elif style_path:
                        print(f"Ostrzeżenie: Plik stylu nie istnieje: {style_path}")
                    
                    # Ustawienie domyślnej wartości dla pola 'l' w warstwie wymiarowanie
                    if name == "wymiarowanie":
                        # Znajdź indeks pola 'l'
                        field_index = layer.fields().indexFromName('l')
                        if field_index != -1:
                            # Ustawienie domyślnej wartości jako wyrażenie obliczające długość
                            layer.setDefaultValueDefinition(field_index, 
                                QgsDefaultValue("$length", True))
                            print(f"Ustawiono automatyczne obliczanie długości dla pola 'l'")
                    
                    # Włączenie trybu edycji
                    layer.startEditing()
                    
                    print(f"Warstwa '{name}' została utworzona jako {gpkg_path} i jest w trybie edycji")
                else:
                    print(f"Błąd podczas wczytywania warstwy '{name}' z pliku {gpkg_path}")
            else:
                print(f"Błąd podczas zapisywania warstwy '{name}': {error[1]}")
        else:
            print(f"Błąd podczas tworzenia tymczasowej warstwy '{name}'")
    
    # Odświeżenie interfejsu
    if iface:
        iface.mapCanvas().refresh()

# Uruchomienie funkcji
create_line_layers_gpkg()