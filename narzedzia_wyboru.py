#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
narzedzia_wyboru.py — narzedzia liczace parametry z obiektow zaznaczonych na mapie.

Okno "Dane dzialki przedmiotowej" jest niemodalne, wiec w trakcie jego pracy
mozna normalnie korzystac z mapy. Oba narzedzia dzialaja tak samo:

    1. przycisk "Zaznacz na mapie" ustawia wlasciwa warstwe jako aktywna
       i wlacza standardowe narzedzie zaznaczania QGIS,
    2. uzytkownik klika obiekty (Ctrl = dokladanie do zaznaczenia),
    3. przycisk liczacy odczytuje zaznaczenie i zwraca wynik.

NARZEDZIE 1 — srednia wysokosc zabudowy na dzialkach sasiednich
    Warstwa 'budynki_parametry', pole 'wysokosc'. Srednia liczona jest zawsze,
    niezaleznie od tego, ktory ustep § 7 rozporzadzenia zostal wybrany.

NARZEDZIE 2 — linia zabudowy z dwoch dzialek sasiednich
    Warstwa 'linie_zabudowy', pole 'distance'. Porownuje odleglosci:
      - rowne (w granicach TOLERANCJA_LZ_M)  -> § 3 ust. 1,
      - rozne                                -> § 3 ust. 2,
    a jako ustalona linie zabudowy przyjmuje wieksza z odleglosci.
"""

from qgis.core import QgsProject

__all__ = [
    "TOLERANCJA_LZ_M",
    "WARSTWA_BUDYNKI",
    "WARSTWA_LINIE",
    "aktywuj_zaznaczanie",
    "srednia_wysokosc_sasiadow",
    "linia_zabudowy_z_zaznaczenia",
    "formatuj_metry",
]

WARSTWA_BUDYNKI = "budynki_parametry"
WARSTWA_LINIE = "linie_zabudowy"

# Ponizej tej roznicy odleglosci uznajemy linie zabudowy za takie same.
# Linie sa obrysowywane recznie z mapy, wiec kilka centymetrow to szum pomiaru,
# a nie faktyczna roznica w usytuowaniu zabudowy.
TOLERANCJA_LZ_M = 0.10

# Mozliwe nazwy pola wysokosci (rozne wersje warstwy budynkow)
POLA_WYSOKOSCI = ("wysokosc", "wysokość", "wys_zab", "wysokosc_bud", "height")
POLA_ODLEGLOSCI = ("distance", "odleglosc", "odległość", "dist")


# ---------------------------------------------------------------- pomocnicze

def _warstwa(nazwa):
    """Warstwa po nazwie; dopasowanie dokladne, potem bez wzgledu na wielkosc liter."""
    proj = QgsProject.instance()
    znalezione = proj.mapLayersByName(nazwa)
    if znalezione:
        return znalezione[0]
    for w in proj.mapLayers().values():
        if w.name().strip().lower() == nazwa.strip().lower():
            return w
    return None


def _nazwa_pola(layer, kandydaci):
    """Pierwsze pasujace pole warstwy (bez wzgledu na wielkosc liter)."""
    istniejace = {f.name().lower(): f.name() for f in layer.fields()}
    for kand in kandydaci:
        if kand.lower() in istniejace:
            return istniejace[kand.lower()]
    return None


def _liczba(wartosc):
    """Liczba z wartosci pola; None gdy pusto albo nie da sie sparsowac."""
    if wartosc is None:
        return None
    try:
        if hasattr(wartosc, "isNull") and wartosc.isNull():
            return None
    except Exception:  # nosec B110
        pass
    if isinstance(wartosc, (int, float)):
        try:
            return float(wartosc)
        except (TypeError, ValueError):
            return None
    tekst = str(wartosc).strip().replace(",", ".")
    if not tekst or tekst.upper() == "NULL":
        return None
    tekst = tekst.split(" ")[0]
    try:
        return float(tekst)
    except ValueError:
        return None


def formatuj_metry(wartosc, miejsca=2):
    """Liczba -> tekst po polsku z jednostka: 9.2 -> '9,20 m'."""
    if wartosc is None:
        return ""
    return (f"%.{miejsca}f" % float(wartosc)).replace(".", ",") + " m"


def aktywuj_zaznaczanie(nazwa_warstwy):
    """
    Ustawia warstwe jako aktywna i wlacza narzedzie zaznaczania QGIS.
    Zwraca (ok, komunikat).
    """
    layer = _warstwa(nazwa_warstwy)
    if layer is None:
        return False, f"Nie znaleziono warstwy '{nazwa_warstwy}' w projekcie."

    try:
        from qgis.utils import iface
        iface.setActiveLayer(layer)
        layer.removeSelection()
        iface.actionSelect().trigger()
    except Exception as e:
        return False, f"Nie udalo sie wlaczyc narzedzia zaznaczania: {e}"

    return True, (f"Warstwa '{layer.name()}' jest aktywna, narzędzie zaznaczania "
                  f"włączone. Kliknij obiekty na mapie (Ctrl = dokładanie do zaznaczenia).")


# ---------------------------------------------- NARZEDZIE 1: wysokosc sasiadow

def srednia_wysokosc_sasiadow(nazwa_warstwy=WARSTWA_BUDYNKI):
    """
    Srednia wysokosc zaznaczonych budynkow.

    Zwraca (ok, dane, komunikat), gdzie dane to slownik:
        srednia   — float,
        wartosci  — lista wysokosci uzytych do sredniej,
        liczba    — ile budynkow policzono,
        pominiete — ile zaznaczonych budynkow nie mialo wysokosci.
    """
    layer = _warstwa(nazwa_warstwy)
    if layer is None:
        return False, None, (f"Nie znaleziono warstwy '{nazwa_warstwy}'. "
                             f"Uruchom wcześniejsze kroki analizy.")

    pole = _nazwa_pola(layer, POLA_WYSOKOSCI)
    if pole is None:
        return False, None, (f"Warstwa '{layer.name()}' nie ma pola wysokości "
                             f"(szukano: {', '.join(POLA_WYSOKOSCI)}).")

    zaznaczone = layer.selectedFeatures()
    if not zaznaczone:
        return False, None, ("Nie zaznaczono żadnego budynku. Kliknij „Zaznacz na mapie”, "
                             "wskaż budynki na działkach sąsiednich i spróbuj ponownie.")

    wartosci = []
    pominiete = 0
    for feat in zaznaczone:
        wys = _liczba(feat[pole])
        if wys is None or wys <= 0:
            pominiete += 1
            continue
        wartosci.append(round(wys, 2))

    if not wartosci:
        return False, None, (f"Żaden z {len(zaznaczone)} zaznaczonych budynków nie ma "
                             f"wypełnionego pola '{pole}'.")

    srednia = round(sum(wartosci) / len(wartosci), 2)
    dane = {
        "srednia": srednia,
        "wartosci": wartosci,
        "liczba": len(wartosci),
        "pominiete": pominiete,
    }

    komunikat = (f"Średnia z {len(wartosci)} budynk(ów): {formatuj_metry(srednia)} "
                 f"(wysokości: {'; '.join(formatuj_metry(w) for w in wartosci)}).")
    if pominiete:
        komunikat += f" Pominięto {pominiete} bez wysokości."
    if len(wartosci) != 2:
        komunikat += (" Uwaga: § 7 rozporządzenia odnosi się do zabudowy na przylegających "
                      "działkach sąsiednich dostępnych z tej samej drogi publicznej — "
                      "sprawdź, czy zaznaczenie jest właściwe.")

    return True, dane, komunikat


# ------------------------------------------- NARZEDZIE 2: linia zabudowy

def linia_zabudowy_z_zaznaczenia(nazwa_warstwy=WARSTWA_LINIE,
                                 tolerancja=TOLERANCJA_LZ_M):
    """
    Porownuje zaznaczone linie zabudowy z dzialek sasiednich.

    Zwraca (ok, dane, komunikat), gdzie dane to slownik:
        odleglosci  — lista odleglosci,
        ustalona    — wieksza z odleglosci (float),
        rowne       — bool, czy roznica miesci sie w tolerancji,
        ustep       — '1' albo '2' (ustep § 3 rozporzadzenia),
        roznica     — bezwzgledna roznica odleglosci.
    """
    layer = _warstwa(nazwa_warstwy)
    if layer is None:
        return False, None, (f"Nie znaleziono warstwy '{nazwa_warstwy}'. "
                             f"Uruchom krok pomiaru linii zabudowy.")

    pole = _nazwa_pola(layer, POLA_ODLEGLOSCI)
    if pole is None:
        return False, None, (f"Warstwa '{layer.name()}' nie ma pola odległości "
                             f"(szukano: {', '.join(POLA_ODLEGLOSCI)}).")

    zaznaczone = layer.selectedFeatures()
    if len(zaznaczone) < 2:
        return False, None, ("Zaznacz dwie linie zabudowy — po jednej z każdej "
                             "przylegającej działki sąsiedniej dostępnej z tej samej "
                             "drogi publicznej.")

    odleglosci = []
    for feat in zaznaczone:
        d = _liczba(feat[pole])
        if d is not None and d > 0:
            odleglosci.append(round(d, 2))

    if len(odleglosci) < 2:
        return False, None, (f"Zaznaczone obiekty nie mają wypełnionego pola '{pole}' "
                             f"(znaleziono {len(odleglosci)} wartości).")

    najmniejsza = min(odleglosci)
    najwieksza = max(odleglosci)
    roznica = round(najwieksza - najmniejsza, 2)
    rowne = roznica <= tolerancja

    dane = {
        "odleglosci": odleglosci,
        "ustalona": najwieksza,
        "rowne": rowne,
        "ustep": "1" if rowne else "2",
        "roznica": roznica,
    }

    opis = "; ".join(formatuj_metry(d) for d in odleglosci)
    if rowne:
        komunikat = (f"Odległości ({opis}) są równe w granicach tolerancji "
                     f"{formatuj_metry(tolerancja)} — § 3 ust. 1 rozporządzenia. "
                     f"Ustalona linia zabudowy: {formatuj_metry(najwieksza)}.")
    else:
        komunikat = (f"Odległości ({opis}) różnią się o {formatuj_metry(roznica)} "
                     f"— § 3 ust. 2 rozporządzenia. Jako ustaloną linię zabudowy "
                     f"przyjęto większą: {formatuj_metry(najwieksza)}.")

    if len(odleglosci) > 2:
        komunikat += (f" Uwaga: zaznaczono {len(odleglosci)} linii, a przepis odnosi się "
                      f"do dwóch działek sąsiednich.")

    return True, dane, komunikat
