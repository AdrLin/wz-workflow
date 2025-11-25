#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
output_and_results_unified.py

Wersja 4.0 - UNIFIED
- Jeden plik Excel z wszystkimi danymi
- Spójne suffixy _x, _y, _z dla budynków
- Mapowanie funkcji istniejących na budynki planowane
- Zestawienia dachów z suffixami

Struktura pliku wynikowego (analiza_wz_kompletna.xlsx):
- Arkusz 1: output_table (tabela główna z działkami i budynkami)
- Arkusz 2: results (wyniki analizy statystycznej)
- Arkusz 3: dane_dzialki (dane z formularza)
- Arkusz 4: do_eksportu (wszystkie zmienne płasko)
- Arkusz 5: zestawienia_dachow (statystyki dachów per grupa)
"""

import os
import pandas as pd
from pathlib import Path

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, 
                            QLabel, QPushButton, QListWidget, QListWidgetItem,
                            QTreeWidget, QTreeWidgetItem, QMessageBox, 
                            QDialogButtonBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QBrush

try:
    import openpyxl
except ImportError:
    print("⚠️ Instaluję openpyxl...")
    os.system("pip install openpyxl")
    import openpyxl

from qgis.core import QgsProject


def get_project_directory():
    project_path = QgsProject.instance().fileName()
    if not project_path:
        return None
    return Path(project_path).parent


def layer_to_dataframe(layer):
    data = []
    field_names = [field.name() for field in layer.fields()]
    for feature in layer.getFeatures():
        row = {fn: feature[fn] for fn in field_names}
        data.append(row)
    return pd.DataFrame(data)


def get_unique_building_functions(layer):
    functions = {}
    if 'rodzaj_zabudowy' not in [f.name() for f in layer.fields()]:
        return functions
    for feature in layer.getFeatures():
        func = feature['rodzaj_zabudowy']
        if func and str(func).strip():
            func_str = str(func).strip()
            functions[func_str] = functions.get(func_str, 0) + 1
    return functions


def get_planned_buildings_from_file(project_directory):
    file_path = Path(project_directory) / "dane_dzialki_przedmiotowej.xlsx"
    if not file_path.exists():
        return []
    try:
        df = pd.read_excel(file_path, sheet_name='do_eksportu')
        data_dict = df.set_index('nazwa_pola')['wartosc'].to_dict()
        
        suffixes = set()
        for key in data_dict.keys():
            if key.startswith('liczba_budynkow_'):
                suffixes.add(key.replace('liczba_budynkow_', ''))
        
        planned = []
        for suffix in sorted(suffixes):
            funkcja = data_dict.get(f'funkcja_budynku_{suffix}', '')
            if pd.isna(funkcja) or not funkcja:
                funkcja = f"budynek typu {suffix.upper()}"
            liczba = int(data_dict.get(f'liczba_budynkow_{suffix}', 1))
            planned.append({'suffix': suffix, 'funkcja': str(funkcja), 'liczba': liczba})
        return planned
    except Exception as e:
        print(f"Błąd: {e}")
        return []


class FunctionMappingDialog(QDialog):
    def __init__(self, available_functions, planned_buildings, parent=None):
        super().__init__(parent)
        self.available_functions = available_functions
        self.planned_buildings = planned_buildings
        self.mapping = {pb['suffix']: [] for pb in planned_buildings}
        
        self.setWindowTitle("Mapowanie funkcji budynków")
        self.setMinimumWidth(900)
        self.setMinimumHeight(600)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        header = QLabel(
            "<b>🔗 Mapowanie funkcji budynków istniejących na planowane</b><br><br>"
            "Przypisz funkcje budynków z obszaru analizowanego do odpowiednich typów "
            "budynków planowanych przez inwestora."
        )
        header.setWordWrap(True)
        header.setStyleSheet("padding: 12px; background-color: #fff3cd; border-radius: 5px;")
        layout.addWidget(header)
        
        main_layout = QHBoxLayout()
        
        # Lewa kolumna
        left_group = QGroupBox("📋 Funkcje budynków w obszarze")
        left_layout = QVBoxLayout()
        self.functions_list = QListWidget()
        self.functions_list.setSelectionMode(QListWidget.ExtendedSelection)
        
        for func_name, count in sorted(self.available_functions.items(), key=lambda x: x[1], reverse=True):
            item = QListWidgetItem(f"{func_name} ({count} bud.)")
            item.setData(Qt.UserRole, func_name)
            self.functions_list.addItem(item)
        
        left_layout.addWidget(self.functions_list)
        left_group.setLayout(left_layout)
        main_layout.addWidget(left_group)
        
        # Środek
        center_layout = QVBoxLayout()
        center_layout.addStretch()
        add_btn = QPushButton("➡️ Przypisz")
        add_btn.clicked.connect(self.add_to_selected_building)
        center_layout.addWidget(add_btn)
        remove_btn = QPushButton("⬅️ Usuń")
        remove_btn.clicked.connect(self.remove_from_building)
        center_layout.addWidget(remove_btn)
        center_layout.addStretch()
        main_layout.addLayout(center_layout)
        
        # Prawa kolumna
        right_group = QGroupBox("🏗️ Budynki planowane")
        right_layout = QVBoxLayout()
        self.buildings_tree = QTreeWidget()
        self.buildings_tree.setHeaderLabels(["Budynek / Funkcja", "Liczba"])
        
        for planned in self.planned_buildings:
            item = QTreeWidgetItem([f"[{planned['suffix'].upper()}] {planned['funkcja']}", str(planned['liczba'])])
            item.setData(0, Qt.UserRole, planned['suffix'])
            item.setBackground(0, QBrush(QColor("#e8f5e9")))
            self.buildings_tree.addTopLevelItem(item)
            item.setExpanded(True)
        
        right_layout.addWidget(self.buildings_tree)
        right_group.setLayout(right_layout)
        main_layout.addWidget(right_group)
        
        layout.addLayout(main_layout)
        
        # Szybkie akcje
        quick_layout = QHBoxLayout()
        auto_btn = QPushButton("🤖 Auto-dopasowanie")
        auto_btn.clicked.connect(self.auto_match)
        quick_layout.addWidget(auto_btn)
        all_first_btn = QPushButton("🔗 Wszystkie do pierwszego")
        all_first_btn.clicked.connect(self.all_to_first)
        quick_layout.addWidget(all_first_btn)
        layout.addLayout(quick_layout)
        
        # Przyciski
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
    
    def add_to_selected_building(self):
        selected = self.functions_list.selectedItems()
        current = self.buildings_tree.currentItem()
        if not selected or not current:
            return
        
        if current.parent():
            building_item = current.parent()
        else:
            building_item = current
        
        suffix = building_item.data(0, Qt.UserRole)
        
        for item in selected:
            func_name = item.data(Qt.UserRole)
            for s in self.mapping:
                if func_name in self.mapping[s]:
                    self.mapping[s].remove(func_name)
            if func_name not in self.mapping[suffix]:
                self.mapping[suffix].append(func_name)
        
        self.update_trees()
    
    def remove_from_building(self):
        current = self.buildings_tree.currentItem()
        if not current or not current.parent():
            return
        func_name = current.data(0, Qt.UserRole)
        suffix = current.parent().data(0, Qt.UserRole)
        if func_name in self.mapping.get(suffix, []):
            self.mapping[suffix].remove(func_name)
        self.update_trees()
    
    def auto_match(self):
        keywords = {
            'mieszk': ['mieszk', 'jednorodzinn', 'wielorodzinn'],
            'usług': ['usług', 'handl', 'biur'],
            'gospodar': ['gospodar', 'garaż', 'niemiesz', 'magazyn']
        }
        
        for suffix in self.mapping:
            self.mapping[suffix] = []
        
        for planned in self.planned_buildings:
            suffix = planned['suffix']
            funkcja_lower = planned['funkcja'].lower()
            
            matched = []
            for kw_group, kws in keywords.items():
                if any(kw in funkcja_lower for kw in kws):
                    matched.extend(kws)
            
            for func_name in self.available_functions.keys():
                if any(kw in func_name.lower() for kw in matched):
                    if func_name not in self.mapping[suffix]:
                        self.mapping[suffix].append(func_name)
        
        self.update_trees()
    
    def all_to_first(self):
        if self.planned_buildings:
            first = self.planned_buildings[0]['suffix']
            for s in self.mapping:
                self.mapping[s] = []
            self.mapping[first] = list(self.available_functions.keys())
            self.update_trees()
    
    def update_trees(self):
        for i in range(self.buildings_tree.topLevelItemCount()):
            item = self.buildings_tree.topLevelItem(i)
            suffix = item.data(0, Qt.UserRole)
            item.takeChildren()
            for func in self.mapping.get(suffix, []):
                child = QTreeWidgetItem([func, str(self.available_functions.get(func, 0))])
                child.setData(0, Qt.UserRole, func)
                item.addChild(child)
            item.setExpanded(True)
        
        assigned = set()
        for funcs in self.mapping.values():
            assigned.update(funcs)
        
        for i in range(self.functions_list.count()):
            item = self.functions_list.item(i)
            func = item.data(Qt.UserRole)
            count = self.available_functions.get(func, 0)
            if func in assigned:
                item.setBackground(QColor("#c8e6c9"))
                item.setText(f"✓ {func} ({count} bud.)")
            else:
                item.setBackground(QColor("white"))
                item.setText(f"{func} ({count} bud.)")
    
    def validate_and_accept(self):
        empty = [pb['suffix'] for pb in self.planned_buildings if not self.mapping.get(pb['suffix'])]
        if empty:
            QMessageBox.warning(self, "Błąd", f"Budynki bez przypisań: {empty}")
            return
        self.accept()
    
    def get_mapping(self):
        return self.mapping


def create_budynki_pivot(budynki_df, suffix, functions_filter):
    if functions_filter:
        filtered = budynki_df[budynki_df['rodzaj_zabudowy'].isin(functions_filter)].copy()
    else:
        filtered = budynki_df.copy()
    
    if filtered.empty or 'ID_DZIALKI' not in filtered.columns:
        return pd.DataFrame()
    
    def safe_mean(x):
        vals = pd.to_numeric(x, errors='coerce').dropna()
        return vals.mean() if len(vals) > 0 else None
    
    def safe_join(x):
        return '; '.join([str(v) for v in x if pd.notna(v)])
    
    agg = {}
    if 'szer_elew_front' in filtered.columns:
        agg['szer_elew_front'] = safe_mean
    if 'wysokosc' in filtered.columns:
        agg['wysokosc'] = safe_mean
    if 'nachylenie' in filtered.columns:
        agg['nachylenie'] = safe_join
    if 'Kategoria' in filtered.columns:
        agg['Kategoria'] = safe_join
    
    if not agg:
        return pd.DataFrame()
    
    grouped = filtered.groupby('ID_DZIALKI').agg(agg).reset_index()
    
    new_cols = ['ID_DZIALKI'] + [f"{c}_{suffix}" for c in grouped.columns[1:]]
    grouped.columns = new_cols
    
    return grouped


def calc_mean(df, col):
    try:
        if col not in df.columns:
            return 0
        vals = pd.to_numeric(df[col], errors='coerce').dropna()
        return round(vals.mean(), 2) if len(vals) > 0 else 0
    except:
        return 0

def calc_min(df, col):
    try:
        if col not in df.columns:
            return 0
        vals = pd.to_numeric(df[col], errors='coerce').dropna()
        return round(vals.min(), 2) if len(vals) > 0 else 0
    except:
        return 0

def calc_max(df, col):
    try:
        if col not in df.columns:
            return 0
        vals = pd.to_numeric(df[col], errors='coerce').dropna()
        return round(vals.max(), 2) if len(vals) > 0 else 0
    except:
        return 0


def create_output_table(dzialki_df, budynki_df, mapping):
    output = pd.DataFrame()
    
    output['Lp.'] = range(1, len(dzialki_df) + 1)
    output['nr działki'] = dzialki_df['NUMER_DZIALKI'] if 'NUMER_DZIALKI' in dzialki_df.columns else ''
    output['nr obrębu'] = dzialki_df['NUMER_OBREBU'] if 'NUMER_OBREBU' in dzialki_df.columns else ''
    
    if 'POLE_EWIDENCYJNE' in dzialki_df.columns:
        output['powierzchnia działki [m2]'] = pd.to_numeric(dzialki_df['POLE_EWIDENCYJNE'], errors='coerce').round(2)
    else:
        output['powierzchnia działki [m2]'] = 0
    
    output['rodzaj zabudowy'] = dzialki_df['RODZAJ_ZABUDOWY'] if 'RODZAJ_ZABUDOWY' in dzialki_df.columns else ''
    
    # Powierzchnia zabudowy - sprawdź różne nazwy kolumn
    if 'S_POW_ZABUD' in dzialki_df.columns:
        output['powierzchnia zabudowy [m2]'] = pd.to_numeric(dzialki_df['S_POW_ZABUD'], errors='coerce').round(2)
    elif 'suma_pow_zab' in dzialki_df.columns:
        output['powierzchnia zabudowy [m2]'] = pd.to_numeric(dzialki_df['suma_pow_zab'], errors='coerce').round(2)
    else:
        output['powierzchnia zabudowy [m2]'] = 0
    
    # WIZ - sprawdź wielkie i małe litery
    if 'WIZ' in dzialki_df.columns:
        output['WIZ wskaźnik intensywności zabudowy'] = pd.to_numeric(dzialki_df['WIZ'], errors='coerce').round(2)
    elif 'wiz' in dzialki_df.columns:
        output['WIZ wskaźnik intensywności zabudowy'] = pd.to_numeric(dzialki_df['wiz'], errors='coerce').round(2)
    else:
        output['WIZ wskaźnik intensywności zabudowy'] = 0
    
    # WNIZ - sprawdź wielkie i małe litery
    if 'WNIZ' in dzialki_df.columns:
        output['WNIZ wskaźnik nadziemnej intensywności zabudowy'] = pd.to_numeric(dzialki_df['WNIZ'], errors='coerce').round(2)
    elif 'wniz' in dzialki_df.columns:
        output['WNIZ wskaźnik nadziemnej intensywności zabudowy'] = pd.to_numeric(dzialki_df['wniz'], errors='coerce').round(2)
    else:
        output['WNIZ wskaźnik nadziemnej intensywności zabudowy'] = 0
    
    # WPZ - jako float (z kolumny wpz_float lub obliczony)
    if 'wpz_float' in dzialki_df.columns:
        wpz = pd.to_numeric(dzialki_df['wpz_float'], errors='coerce')
    elif 'wpz' in dzialki_df.columns:
        wpz = pd.to_numeric(dzialki_df['wpz'], errors='coerce')
    else:
        wpz = pd.Series([0] * len(dzialki_df))
    
    # WPBC - jako float (z kolumny wpbc_float lub obliczony)
    if 'wpbc_float' in dzialki_df.columns:
        wpbc = pd.to_numeric(dzialki_df['wpbc_float'], errors='coerce')
    elif 'wpbc' in dzialki_df.columns:
        wpbc = pd.to_numeric(dzialki_df['wpbc'], errors='coerce')
    else:
        wpbc = pd.Series([0] * len(dzialki_df))
    
    output['WPZ wskaźnik powierzchni zabudowy'] = (wpz * 100).round(0).astype(int).astype(str) + '%'
    output['WPBC wskaźnik powierzchni biologicznie czynnej'] = (wpbc * 100).round(0).astype(int).astype(str) + '%'
    
    output['id_działki'] = dzialki_df['ID_DZIALKI'] if 'ID_DZIALKI' in dzialki_df.columns else ''
    output['wpz_float'] = wpz.round(2)
    output['wpbc_float'] = wpbc.round(2)
    
    for suffix, functions in mapping.items():
        pivot = create_budynki_pivot(budynki_df, suffix, functions)
        if not pivot.empty:
            output = pd.merge(output, pivot, left_on='id_działki', right_on='ID_DZIALKI', how='left')
            if 'ID_DZIALKI' in output.columns:
                output = output.drop('ID_DZIALKI', axis=1)
        
        rename = {
            f'szer_elew_front_{suffix}': f'szerokość elewacji frontowej [m]_{suffix}',
            f'wysokosc_{suffix}': f'wysokość zabudowy [m]_{suffix}',
            f'Kategoria_{suffix}': f'rodzaj dachu_{suffix}',
            f'nachylenie_{suffix}': f'kąt nachylenia połaci dachowych [o]_{suffix}'
        }
        output = output.rename(columns=rename)
    
    return output


def parse_identyfikator_dzialki(identyfikator):
    """
    Parsuje identyfikator działki i zwraca numery działek oraz obrębów.
    
    Format wejściowy:
    - Pojedyncza: "302104_2.0014.341/1"
      gdzie: TERYT_GMINA.OBRĘB.NUMER_DZIAŁKI
    - Wiele: "302104_2.0014.342/3;302104_2.0014.343/3"
    
    Returns:
        tuple: (numery_dzialek, numery_obrebow)
        np. ("341/1", "0014") lub ("342/3;343/3", "0014;0014")
    """
    if not identyfikator or pd.isna(identyfikator):
        return '', ''
    
    identyfikator = str(identyfikator).strip()
    
    # Podziel po średnikach (wiele działek)
    ids = identyfikator.split(';')
    
    numery_dzialek = []
    numery_obrebow = []
    
    for id_str in ids:
        id_str = id_str.strip()
        if not id_str:
            continue
        
        try:
            # Format: TERYT_GMINA.OBRĘB.NUMER_DZIAŁKI
            # np. 302104_2.0014.341/1
            
            # Podziel po podkreślniku
            parts = id_str.split('_')
            if len(parts) < 2:
                continue
            
            # Część po podkreślniku: "2.0014.341/1"
            po_podkreslniku = parts[1]
            
            # Podziel po kropce
            parts_kropka = po_podkreslniku.split('.')
            if len(parts_kropka) < 3:
                continue
            
            # parts_kropka = ['2', '0014', '341/1']
            # obręb to przedostatni element (0014)
            # działka to ostatni element (341/1)
            obreb = parts_kropka[-2]      # np. "0014"
            dzialka = parts_kropka[-1]    # np. "341/1"
            
            numery_dzialek.append(dzialka)
            numery_obrebow.append(obreb)
            
        except Exception as e:
            print(f"⚠️ Błąd parsowania identyfikatora '{id_str}': {e}")
            continue
    
    # Złącz średnikami
    numery_dzialek_str = ';'.join(numery_dzialek) if numery_dzialek else ''
    numery_obrebow_str = ';'.join(numery_obrebow) if numery_obrebow else ''
    
    return numery_dzialek_str, numery_obrebow_str


def create_results(output_table, mapping):
    results = []
    # MAKSYMALNE WIZ I WNIZ występujące w obszarze analizowanym, MOŻE SIĘ PRZYDAĆ GDYBY INNE PODMIOTY DZIAŁAŁY INACZEJ NIŻ GMINA OSTRÓW WLKP
    # results.append({'nazwa_pola': 'maks_inten_zab', 'wartosc': calc_max(output_table, 'WIZ wskaźnik intensywności zabudowy')})
    # results.append({'nazwa_pola': 'maks_nadz_inten_zab', 'wartosc': calc_max(output_table, 'WNIZ wskaźnik nadziemnej intensywności zabudowy')})
    
    # MAKSYMALNE WIZ I WNIZ DLA PLANOWANEJ INWESTYCJI liczone zdognie z rozporządzeniem
    results.append({'nazwa_pola': 'maks_inten_zab', 'wartosc': round(calc_mean(output_table, 'WIZ wskaźnik intensywności zabudowy')*1.2,2)})
    results.append({'nazwa_pola': 'maks_nadz_inten_zab', 'wartosc': round(calc_mean(output_table, 'WNIZ wskaźnik nadziemnej intensywności zabudowy')*1.2,2)})
    
    results.append({'nazwa_pola': 'min_nadz_inten_zab', 'wartosc': calc_min(output_table, 'WNIZ wskaźnik nadziemnej intensywności zabudowy')})
    results.append({'nazwa_pola': 'Sredni_wiz', 'wartosc': calc_mean(output_table, 'WIZ wskaźnik intensywności zabudowy')})
    results.append({'nazwa_pola': 'Sredni_wniz', 'wartosc': calc_mean(output_table, 'WNIZ wskaźnik nadziemnej intensywności zabudowy')})
    
    wpz_mean = calc_mean(output_table, 'wpz_float') * 100
    wpbc_mean = calc_mean(output_table, 'wpbc_float') * 100
    results.append({'nazwa_pola': 'Sredni_wpz', 'wartosc': f"{int(wpz_mean)}%"})
    results.append({'nazwa_pola': 'Sredni_wpbc', 'wartosc': f"{int(wpbc_mean)}%"})
    
    results.append({'nazwa_pola': 'wpz_min', 'wartosc': f"{int(calc_min(output_table, 'wpz_float') * 100)}%"})
    results.append({'nazwa_pola': 'wpz_max', 'wartosc': f"{int(calc_max(output_table, 'wpz_float') * 100)}%"})
    results.append({'nazwa_pola': 'wpbc_min', 'wartosc': f"{int(calc_min(output_table, 'wpbc_float') * 100)}%"})
    results.append({'nazwa_pola': 'wpbc_max', 'wartosc': f"{int(calc_max(output_table, 'wpbc_float') * 100)}%"})
    
    for suffix in mapping.keys():
        szer_col = f'szerokość elewacji frontowej [m]_{suffix}'
        wys_col = f'wysokość zabudowy [m]_{suffix}'
        
        if szer_col in output_table.columns:
            sr = calc_mean(output_table, szer_col)
            results.append({'nazwa_pola': f'SrElewFront_{suffix}', 'wartosc': f"{sr} m"})
            results.append({'nazwa_pola': f'MinszerElewFront_{suffix}', 'wartosc': f"{calc_min(output_table, szer_col)} m"})
            results.append({'nazwa_pola': f'MaxszerElewFront_{suffix}', 'wartosc': f"{calc_max(output_table, szer_col)} m"})
            results.append({'nazwa_pola': f'szerElewFront08_{suffix}', 'wartosc': f"{round(sr*0.8, 2)} m"})
            results.append({'nazwa_pola': f'szerElewFront12_{suffix}', 'wartosc': f"{round(sr*1.2, 2)} m"})
        
        if wys_col in output_table.columns:
            results.append({'nazwa_pola': f'srWysZab_{suffix}', 'wartosc': f"{calc_mean(output_table, wys_col)} m"})
            results.append({'nazwa_pola': f'wys_zab_min_{suffix}', 'wartosc': f"{calc_min(output_table, wys_col)} m"})
            results.append({'nazwa_pola': f'wys_zab_max_{suffix}', 'wartosc': f"{calc_max(output_table, wys_col)} m"})
    
    # === POBIERZ IDENTYFIKATOR DZIAŁKI PRZEDMIOTOWEJ ===
    # Wczytaj z pliku dane_dzialki_przedmiotowej.xlsx
    project_directory = get_project_directory()
    identyfikator_dzialki = ''
    
    if project_directory:
        dane_path = Path(project_directory) / "dane_dzialki_przedmiotowej.xlsx"
        if dane_path.exists():
            try:
                df = pd.read_excel(dane_path, sheet_name='do_eksportu')
                data_dict = df.set_index('nazwa_pola')['wartosc'].to_dict()
                identyfikator_dzialki = data_dict.get('identyfikator_dzialki', '')
                nazwa_gminy = data_dict.get('nazwa_gminy', '')
            except Exception as e:
                print(f"⚠️ Nie udało się wczytać identyfikatora: {e}")
    
    # Parsuj identyfikator
    numery_dzialek, numery_obrebow = parse_identyfikator_dzialki(identyfikator_dzialki)
    
    if numery_obrebow:
        results.append({'nazwa_pola': 'nr_obrebu', 'wartosc': numery_obrebow})
    
    if numery_dzialek:
        results.append({'nazwa_pola': 'nr_dzialki', 'wartosc': numery_dzialek})
    # Nazwa gminy
    if nazwa_gminy:
        results.append({'nazwa_pola': 'nazwa_gminy', 'wartosc': nazwa_gminy})
        
    # === POBIERZ NAZWĘ GMINY Z WARSTWY (jeśli nie ma w pliku) ===
    if not nazwa_gminy:
        try:
            granica_layers = QgsProject.instance().mapLayersByName('granica_terenu')
            if granica_layers and granica_layers[0].featureCount() > 0:
                layer = granica_layers[0]
                # Pobierz pierwszą cechę
                feature = next(layer.getFeatures())
                
                # Sprawdź różne możliwe nazwy pól
                field_names = [f.name() for f in layer.fields()]
                nazwa_gminy_field = None
                
                for possible_name in ['gmina', 'GMINA', 'NAZWA_GMINY', 'nazwa_gminy']:
                    if possible_name in field_names:
                        nazwa_gminy_field = possible_name
                        break
                
                if nazwa_gminy_field:
                    nazwa_gminy = feature[nazwa_gminy_field]
                    if nazwa_gminy:
                        results.append({'nazwa_pola': 'nazwa_gminy', 'wartosc': str(nazwa_gminy)})
        except Exception as e:
            print(f"⚠️ Nie udało się pobrać nazwy gminy z warstwy: {e}")    
            
    # Wymiary - dlugosc_frontu i promien_bufora z pola 'l'
    try:
        wymiary_layers = QgsProject.instance().mapLayersByName('wymiary')
        if wymiary_layers:
            l_values = []
            for f in wymiary_layers[0].getFeatures():
                l_value = f['l']
                if l_value is not None:
                    try:
                        l_values.append(float(l_value))
                    except (ValueError, TypeError):
                        continue
            
            if len(l_values) >= 2:
                l_values.sort()
                results.append({'nazwa_pola': 'dlugosc_frontu', 'wartosc': f"{round(l_values[0], 2)} m"})
                results.append({'nazwa_pola': 'promien_bufora', 'wartosc': f"{round(l_values[-1], 2)} m"})
            elif len(l_values) == 1:
                results.append({'nazwa_pola': 'dlugosc_frontu', 'wartosc': f"{round(l_values[0], 2)} m"})
                results.append({'nazwa_pola': 'promien_bufora', 'wartosc': f"{round(l_values[0], 2)} m"})
            else:
                results.append({'nazwa_pola': 'dlugosc_frontu', 'wartosc': "0 m"})
                results.append({'nazwa_pola': 'promien_bufora', 'wartosc': "0 m"})
        else:
            results.append({'nazwa_pola': 'dlugosc_frontu', 'wartosc': "0 m"})
            results.append({'nazwa_pola': 'promien_bufora', 'wartosc': "0 m"})
    except Exception as e:
        print(f"Błąd wymiary: {e}")
        results.append({'nazwa_pola': 'dlugosc_frontu', 'wartosc': "0 m"})
        results.append({'nazwa_pola': 'promien_bufora', 'wartosc': "0 m"})
    
    # Linie zabudowy - Lz_min i Lz_max z pola 'distance'
    try:
        lz_layers = QgsProject.instance().mapLayersByName('linie_zabudowy')
        if lz_layers:
            distance_values = []
            for f in lz_layers[0].getFeatures():
                distance_value = f['distance']
                if distance_value is not None:
                    try:
                        distance_values.append(float(distance_value))
                    except (ValueError, TypeError):
                        continue
            
            if len(distance_values) > 0:
                results.append({'nazwa_pola': 'Lz_min', 'wartosc': f"{round(min(distance_values), 2)} m"})
                results.append({'nazwa_pola': 'Lz_max', 'wartosc': f"{round(max(distance_values), 2)} m"})
            else:
                results.append({'nazwa_pola': 'Lz_min', 'wartosc': "0 m"})
                results.append({'nazwa_pola': 'Lz_max', 'wartosc': "0 m"})
        else:
            results.append({'nazwa_pola': 'Lz_min', 'wartosc': "0 m"})
            results.append({'nazwa_pola': 'Lz_max', 'wartosc': "0 m"})
    except Exception as e:
        print(f"Błąd linie_zabudowy: {e}")
        results.append({'nazwa_pola': 'Lz_min', 'wartosc': "0 m"})
        results.append({'nazwa_pola': 'Lz_max', 'wartosc': "0 m"})
    
    return pd.DataFrame(results)


def generate_roof_stats(budynki_df, mapping):
    stats = []
    for suffix, functions in mapping.items():
        filtered = budynki_df[budynki_df['rodzaj_zabudowy'].isin(functions)]
        roof_data = {}
        for _, row in filtered.iterrows():
            kat = str(row.get('Kategoria', 'nieznany')).strip() or 'nieznany'
            nach = int(row.get('nachylenie', 0))
            if kat not in roof_data:
                roof_data[kat] = {'count': 0, 'min': nach, 'max': nach}
            roof_data[kat]['count'] += 1
            roof_data[kat]['min'] = min(roof_data[kat]['min'], nach)
            roof_data[kat]['max'] = max(roof_data[kat]['max'], nach)
        
        for kat, d in roof_data.items():
            stats.append({
                'suffix': suffix,
                'Kategoria': kat,
                'liczba_wystapien': d['count'],
                'min_nachylenie': d['min'],
                'max_nachylenie': d['max']
            })
    return pd.DataFrame(stats)


def create_geom_dachow_text(roof_df, suffix):
    df = roof_df[roof_df['suffix'] == suffix].sort_values('liczba_wystapien', ascending=False)
    if df.empty:
        return ""
    
    total = df['liczba_wystapien'].sum()
    opisy = []
    
    for _, row in df.iterrows():
        kat = row['Kategoria']
        n = row['liczba_wystapien']
        mi = int(row['min_nachylenie'])
        ma = int(row['max_nachylenie'])
        
        pct = (n / total) * 100
        if pct > 50:
            pre = "występują przeważnie dachy typu"
        elif pct < 10:
            pre = "sporadycznie występują dachy typu"
        else:
            pre = "występują dachy typu"
        
        if mi == ma:
            opisy.append(f"{pre} {kat} o kącie nachylenia połaci dachowych ok. {mi} stopni")
        else:
            opisy.append(f"{pre} {kat} o kącie nachylenia połaci dachowych od {mi} do {ma} stopni")
    
    return ", ".join(opisy) + ","


def process_layers_unified():
    print("\n" + "="*70)
    print("OUTPUT AND RESULTS - UNIFIED v4.0")
    print("="*70)
    
    project_directory = get_project_directory()
    if not project_directory:
        print("❌ Projekt nie zapisany!")
        return False
    
    # Warstwy
    dzialki_layer = budynki_layer = None
    for layer in QgsProject.instance().mapLayers().values():
        if layer.name() == 'dzialki_ze_wskaznikami':
            dzialki_layer = layer
        elif layer.name() == 'budynki_parametry':
            budynki_layer = layer
    
    if not dzialki_layer or not budynki_layer:
        print("❌ Brak wymaganych warstw!")
        return False
    
    print(f"✅ Działki: {dzialki_layer.featureCount()}, Budynki: {budynki_layer.featureCount()}")
    
    dzialki_df = layer_to_dataframe(dzialki_layer)
    budynki_df = layer_to_dataframe(budynki_layer)
    budynki_df['nachylenie'] = pd.to_numeric(budynki_df['nachylenie'], errors='coerce').fillna(0).astype(int)
    
    planned = get_planned_buildings_from_file(project_directory)
    if not planned:
        planned = [{'suffix': 'x', 'funkcja': 'budynek', 'liczba': 1}]
    
    print(f"📋 Planowane: {[p['suffix'] for p in planned]}")
    
    available_functions = get_unique_building_functions(budynki_layer)
    print(f"🏠 Funkcje: {list(available_functions.keys())}")
    
    # Dialog mapowania
    dialog = FunctionMappingDialog(available_functions, planned)
    if dialog.exec_() != QDialog.Accepted:
        print("⚠️ Anulowano")
        return False
    
    mapping = dialog.get_mapping()
    print(f"🔗 Mapowanie: {mapping}")
    
    # Tworzenie tabel
    output_table = create_output_table(dzialki_df, budynki_df, mapping)
    results_df = create_results(output_table, mapping)
    roof_stats_df = generate_roof_stats(budynki_df, mapping)
    
    # Dodaj geometriaDachow
    for suffix in mapping.keys():
        geom_text = create_geom_dachow_text(roof_stats_df, suffix)
        results_df = pd.concat([results_df, pd.DataFrame([{
            'nazwa_pola': f'geometriaDachow_{suffix}',
            'wartosc': geom_text
        }])], ignore_index=True)
    
    # Wczytaj dane działki
    dane_path = Path(project_directory) / "dane_dzialki_przedmiotowej.xlsx"
    if dane_path.exists():
        dane_df = pd.read_excel(dane_path, sheet_name='do_eksportu')
    else:
        dane_df = pd.DataFrame(columns=['nazwa_pola', 'wartosc'])
    
    # Połącz do_eksportu
    eksport_df = pd.concat([dane_df, results_df], ignore_index=True)
    eksport_df = eksport_df.drop_duplicates(subset='nazwa_pola', keep='last')
    
    # Zapisz
    output_path = os.path.join(project_directory, "analiza_wz_kompletna.xlsx")
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        output_table.to_excel(writer, sheet_name='output_table', index=False)
        results_df.to_excel(writer, sheet_name='results', index=False)
        dane_df.to_excel(writer, sheet_name='dane_dzialki', index=False)
        eksport_df.to_excel(writer, sheet_name='do_eksportu', index=False)
        roof_stats_df.to_excel(writer, sheet_name='zestawienia_dachow', index=False)
    
    print(f"\n✅ Zapisano: {output_path}")
    QMessageBox.information(None, "Sukces", f"Utworzono plik:\n{output_path}")
    
    return True


try:
    process_layers_unified()
except Exception as e:
    print(f"❌ Błąd: {e}")
    import traceback
    traceback.print_exc()