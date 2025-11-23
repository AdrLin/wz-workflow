import pandas as pd
import os
from qgis.core import QgsProject
from pathlib import Path
try:
    from qgis.utils import iface
    IFACE_AVAILABLE = True
except ImportError:
    print("UWAGA: iface nie jest dostępne")
    iface = None
    IFACE_AVAILABLE = False

def utworz_folder(sciezka_folderu):
    try:
        os.makedirs(sciezka_folderu, exist_ok=True)
        print(f"Folder utworzony lub już istnieje: {sciezka_folderu}")
    except Exception as e:
        print(f"Błąd podczas tworzenia folderu: {e}")
        
        
project_path = QgsProject.instance().fileName()
project_directory = os.path.dirname(project_path)                
utworz_folder(f"{Path(project_directory)}/budynki_parametry_dachy")

# Pobranie warstwy z projektu QGIS
layer = iface.activeLayer()
layer_name = layer.name()
# Konwersja do pandas DataFrame
data = []
for feature in layer.getFeatures():
    attrs = feature.attributes()
    fields = [field.name() for field in layer.fields()]
    data.append(dict(zip(fields, attrs)))

budynki = pd.DataFrame(data)

# Sprawdzenie struktury danych
print("Kolumny w warstwie wektorowej:")
print(budynki.columns.tolist())
print("\nPierwsze 5 wierszy:")
print(budynki[['Kategoria', 'nachylenie']].head())

# Utworzenie dataframe 'dachy' z analizą według kategorii
dachy = budynki.groupby('Kategoria').agg({
    'nachylenie': ['count', 'min', 'max']
}).reset_index()

# Spłaszczenie kolumn wielopoziomowych
dachy.columns = ['Kategoria', 'liczba_wystapien', 'min_nachylenie', 'max_nachylenie']
dachy[['min_nachylenie', 'max_nachylenie']] = dachy[['min_nachylenie', 'max_nachylenie']].astype(int)
dachy = dachy.sort_values('liczba_wystapien', ascending=False)
# Wyświetlenie wyników
print("\nDataframe 'dachy':")
print(dachy)

# Dodatkowe statystyki dla lepszego zrozumienia danych
print("\nDodatkowe informacje:")
print(f"Łączna liczba budynków: {len(budynki)}")
print(f"Liczba unikalnych kategorii: {budynki['Kategoria'].nunique()}")
print(f"Kategorie dachów: {budynki['Kategoria'].unique()}")

# Ścieżka do folderu projektu
project_folder = QgsProject.instance().homePath()
output_path = f"{project_folder}/budynki_parametry_dachy/{layer_name}_dachy.csv"

# Zapisanie dataframe jako CSV
dachy.to_csv(output_path, index=False, encoding='utf-8')
print(f"\nDataframe został zapisany jako '{output_path}'")

# Opcjonalne: wyświetlenie podstawowych statystyk dla nachylenia
print("\nPodstawowe statystyki nachylenia dachów:")
print(budynki['nachylenie'].describe())