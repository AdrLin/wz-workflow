#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Ciezkie biblioteki — czytelny komunikat zamiast surowego bledu importu.
try:
    import pandas as pd
except ImportError as _exc:
    raise ImportError(
        "Ten krok wymaga bibliotek naukowych (numpy/pandas/scipy). "
        "Zainstaluj je w srodowisku Pythona QGIS:  "
        "python3 -m pip install numpy pandas scipy scikit-learn joblib\n"
        f"Szczegoly: {_exc}"
    ) from _exc

"""
generator_analiz_opisowych_v4.py

Wersja 4.0 - UNIFIED
- Wczytuje JEDEN plik Excel (analiza_wz_kompletna.xlsx)
- Spójne suffixy _x, _y, _z dla wszystkich parametrów budynków
- Automatyczne mapowanie danych z arkusza do_eksportu na strukturę szablonu Word
- Obsługa wielu budynków o różnych funkcjach
"""

from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
from datetime import datetime
import os
import re
import traceback
from qgis.core import QgsProject

SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

project_path = QgsProject.instance().fileName()
project_directory = os.path.dirname(project_path) if project_path else os.getcwd()

try:
    from docxtpl import DocxTemplate
except ImportError as exc:
    # NIE instalujemy pakietow automatycznie przez powloke (os.system) —
    # to niebezpieczne i nieprzewidywalne. Uzytkownik instaluje zaleznosc sam.
    raise ImportError(
        "Brak biblioteki 'docxtpl', wymaganej do generowania raportow Word.\n"
        "Zainstaluj ja w srodowisku Pythona QGIS, np.:\n"
        "    python3 -m pip install docxtpl"
    ) from exc


def _plan_ogolny():
    """
    Leniwy import modulu plan_ogolny.py.
    Skrypt jest uruchamiany przez runpy (nie jako modul pakietu), wiec
    import wzgledny nie zadziala — ladujemy plik po sciezce.
    """
    try:
        from . import plan_ogolny as _pog  # gdyby kiedys byl importowany jako modul
        return _pog
    except Exception:  # nosec B110
        pass
    import importlib.util
    sciezka = os.path.join(SCRIPTS_PATH, "plan_ogolny.py")
    if not os.path.exists(sciezka):
        raise ImportError(f"Brak pliku {sciezka} — wymagany do obslugi planu ogolnego.")
    spec = importlib.util.spec_from_file_location("wz_plan_ogolny", sciezka)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def szablon_uzywa_planu_ogolnego(template_path):
    """
    Czy wybrany szablon zawiera placeholdery planu ogolnego?

    Pozwala uzywac starych szablonow (wnioski zlozone przed uchwaleniem planu
    ogolnego, rozpatrywane na dotychczasowych zasadach) bez zbednych ostrzezen
    o braku danych z planu.
    """
    import zipfile
    znaczniki = ("pog_strefa", "pog_ocena", "zakres_wystepujaca",
                 "podstawa_ustalen_zdanie")
    try:
        with zipfile.ZipFile(template_path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return False
    return any(z in xml for z in znaczniki)


def is_temporary_excel(fname):
    """Sprawdza czy plik jest tymczasowy."""
    bn = os.path.basename(fname)
    return bn.startswith('~$') or bn.endswith('.tmp')


def auto_find_unified_file(search_dir):
    """
    Automatycznie znajduje plik analiza_wz_kompletna.xlsx w katalogu projektu.
    """
    # Priorytet: analiza_wz_kompletna.xlsx
    priority_names = [
        'analiza_wz_kompletna.xlsx',
        'analiza_wz.xlsx',
        'wz_kompletna.xlsx'
    ]
    
    for name in priority_names:
        path = os.path.join(search_dir, name)
        if os.path.exists(path) and not is_temporary_excel(path):
            # Sprawdź czy ma arkusz do_eksportu
            try:
                xls = pd.ExcelFile(path)
                if 'do_eksportu' in xls.sheet_names:
                    return path
            except Exception:
                # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
                pass  # nosec B110
    
    # Fallback: szukaj pliku z arkuszem do_eksportu
    try:
        for f in os.listdir(search_dir):
            if f.lower().endswith('.xlsx') and not is_temporary_excel(f):
                path = os.path.join(search_dir, f)
                try:
                    xls = pd.ExcelFile(path)
                    if 'do_eksportu' in xls.sheet_names:
                        return path
                except Exception:
                    # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
                    pass  # nosec B110
    except Exception:
        # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
        pass  # nosec B110
    
    return None


def extract_building_suffixes(data_dict):
    """
    Wyodrębnia wszystkie unikalne suffiksy budynków z kluczy typu liczba_budynkow_x.
    """
    suffixes = set()
    suffix_pattern = re.compile(r'^liczba_budynkow_([a-z])$')
    
    for key in data_dict.keys():
        match = suffix_pattern.match(key)
        if match:
            suffixes.add(match.group(1))
    
    return sorted(suffixes)


def safe_float(value, default=0.0):
    """Bezpieczna konwersja na float."""
    try:
        if pd.isna(value):
            return default
        # Obsługa wartości typu "12.5 m" lub "45%"
        if isinstance(value, str):
            value = value.replace(' m', '').replace('%', '').strip()
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_round(value, decimals=2):
    """Bezpieczne zaokrąglanie."""
    try:
        return round(float(value), decimals)
    except (ValueError, TypeError):
        return value


def safe_str(value):
    """Bezpieczna konwersja na string."""
    if pd.isna(value):
        return ''
    return str(value)


def group_building_data(data_dict, suffixes):
    """
    Grupuje dane budynków według suffixów _x, _y, _z.
    Zawiera zarówno dane planowane jak i dane z analizy obszaru.
    
    KLUCZOWA ZMIANA: Wszystkie parametry używają tego samego suffixu!
    - SrElewFront_x (nie SrElewFront_0)
    - geometriaDachow_x (nie geometriaDachow_0)
    - wys_zab_min_x (nie wys_zab_min_0)
    """
    buildings = []
    
    for idx, suffix in enumerate(suffixes, start=1):
        building = {
            'numer': idx,
            'suffix': suffix,
            'suffix_upper': suffix.upper(),
            'indeks': idx - 1,
            
            # === NAZWA FUNKCJI BUDYNKU ===
            'funkcja': safe_str(data_dict.get(f'funkcja_budynku_{suffix}', f'budynku typu {suffix.upper()}')),
            'funkcja_przymiotnik': safe_str(data_dict.get(f'funkcja_przymiotnik_{suffix}', f'typu {suffix.upper()}')),
            'funkcja_dopelniacz': safe_str(data_dict.get(f'funkcja_dopelniacz_{suffix}', f'typu {suffix.upper()}')),
            
            # === PLANOWANE PARAMETRY ===
            'liczba_budynkow': int(safe_float(data_dict.get(f'liczba_budynkow_{suffix}', 1))),
            'powierzchnia_zabudowy_min': safe_round(data_dict.get(f'powierzchnia_zabudowy_min_{suffix}', 0)),
            'powierzchnia_zabudowy_max': safe_round(data_dict.get(f'powierzchnia_zabudowy_max_{suffix}', 0)),
            'powierzchnia_kond_podziemnych_min': safe_round(data_dict.get(f'powierzchnia_kond_podziemnych_min_{suffix}', 0)),
            'powierzchnia_kond_podziemnych_max': safe_round(data_dict.get(f'powierzchnia_kond_podziemnych_max_{suffix}', 0)),
            'powierzchnia_kond_nadziemnych_min': safe_round(data_dict.get(f'powierzchnia_kond_nadziemnych_min_{suffix}', 0)),
            'powierzchnia_kond_nadziemnych_max': safe_round(data_dict.get(f'powierzchnia_kond_nadziemnych_max_{suffix}', 0)),
            'WszerFrontmin': safe_round(data_dict.get(f'WszerFrontmin_{suffix}', 0)),
            'WszerFrontmax': safe_round(data_dict.get(f'WszerFrontmax_{suffix}', 0)),
            'w_wys_min': safe_round(data_dict.get(f'w_wys_min_{suffix}', 0)),
            'w_wys_max': safe_round(data_dict.get(f'w_wys_max_{suffix}', 0)),
            'dachProj': safe_str(data_dict.get(f'dachProj_{suffix}', data_dict.get(f'dachProj{suffix.upper()}', ''))),
            'kalenicaProj': safe_str(data_dict.get(f'kalenica_{suffix}_proj', data_dict.get(f'kalenica{suffix.upper()}proj', ''))),
            'nachylenieProjMin': int(data_dict.get(f'nachylenieProjMin_{suffix}')),
            'nachylenieProjMax': int(data_dict.get(f'nachylenieProjMax_{suffix}')),
            'liczba_kond_podziemnych_min': int(safe_float(data_dict.get(f'liczba_kond_podziemnych_min_{suffix}', 0))),
            'liczba_kond_podziemnych_max': int(safe_float(data_dict.get(f'liczba_kond_podziemnych_max_{suffix}', 0))),
            'liczba_kond_nadziemnych_min': int(safe_float(data_dict.get(f'liczba_kond_nadziemnych_min_{suffix}', 0))),
            'liczba_kond_nadziemnych_max': int(safe_float(data_dict.get(f'liczba_kond_nadziemnych_max_{suffix}', 0))),
            
            # === DANE Z ANALIZY OBSZARU - SZEROKOŚĆ ELEWACJI FRONTOWEJ ===
            # Teraz używamy suffixu _x, _y, _z (NIE _0, _1, _2!)
            'szer_elew_front_min': safe_str(data_dict.get(f'MinszerElewFront_{suffix}', '')),
            'szer_elew_front_max': safe_str(data_dict.get(f'MaxszerElewFront_{suffix}', '')),
            'SrElewFront': safe_str(data_dict.get(f'SrElewFront_{suffix}', '')),
            'szer_elew_front_08': safe_str(data_dict.get(f'szerElewFront08_{suffix}', '')),
            'szer_elew_front_12': safe_str(data_dict.get(f'szerElewFront12_{suffix}', '')),
            
            # === DANE Z ANALIZY OBSZARU - WYSOKOŚĆ ===
            'wys_zab_min': safe_str(data_dict.get(f'wys_zab_min_{suffix}', '')),
            'wys_zab_max': safe_str(data_dict.get(f'wys_zab_max_{suffix}', '')),
            'srWysZab': safe_str(data_dict.get(f'srWysZab_{suffix}', '')),
            # Maksymalna wysokość USTALONA dla nowej zabudowy — średnia z działek
            # sąsiednich policzona narzędziem w oknie danych działki, a gdy jej
            # nie policzono, średnia z całego obszaru (fallback już w xlsx).
            'wys_ustalona': safe_str(data_dict.get(
                f'wys_ustalona_{suffix}', data_dict.get(f'srWysZab_{suffix}', ''))),
            'wys_ustalona_zrodlo': safe_str(data_dict.get(
                f'wys_ustalona_zrodlo_{suffix}', '')),
            
            # === GEOMETRIA DACHÓW Z ANALIZY OBSZARU ===
            # KLUCZOWA ZMIANA: używamy suffixu _x, _y, _z (NIE _0, _1, _2!)
            'geometriaDachow': safe_str(data_dict.get(f'geometriaDachow_{suffix}', '')),
        }
        
        # Oblicz przedziały 0.8 i 1.2 * średnia dla szerokości elewacji jeśli nie ma ich w danych
        if not building['szer_elew_front_08'] or not building['szer_elew_front_12']:
            sr_elew_str = building['SrElewFront']
            sr_elew = safe_float(sr_elew_str, 0)
            if sr_elew > 0:
                building['szer_elew_front_08'] = f"{safe_round(sr_elew * 0.8)} m"
                building['szer_elew_front_12'] = f"{safe_round(sr_elew * 1.2)} m"
        
        buildings.append(building)
    
    return buildings


def calculate_totals(buildings):
    """Oblicza sumaryczne wartości dla wszystkich budynków."""
    totals = {
        'liczba_typow_budynkow': len(buildings),
        'suma_liczba_budynkow': 0,
        'suma_pow_zabudowy_min': 0,
        'suma_pow_zabudowy_max': 0,
        'suma_pow_kond_podz_min': 0,
        'suma_pow_kond_podz_max': 0,
        'suma_pow_kond_nadz_min': 0,
        'suma_pow_kond_nadz_max': 0,
    }
    
    for b in buildings:
        liczba = int(b.get('liczba_budynkow', 1))
        totals['suma_liczba_budynkow'] += liczba
        totals['suma_pow_zabudowy_min'] += safe_float(b.get('powierzchnia_zabudowy_min', 0)) * liczba
        totals['suma_pow_zabudowy_max'] += safe_float(b.get('powierzchnia_zabudowy_max', 0)) * liczba
        totals['suma_pow_kond_podz_min'] += safe_float(b.get('powierzchnia_kond_podziemnych_min', 0)) * liczba
        totals['suma_pow_kond_podz_max'] += safe_float(b.get('powierzchnia_kond_podziemnych_max', 0)) * liczba
        totals['suma_pow_kond_nadz_min'] += safe_float(b.get('powierzchnia_kond_nadziemnych_min', 0)) * liczba
        totals['suma_pow_kond_nadz_max'] += safe_float(b.get('powierzchnia_kond_nadziemnych_max', 0)) * liczba
    
    # Zaokrąglij wartości
    for key in totals:
        if isinstance(totals[key], float):
            totals[key] = round(totals[key], 2)
    
    return totals


def generate_document():
    """
    Główna funkcja generująca dokument Word z analizą WZ.
    
    NOWA LOGIKA:
    1. Wczytuje JEDEN plik Excel (analiza_wz_kompletna.xlsx)
    2. Parsuje arkusz do_eksportu
    3. Grupuje dane budynków według suffixów _x, _y, _z
    4. Renderuje szablon Word z użyciem Jinja2
    """
    template_dir = os.path.join(SCRIPTS_PATH, "analizaWZ_szablony")
    
    try:
        # ============================================
        # 1) WYBIERZ SZABLON
        # ============================================
        template_path, _ = QFileDialog.getOpenFileName(
            None,
            "Wybierz szablon dokumentu Word",
            template_dir,
            "Dokumenty Word (*.docx)"
        )
        if not template_path:
            QMessageBox.information(None, "Anulowano", "Nie wybrano szablonu. Operacja przerwana.")
            return

        # ============================================
        # 2) ZNAJDŹ PLIK Z DANYMI
        # ============================================
        data_path = auto_find_unified_file(project_directory)
        
        if not data_path:
            # Poproś użytkownika o wybór pliku
            data_path, _ = QFileDialog.getOpenFileName(
                None,
                "Wybierz plik z danymi analizy (analiza_wz_kompletna.xlsx)",
                project_directory,
                "Pliki Excel (*.xlsx)"
            )
            if not data_path:
                QMessageBox.information(None, "Anulowano", "Nie wybrano pliku z danymi. Operacja przerwana.")
                return
        
        print(f"📂 Plik z danymi: {data_path}")

        # ============================================
        # 3) WCZYTAJ DANE Z ARKUSZA do_eksportu
        # ============================================
        try:
            df = pd.read_excel(data_path, sheet_name='do_eksportu')
            
            # Sprawdź strukturę danych
            if 'nazwa_pola' not in df.columns or 'wartosc' not in df.columns:
                raise ValueError("Arkusz 'do_eksportu' musi mieć kolumny 'nazwa_pola' i 'wartosc'")
            
            # Konwertuj na słownik
            data_dict = df.set_index('nazwa_pola')['wartosc'].to_dict()
            
            print(f"✅ Wczytano {len(data_dict)} pól z arkusza do_eksportu")
            
        except Exception as e:
            QMessageBox.critical(
                None,
                "Błąd wczytywania",
                f"Nie udało się wczytać arkusza 'do_eksportu':\n{str(e)}"
            )
            return

        # ============================================
        # 4) WYODRĘBNIJ SUFFIXY BUDYNKÓW
        # ============================================
        suffixes = extract_building_suffixes(data_dict)
        
        if not suffixes:
            QMessageBox.warning(
                None,
                "Brak danych budynków",
                "Nie znaleziono danych budynków w pliku.\n"
                "Upewnij się, że plik zawiera pola typu 'liczba_budynkow_x'."
            )
            # Ustaw domyślny suffix
            suffixes = ['x']
        
        print(f"🏠 Znalezione suffixy budynków: {suffixes}")

        # ============================================
        # 5) ZGRUPUJ DANE BUDYNKÓW
        # ============================================
        buildings = group_building_data(data_dict, suffixes)
        
        print(f"📊 Zgrupowano dane dla {len(buildings)} typów budynków:")
        for b in buildings:
            print(f"   - [{b['suffix_upper']}] {b['funkcja']}: {b['liczba_budynkow']} szt.")
            print(f"     Szerokość elewacji: {b['szer_elew_front_min']} - {b['szer_elew_front_max']}")
            print(f"     Wysokość: {b['wys_zab_min']} - {b['wys_zab_max']}")

        # ============================================
        # 6) OBLICZ SUMY
        # ============================================
        totals = calculate_totals(buildings)

        # ============================================
        # 7) PRZYGOTUJ KONTEKST DLA SZABLONU
        # ============================================
        context = {}
        
        # Dodaj wszystkie pola z data_dict (płasko)
        for key, value in data_dict.items():
            # Usuń suffixy z kluczy dla kompatybilności wstecznej
            context[key] = value if not pd.isna(value) else ''
        
        # Dodaj listę budynków (dla pętli Jinja2)
        context['budynki'] = buildings
        
        # Dodaj pierwszy budynek jako 'budynek' dla kompatybilności wstecznej
        if buildings:
            context['budynek'] = buildings[0]
        
        # Dodaj sumy
        context.update(totals)
        
        # Dodaj datę
        context['today'] = datetime.now().strftime('%d.%m.%Y')
        
        # === TRANSFORMACJA {{obecne_zagospodarowanie}} ===
        obecne = str(context.get('obecne_zagospodarowanie', ''))
        if obecne.lower().startswith('zabudowany'):
            rodzaj_istn = str(context.get('rodzaj_istniejacy', ''))
            if not rodzaj_istn:
                for separator in [' - ', ' + ']:
                    if separator in obecne:
                        rodzaj_istn = obecne.split(separator, 1)[1].strip()
                        break
            if rodzaj_istn:
                context['obecne_zagospodarowanie'] = f"występuje {rodzaj_istn}"
            else:
                context['obecne_zagospodarowanie'] = "występuje zabudowa"
        elif obecne.lower() == 'niezabudowany':
            context['obecne_zagospodarowanie'] = "nie występuje żadna zabudowa"
        
        # Dodaj dodatkowe zmienne pomocnicze
        context['liczba_budynkow_total'] = totals['suma_liczba_budynkow']
        context['czy_wiele_budynkow'] = len(buildings) > 1
        context['czy_wiele_typow'] = len(buildings) > 1

        # ============================================
        # 7b) PLAN OGOLNY — automat wyborow w szablonie
        # ============================================
        # Szablony "..._POG_2026.docx" zawieraja warianty rozdzielone "/"
        # (np. "jest nie wieksza/jest wieksza"). Ponizsza funkcja:
        #   - przepisuje wybory dokonane w oknie "Dane dzialki przedmiotowej"
        #     (§ 2 ust. 2/3, § 3 ust. 1/2/3, § 7 ust. 1-2/3, zgodnosc funkcji),
        #   - automatycznie porownuje parametry ustalone w decyzji z parametrami
        #     strefy planistycznej i wybiera wlasciwa fraze.
        szablon_pog = szablon_uzywa_planu_ogolnego(template_path)

        try:
            _pog = _plan_ogolny()
            _pog.uzupelnij_wybory(context, buildings)
        except Exception as e:
            print(f"⚠️ Nie udało się uzupełnić ustaleń planu ogólnego: {e}")
            traceback.print_exc()

        if not szablon_pog:
            # Stary szablon (sprzed planu ogólnego) — zmienne pog_* są w kontekście,
            # ale szablon ich nie używa. Nie zawracamy użytkownikowi głowy.
            print("\nℹ️ Wybrano szablon sprzed planu ogólnego "
                  "— ustalenia planu nie będą wstawiane do dokumentu.")
        else:
            print("\n🗺️ Plan ogólny:")
            print(f"   strefa: {context.get('pog_strefa_oznaczenie', '—')} "
                  f"({context.get('pog_strefa_nazwa_mian', context.get('pog_strefa_nazwa', '—'))})")
            print(f"   podstawa ustaleń: {context.get('podstawa_ustalen', '—')} rozporządzenia")
            print(f"   nadziemna intensywność: {context.get('maks_nadz_inten_zab_inw', '—')} "
                  f"vs {context.get('pog_maks_nadz_intens', '—')} → {context.get('pog_ocena_nadz_intens', '—')}")
            print(f"   udział pow. zabudowy:   {context.get('Sredni_wpz', '—')} "
                  f"vs {context.get('pog_maks_udzial_pow_zab', '—')} → {context.get('pog_ocena_udzial_pow_zab', '—')}")
            print(f"   wysokość zabudowy:      vs {context.get('pog_maks_wysokosc', '—')} "
                  f"→ {context.get('pog_ocena_wysokosc', '—')}")
            print(f"   udział PBC:             {context.get('Sredni_wpbc', '—')} "
                  f"vs {context.get('pog_min_pbc', '—')} → {context.get('pog_ocena_pbc', '—')}")

            ostrzezenia = list(context.get('pog_ostrzezenia') or [])
            if str(context.get('pog_dostepny', 'nie')) != 'tak':
                ostrzezenia.insert(0, (
                    "NIE ODCZYTANO STREFY PLANISTYCZNEJ — w dokumencie pojawią się "
                    "wielokropki zamiast ustaleń planu. Wczytaj warstwy planu ogólnego "
                    "i powtórz krok „Dane działki”."
                ))
            for o in ostrzezenia:
                print(f"   ⚠️ {o}")
            if ostrzezenia:
                QMessageBox.warning(
                    None,
                    "Plan ogólny — sprawdź analizę",
                    "Automat wykrył następujące kwestie:\n\n• " + "\n• ".join(ostrzezenia) +
                    "\n\nDokument zostanie wygenerowany, ale zweryfikuj powyższe punkty."
                )

        # ============================================
        # 8) RENDERUJ SZABLON
        # ============================================
        print(f"\n📝 Renderowanie szablonu: {os.path.basename(template_path)}")
        
        doc = DocxTemplate(template_path)
        doc.render(context)

        # ============================================
        # 9) ZAPISZ DOKUMENT
        # ============================================
        # Pobierz znak_sprawy z danych
        znak_sprawy = data_dict.get('znak_sprawy', 'analiza_wz')
        znak_sprawy = str(znak_sprawy).replace('/', '_').replace('\\', '_').replace(' ', '_')
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_name = f"6730_1_{znak_sprawy}_2026_analiza_{timestamp}.docx"
        output_path = os.path.join(project_directory, output_name)
        
        doc.save(output_path)

        print(f"\n✅ Zapisano dokument: {output_path}")
        
        QMessageBox.information(
            None,
            "Sukces",
            f"Dokument został wygenerowany!\n\n"
            f"Plik: {output_name}\n"
            f"Lokalizacja: {project_directory}\n\n"
            f"Przetworzono {len(buildings)} typ(ów) budynków."
        )

    except Exception as e:
        error_msg = f"Wystąpił błąd podczas generowania dokumentu:\n\n{str(e)}"
        print(f"\n❌ {error_msg}")
        print("\nSzczegóły błędu:")
        traceback.print_exc()
        
        QMessageBox.critical(None, "Błąd", error_msg)


# ============================================
# PUNKT WEJŚCIA
# ============================================
generate_document()