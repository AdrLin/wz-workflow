#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skrypt PyQGIS - Dodawanie pól do warstwy wektorowej
Dodaje cztery pola do aktywnej warstwy i pozostawia w trybie edycji
"""

from qgis.core import QgsField, QgsVectorLayer, QgsProject
from qgis.PyQt.QtCore import QVariant

def get_active_vector_layer():
    """Pobiera aktywną warstwę wektorową"""
    layer = iface.activeLayer()
    
    if layer is None:
        raise Exception("Brak aktywnej warstwy! Wybierz warstwę wektorową w panelu warstw.")
    
    if not isinstance(layer, QgsVectorLayer):
        raise Exception(f"Aktywna warstwa '{layer.name()}' nie jest warstwą wektorową!")
    
    print(f"Aktywna warstwa: {layer.name()}")
    print(f"Typ geometrii: {layer.geometryType()}")
    print(f"Liczba obiektów: {layer.featureCount()}")
    
    return layer

def add_fields_to_layer(layer):
    """
    Dodaje cztery pola do warstwy wektorowej:
    - WIZ (float)
    - WNIZ (float) 
    - WPZ (string)
    - WPBC (string)
    """
    print(f"\n=== DODAWANIE PÓL DO WARSTWY: {layer.name()} ===")
    
    # Definicja pól do dodania
    fields_to_add = [
        {'name': 'WIZ', 'type': QVariant.Double, 'length': 10, 'precision': 2, 'comment': 'Pole WIZ (float)'},
        {'name': 'WNIZ', 'type': QVariant.Double, 'length': 10, 'precision': 2, 'comment': 'Pole WNIZ (float)'},
        {'name': 'WPZ', 'type': QVariant.String, 'length': 255, 'precision': 0, 'comment': 'Pole WPZ (string)'},
        {'name': 'WPBC', 'type': QVariant.String, 'length': 255, 'precision': 0, 'comment': 'Pole WPBC (string)'}
    ]
    
    # Sprawdź istniejące pola
    existing_fields = [field.name() for field in layer.fields()]
    print(f"Istniejące pola: {existing_fields}")
    
    # Rozpocznij edycję
    if not layer.isEditable():
        if not layer.startEditing():
            raise Exception("Nie można rozpocząć edycji warstwy!")
        print("✓ Rozpoczęto edycję warstwy")
    else:
        print("✓ Warstwa już w trybie edycji")
    
    # Dodaj pola
    fields_added = []
    fields_skipped = []
    
    for field_def in fields_to_add:
        field_name = field_def['name']
        
        # Sprawdź czy pole już istnieje
        if field_name in existing_fields:
            print(f"⚠ Pole '{field_name}' już istnieje - pomijam")
            fields_skipped.append(field_name)
            continue
        
        # Utwórz pole
        field = QgsField(
            name=field_def['name'],
            type=field_def['type'],
            len=field_def['length'],
            prec=field_def['precision'],
            comment=field_def['comment']
        )
        
        # Dodaj pole do warstwy
        if layer.addAttribute(field):
            fields_added.append(field_name)
            print(f"✓ Dodano pole: {field_name} ({field_def['type']})")
        else:
            print(f"✗ Błąd dodawania pola: {field_name}")
    
    # Podsumowanie
    print(f"\n=== PODSUMOWANIE ===")
    print(f"Pola dodane: {fields_added}")
    print(f"Pola pominięte (już istniały): {fields_skipped}")
    print(f"Warstwa pozostaje w trybie edycji")
    
    # Odśwież tabelę atrybutów jeśli jest otwarta  
    iface.layerTreeView().refreshLayerSymbology(layer.id())
    
    return fields_added, fields_skipped

def show_layer_info(layer):
    """Wyświetla informacje o polach warstwy"""
    print(f"\n=== INFORMACJE O POLACH WARSTWY: {layer.name()} ===")
    
    fields = layer.fields()
    print(f"Liczba pól: {len(fields)}")
    
    for i, field in enumerate(fields):
        type_name = {
            QVariant.String: "String",
            QVariant.Int: "Integer", 
            QVariant.Double: "Double/Float",
            QVariant.Bool: "Boolean",
            QVariant.Date: "Date",
            QVariant.DateTime: "DateTime"
        }.get(field.type(), f"Type_{field.type()}")
        
        print(f"  {i+1:2d}. {field.name():15s} | {type_name:12s} | Długość: {field.length():3d} | Precyzja: {field.precision()}")

def main():
    """Główna funkcja skryptu"""
    try:
        print("=== ROZPOCZĘCIE DODAWANIA PÓL ===")
        
        # Pobierz aktywną warstwę wektorową
        layer = get_active_vector_layer()
        
        # Wyświetl informacje o polach przed zmianami
        show_layer_info(layer)
        
        # Dodaj pola
        fields_added, fields_skipped = add_fields_to_layer(layer)
        
        # Wyświetl informacje o polach po zmianach
        show_layer_info(layer)
        
        # Informacja o trybie edycji
        if layer.isEditable():
            print(f"\n✓ Warstwa '{layer.name()}' jest w trybie edycji")
            print("💡 Aby zapisać zmiany: layer.commitChanges()")
            print("💡 Aby anulować zmiany: layer.rollBack()")
            print("💡 Lub użyj przycisków w pasku narzędzi QGIS")
        
        return True
        
    except Exception as e:
        print(f"\n❌ BŁĄD: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def save_changes():
    """Funkcja pomocnicza do zapisania zmian w aktywnej warstwie"""
    try:
        layer = iface.activeLayer()
        if layer and layer.isEditable():
            if layer.commitChanges():
                print(f"✓ Zmiany w warstwie '{layer.name()}' zostały zapisane")
                return True
            else:
                print(f"✗ Błąd zapisywania zmian w warstwie '{layer.name()}'")
                return False
        else:
            print("Brak aktywnej warstwy w trybie edycji")
            return False
    except Exception as e:
        print(f"❌ Błąd zapisywania: {str(e)}")
        return False

def cancel_changes():
    """Funkcja pomocnicza do anulowania zmian w aktywnej warstwie"""
    try:
        layer = iface.activeLayer()
        if layer and layer.isEditable():
            if layer.rollBack():
                print(f"✓ Zmiany w warstwie '{layer.name()}' zostały anulowane")
                return True
            else:
                print(f"✗ Błąd anulowania zmian w warstwie '{layer.name()}'")
                return False
        else:
            print("Brak aktywnej warstwy w trybie edycji")
            return False
    except Exception as e:
        print(f"❌ Błąd anulowania: {str(e)}")
        return False

# Uruchomienie skryptu
if __name__ == "__main__":
    main()
else:
    # Dla uruchomienia z konsoli QGIS
    print("Skrypt załadowany.")
    print("Dostępne funkcje:")
    print("  main() - dodaje pola do aktywnej warstwy")
    print("  save_changes() - zapisuje zmiany")
    print("  cancel_changes() - anuluje zmiany")
