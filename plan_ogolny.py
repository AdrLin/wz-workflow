#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_ogolny.py — obsluga planu ogolnego gminy (schemat APP 2.0) w WZ Workflow.

Modul robi dwie rzeczy:

1. ODCZYT (uzywany przez okno "Dane dzialki przedmiotowej", krok 13)
   Znajduje w projekcie warstwy planu ogolnego (StrefaPlanistyczna,
   ObszarUzupelnieniaZabudowy, ObszarZabudowySrodmiejskiej), przecina je
   z geometria terenu inwestycji i zwraca plaski slownik pol `pog_*`
   gotowy do zapisu w arkuszu `do_eksportu`.

2. AUTOMAT WYBOROW (uzywany przez generator_analiz_opisowych.py, krok 14)
   W nowym wzorze analizy (po uchwaleniu planu ogolnego) czesc zdan ma
   warianty rozdzielone znakiem "/" — np. "jest nie wieksza/jest wieksza".
   Funkcja `uzupelnij_wybory()` rozstrzyga te warianty:
     * porownania liczbowe (parametr ustalony w decyzji vs parametr strefy)
       — w pelni automatycznie,
     * wybory merytoryczne (§ 2 ust. 2 / ust. 3, § 3 ust. 1/2/3,
       § 7 ust. 1-2 / ust. 3, zgodnosc funkcji) — z pol wybranych przez
       uzytkownika w oknie dialogowym; automat podstawia tylko wartosci
       domyslne.

Modul celowo NIE importuje pandas ani docxtpl — ma dzialac takze wtedy,
gdy krok 13 jest uruchamiany bez bibliotek naukowych.
"""

import os

from qgis.core import (
    QgsProject,
    QgsGeometry,
    QgsFeatureRequest,
    QgsCoordinateTransform,
    QgsWkbTypes,
)

__all__ = [
    "NAZWY_STREF",
    "NAZWY_STREF_ODM",
    "KPT_NAZWY",
    "znajdz_warstwe_pog",
    "geometria_terenu_inwestycji",
    "odczytaj_strefe_planistyczna",
    "odczytaj_obszar",
    "zbierz_dane_pog",
    "uzupelnij_wybory",
    "PODSTAWA_PAR2_UST2",
    "PODSTAWA_PAR2_UST3",
]


# =====================================================================
# SLOWNIKI KODOWE (rozporzadzenie MRiT w sprawie planu ogolnego gminy)
# =====================================================================

NAZWY_STREF = {
    "SW": "strefa wielofunkcyjna z zabudową mieszkaniową wielorodzinną",
    "SJ": "strefa wielofunkcyjna z zabudową mieszkaniową jednorodzinną",
    "SZ": "strefa wielofunkcyjna z zabudową zagrodową",
    "SU": "strefa usługowa",
    "SH": "strefa handlu wielkopowierzchniowego",
    "SP": "strefa gospodarcza",
    "SR": "strefa produkcji rolniczej",
    "SI": "strefa infrastrukturalna",
    "SN": "strefa zieleni i rekreacji",
    "SC": "strefa cmentarzy",
    "SG": "strefa górnictwa",
    "SO": "strefa otwarta",
    "SK": "strefa komunikacyjna",
}

# Forma uzywana po "w strefie planistycznej ..." oraz "dla strefy ..."
# (miejscownik i dopelniacz rodzaju zenskiego maja tu identyczna postac)
NAZWY_STREF_ODM = {
    "SW": "wielofunkcyjnej z zabudową mieszkaniową wielorodzinną",
    "SJ": "wielofunkcyjnej z zabudową mieszkaniową jednorodzinną",
    "SZ": "wielofunkcyjnej z zabudową zagrodową",
    "SU": "usługowej",
    "SH": "handlu wielkopowierzchniowego",
    "SP": "gospodarczej",
    "SR": "produkcji rolniczej",
    "SI": "infrastrukturalnej",
    "SN": "zieleni i rekreacji",
    "SC": "cmentarzy",
    "SG": "górnictwa",
    "SO": "otwartej",
    "SK": "komunikacyjnej",
}

# Kody profilu funkcjonalnego (KPT-MPZP-*) -> nazwa przeznaczenia terenu
KPT_NAZWY = {
    "KPT-MPZP-MN": "teren zabudowy mieszkaniowej jednorodzinnej",
    "KPT-MPZP-MW": "teren zabudowy mieszkaniowej wielorodzinnej",
    "KPT-MPZP-MZ": "teren zabudowy zagrodowej",
    "KPT-MPZP-U": "teren usług",
    "KPT-MPZP-UE": "teren usług edukacji",
    "KPT-MPZP-UG": "teren usług gastronomii",
    "KPT-MPZP-UHD": "teren usług handlu detalicznego",
    "KPT-MPZP-UK": "teren usług kultury i rozrywki",
    "KPT-MPZP-UN": "teren usług nauki",
    "KPT-MPZP-UR": "teren usług kultu religijnego",
    "KPT-MPZP-US": "teren usług sportu i rekreacji",
    "KPT-MPZP-UT": "teren usług turystyki",
    "KPT-MPZP-UZ": "teren usług zdrowia i pomocy społecznej",
    "KPT-MPZP-UA": "teren usług administracji publicznej",
    "KPT-MPZP-UO": "teren usług innych",
    "KPT-MPZP-H": "teren handlu wielkopowierzchniowego",
    "KPT-MPZP-P": "teren produkcji",
    "KPT-MPZP-PS": "teren składów i magazynów",
    "KPT-MPZP-PEF": "teren elektrowni słonecznej",
    "KPT-MPZP-PEW": "teren elektrowni wiatrowej",
    "KPT-MPZP-PG": "teren górnictwa",
    "KPT-MPZP-R": "teren rolnictwa",
    "KPT-MPZP-RN": "teren rolnictwa z zakazem zabudowy",
    "KPT-MPZP-L": "teren lasu",
    "KPT-MPZP-ZN": "teren zieleni naturalnej",
    "KPT-MPZP-ZP": "teren zieleni urządzonej",
    "KPT-MPZP-ZD": "teren ogrodów działkowych",
    "KPT-MPZP-ZB": "teren plaży",
    "KPT-MPZP-C": "teren cmentarza",
    "KPT-MPZP-W": "teren wód",
    "KPT-MPZP-I": "teren infrastruktury technicznej",
    "KPT-MPZP-K": "teren komunikacji",
    "KPT-MPZP-KDA": "teren autostrady",
    "KPT-MPZP-KDS": "teren drogi ekspresowej",
    "KPT-MPZP-KDG": "teren drogi głównej",
    "KPT-MPZP-KDR": "teren drogi głównej ruchu przyspieszonego",
    "KPT-MPZP-KDZ": "teren drogi zbiorczej",
    "KPT-MPZP-KK": "teren komunikacji kolejowej i szynowej",
    "KPT-MPZP-KKL": "teren komunikacji kolei linowej",
    "KPT-MPZP-KL": "teren komunikacji lotniczej",
    "KPT-MPZP-KW": "teren komunikacji wodnej",
    "KPT-MPZP-KO": "teren obsługi komunikacji",
}

# Nazwy warstw, pod ktorymi Narzedziownik APP / GDAL wczytuje obiekty planu.
# Kolejnosc = priorytet dopasowania.
WARSTWY_POG = {
    "strefa": [
        "StrefaPlanistyczna",
        "Strefa planistyczna",
        "strefy_planistyczne",
        "StrefyPlanistyczne",
        "POG - StrefaPlanistyczna",
    ],
    "ouz": [
        "ObszarUzupelnieniaZabudowy",
        "Obszar uzupełnienia zabudowy",
        "OUZ",
        "POG - ObszarUzupelnieniaZabudowy",
    ],
    "ozs": [
        "ObszarZabudowySrodmiejskiej",
        "Obszar zabudowy śródmiejskiej",
        "OZS",
        "POG - ObszarZabudowySrodmiejskiej",
    ],
    "akt": [
        "AktPlanowaniaPrzestrzennego",
    ],
}

# Pola rozstrzygajace, gdy nazwa warstwy jest niestandardowa
POLA_ROZPOZNAWCZE = {
    "strefa": ["maksNadziemnaIntensywnoscZabudowy", "minUdzialPowierzchniBiologicznieCzynnej"],
    "ouz": [],
    "ozs": [],
    "akt": ["tytul"],
}

NAZWY_WARSTW_TERENU = [
    "granica_terenu",
    "granica_terenu_wskazniki",
    "granica_terenu_inwestycji",
    "granica terenu planowanej inwestycji",
]


# =====================================================================
# NARZEDZIA POMOCNICZE
# =====================================================================

def _pola(layer):
    return [f.name() for f in layer.fields()]


def _pole(feat, layer, *kandydaci):
    """Zwraca wartosc pierwszego pasujacego pola (bez wzgledu na wielkosc liter)."""
    nazwy = _pola(layer)
    for kand in kandydaci:
        for n in nazwy:
            if n.lower() == kand.lower():
                v = feat[n]
                try:
                    if v is None or (hasattr(v, "isNull") and v.isNull()):
                        return None
                except Exception:  # nosec B110
                    pass
                return v
    return None


def _num(v):
    """Liczba z wartosci, ktora moze byc floatem, '0,65', '12,5 m', '40%'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "nie określono", "nie okreslono", "brak", "-", "—"):
        return None
    s = s.replace("%", "").replace("\u00a0", " ")
    s = s.split(" ")[0]
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(v, prec=2, sufiks=""):
    """Formatuje liczbe po polsku (przecinek), bez zbednych zer."""
    f = _num(v)
    if f is None:
        return "nie określono"
    if abs(f - round(f)) < 1e-9:
        txt = str(int(round(f)))
    else:
        txt = ("%%.%df" % prec) % f
        txt = txt.rstrip("0").rstrip(".")
        txt = txt.replace(".", ",")
    return txt + sufiks


def _lista_profili(v):
    """
    Normalizuje pole profilPodstawowy/profilDodatkowy do listy nazw przeznaczen.

    Wartosc moze byc: lista Pythona, string z separatorami, adresy URL
    z kodami KPT-MPZP-*, albo gotowe nazwy ("teren usług").
    """
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        surowe = [str(x) for x in v]
    else:
        s = str(v).strip()
        if not s or s.lower() in ("nan", "none", "null"):
            return []
        s = s.strip("[]{}")
        for sep in ("\n", ";", "|", ","):
            if sep in s:
                surowe = [x for x in s.split(sep)]
                break
        else:
            surowe = [s]

    wynik = []
    for tok in surowe:
        tok = tok.strip().strip("'\"").strip()
        if not tok:
            continue
        kod = None
        if "KPT-MPZP-" in tok:
            kod = "KPT-MPZP-" + tok.split("KPT-MPZP-", 1)[1].strip().strip("'\"")
            kod = kod.split()[0].split(",")[0]
        elif tok.startswith("http"):
            kod = tok.rstrip("/").split("/")[-1].split("#")[-1]
        nazwa = KPT_NAZWY.get(kod, None) if kod else None
        if nazwa is None:
            nazwa = KPT_NAZWY.get(tok, tok if not tok.startswith("http") else kod or tok)
        if nazwa and nazwa not in wynik:
            wynik.append(nazwa)
    return wynik


def _nazwa_strefy_odm(symbol, pole_nazwa):
    """
    Forma nazwy strefy pasujaca do zdan "w strefie planistycznej ..." /
    "dla strefy ... oznaczonej symbolem ...".
    """
    if symbol:
        odm = NAZWY_STREF_ODM.get(str(symbol).strip().upper())
        if odm:
            return odm
    # awaryjnie: mianownik bez wiodacego slowa "strefa"
    nazwa = _nazwa_strefy(symbol, pole_nazwa)
    if nazwa.lower().startswith("strefa "):
        return nazwa[7:]
    return nazwa


def _nazwa_strefy(symbol, pole_nazwa):
    """Nazwa strefy planistycznej: najpierw slownik po symbolu, potem pole `nazwa`."""
    if symbol:
        nazwa = NAZWY_STREF.get(str(symbol).strip().upper())
        if nazwa:
            return nazwa
    if pole_nazwa:
        s = str(pole_nazwa).strip()
        if s and not s.startswith("http"):
            return s
        if s.startswith("http"):
            kod = s.rstrip("/").split("/")[-1]
            # strefaWielofunkcyjnaZZabudowaMieszkaniowaJednorodzinna -> rozbij camelCase
            import re as _re
            czlony = _re.sub(r"(?<!^)(?=[A-Z])", " ", kod).lower()
            return czlony.replace(" z ", " z ").strip()
    return "nie określono"


# =====================================================================
# 1. ODCZYT PLANU OGOLNEGO
# =====================================================================

def znajdz_warstwe_pog(klucz):
    """Znajduje warstwe planu ogolnego ('strefa' / 'ouz' / 'ozs' / 'akt')."""
    proj = QgsProject.instance()
    warstwy = list(proj.mapLayers().values())

    # 1) dokladna nazwa
    for nazwa in WARSTWY_POG.get(klucz, []):
        znalezione = proj.mapLayersByName(nazwa)
        if znalezione:
            return znalezione[0]

    # 2) nazwa zawierajaca wzorzec (bez wzgledu na wielkosc liter i spacje)
    for nazwa in WARSTWY_POG.get(klucz, []):
        wzor = nazwa.lower().replace(" ", "")
        for w in warstwy:
            if wzor in w.name().lower().replace(" ", ""):
                return w

    # 3) po zestawie pol
    for pole in POLA_ROZPOZNAWCZE.get(klucz, []):
        for w in warstwy:
            try:
                if pole.lower() in [f.lower() for f in _pola(w)]:
                    return w
            except Exception:  # nosec B112
                continue
    return None


def geometria_terenu_inwestycji():
    """
    Zwraca (QgsGeometry, QgsCoordinateReferenceSystem) terenu inwestycji.
    Laczy wszystkie obiekty warstwy granicy terenu (obsluga scalonych dzialek).
    """
    proj = QgsProject.instance()
    for nazwa in NAZWY_WARSTW_TERENU:
        warstwy = proj.mapLayersByName(nazwa)
        if not warstwy:
            continue
        layer = warstwy[0]
        geoms = [f.geometry() for f in layer.getFeatures()
                 if f.hasGeometry() and not f.geometry().isEmpty()]
        if not geoms:
            continue
        geom = geoms[0] if len(geoms) == 1 else QgsGeometry.unaryUnion(geoms)
        if geom is None or geom.isEmpty():
            continue
        return geom, layer.crs()
    return None, None


def _przetnij(layer, geom, crs_zrodla):
    """
    Zwraca liste (feature, pole_przeciecia_m2) obiektow warstwy przecinajacych
    geometrie `geom` podana w ukladzie `crs_zrodla`.
    """
    if layer is None or geom is None or geom.isEmpty():
        return []

    g = QgsGeometry(geom)
    if crs_zrodla is not None and layer.crs() != crs_zrodla:
        try:
            tr = QgsCoordinateTransform(crs_zrodla, layer.crs(), QgsProject.instance())
            g.transform(tr)
        except Exception as exc:
            print(f"⚠️ Plan ogólny: nie udało się przetransformować geometrii: {exc}")
            return []

    if not g.isGeosValid():
        g = g.makeValid()

    wynik = []
    req = QgsFeatureRequest().setFilterRect(g.boundingBox())
    for feat in layer.getFeatures(req):
        if not feat.hasGeometry():
            continue
        fg = feat.geometry()
        if not fg.isGeosValid():
            fg = fg.makeValid()
        if not fg.intersects(g):
            continue
        try:
            czesc = fg.intersection(g)
            pole = czesc.area() if czesc and not czesc.isEmpty() else 0.0
        except Exception:
            pole = 0.0
        wynik.append((feat, pole))

    wynik.sort(key=lambda x: x[1], reverse=True)
    return wynik


def odczytaj_strefe_planistyczna(geom=None, crs=None):
    """
    Zwraca slownik opisujacy strefe planistyczna obejmujaca teren inwestycji.
    Gdy teren lezy w kilku strefach — wybierana jest strefa o najwiekszym
    udziale powierzchniowym, a pozostale trafiaja do klucza `inne_strefy`.
    """
    layer = znajdz_warstwe_pog("strefa")
    if layer is None:
        return None

    if geom is None:
        geom, crs = geometria_terenu_inwestycji()
    if geom is None:
        return None

    trafienia = _przetnij(layer, geom, crs)
    if not trafienia:
        return None

    suma = sum(p for _, p in trafienia) or 1.0
    feat, pole = trafienia[0]

    symbol = _pole(feat, layer, "symbol")
    oznaczenie = _pole(feat, layer, "oznaczenie")
    nazwa_pola = _pole(feat, layer, "nazwa", "rodzajStrefy", "nazwaStrefy")

    dane = {
        "symbol": str(symbol).strip() if symbol else "",
        "oznaczenie": str(oznaczenie).strip() if oznaczenie else "",
        "nazwa": _nazwa_strefy(symbol, nazwa_pola),
        "nazwa_odm": _nazwa_strefy_odm(symbol, nazwa_pola),
        "maks_nadz_intens": _num(_pole(feat, layer, "maksNadziemnaIntensywnoscZabudowy")),
        "maks_udzial_pow_zab": _num(_pole(feat, layer, "maksUdzialPowierzchniZabudowy")),
        "maks_wysokosc": _num(_pole(feat, layer, "maksWysokoscZabudowy")),
        "min_pbc": _num(_pole(feat, layer, "minUdzialPowierzchniBiologicznieCzynnej")),
        "profil_podstawowy": _lista_profili(_pole(feat, layer, "profilPodstawowy")),
        "profil_dodatkowy": _lista_profili(_pole(feat, layer, "profilDodatkowy")),
        "udzial": round(100.0 * pole / suma, 1),
        "inne_strefy": [],
    }

    for f2, p2 in trafienia[1:]:
        ozn = _pole(f2, layer, "oznaczenie")
        dane["inne_strefy"].append({
            "oznaczenie": str(ozn).strip() if ozn else "",
            "udzial": round(100.0 * p2 / suma, 1),
        })
    return dane


def odczytaj_obszar(klucz, geom=None, crs=None):
    """
    Sprawdza, czy teren inwestycji lezy w obszarze ('ouz' albo 'ozs').
    Zwraca (znaleziono_warstwe, lezy_w_obszarze, [oznaczenia]).
    """
    layer = znajdz_warstwe_pog(klucz)
    if layer is None:
        return False, False, []

    if geom is None:
        geom, crs = geometria_terenu_inwestycji()
    if geom is None:
        return True, False, []

    trafienia = _przetnij(layer, geom, crs)
    oznaczenia = []
    for feat, _pole_m2 in trafienia:
        ozn = _pole(feat, layer, "oznaczenie", "symbol", "nazwa")
        if ozn:
            oznaczenia.append(str(ozn).strip())
    return True, bool(trafienia), oznaczenia


def zbierz_dane_pog(geom=None, crs=None):
    """
    Buduje plaski slownik pol `pog_*` do zapisania w arkuszu `do_eksportu`.

    Klucze `*_val` zawieraja surowe liczby (do porownan), pozostale —
    gotowy tekst do wstawienia w dokument.
    """
    if geom is None:
        geom, crs = geometria_terenu_inwestycji()

    dane = {
        "pog_dostepny": "nie",
        "pog_strefa_symbol": "",
        "pog_strefa_oznaczenie": "…",
        "pog_strefa_nazwa": "…",
        "pog_strefa_nazwa_mian": "…",
        "pog_profil_podstawowy": "…",
        "pog_profil_dodatkowy": "…",
        "pog_maks_nadz_intens": "nie określono",
        "pog_maks_nadz_intens_val": "",
        "pog_maks_udzial_pow_zab": "nie określono",
        "pog_maks_udzial_pow_zab_val": "",
        "pog_maks_wysokosc": "nie określono",
        "pog_maks_wysokosc_val": "",
        "pog_min_pbc": "nie określono",
        "pog_min_pbc_val": "",
        "pog_ouz": "nie",
        "pog_ouz_oznaczenie": "",
        "pog_ozs": "nie",
        "pog_ozs_oznaczenie": "",
        "pog_uwagi": "",
    }

    uwagi = []

    strefa = odczytaj_strefe_planistyczna(geom, crs)
    if strefa:
        dane["pog_dostepny"] = "tak"
        dane["pog_strefa_symbol"] = strefa["symbol"]
        dane["pog_strefa_oznaczenie"] = strefa["oznaczenie"] or strefa["symbol"]
        dane["pog_strefa_nazwa"] = strefa["nazwa_odm"]
        dane["pog_strefa_nazwa_mian"] = strefa["nazwa"]
        dane["pog_profil_podstawowy"] = ", ".join(strefa["profil_podstawowy"]) or "nie określono"
        dane["pog_profil_dodatkowy"] = ", ".join(strefa["profil_dodatkowy"]) or "nie określono"

        dane["pog_maks_nadz_intens"] = _fmt(strefa["maks_nadz_intens"], 2)
        dane["pog_maks_udzial_pow_zab"] = _fmt(strefa["maks_udzial_pow_zab"], 0, "%")
        dane["pog_maks_wysokosc"] = _fmt(strefa["maks_wysokosc"], 2, " m")
        dane["pog_min_pbc"] = _fmt(strefa["min_pbc"], 0, "%")

        for klucz_val, klucz_src in (
            ("pog_maks_nadz_intens_val", "maks_nadz_intens"),
            ("pog_maks_udzial_pow_zab_val", "maks_udzial_pow_zab"),
            ("pog_maks_wysokosc_val", "maks_wysokosc"),
            ("pog_min_pbc_val", "min_pbc"),
        ):
            v = strefa[klucz_src]
            dane[klucz_val] = "" if v is None else v

        if strefa["inne_strefy"]:
            opis = "; ".join(
                f"{s['oznaczenie']} ({s['udzial']}%)" for s in strefa["inne_strefy"]
            )
            uwagi.append(
                f"teren leży w kilku strefach — przyjęto {dane['pog_strefa_oznaczenie']} "
                f"({strefa['udzial']}% powierzchni), pozostałe: {opis}"
            )
    else:
        uwagi.append("nie znaleziono warstwy StrefaPlanistyczna lub teren jej nie przecina")

    jest_ouz, w_ouz, ozn_ouz = odczytaj_obszar("ouz", geom, crs)
    if not jest_ouz:
        uwagi.append("brak warstwy ObszarUzupelnieniaZabudowy")
    dane["pog_ouz"] = "tak" if w_ouz else "nie"
    dane["pog_ouz_oznaczenie"] = ", ".join(ozn_ouz)

    jest_ozs, w_ozs, ozn_ozs = odczytaj_obszar("ozs", geom, crs)
    if not jest_ozs:
        uwagi.append("brak warstwy ObszarZabudowySrodmiejskiej")
    dane["pog_ozs"] = "tak" if w_ozs else "nie"
    dane["pog_ozs_oznaczenie"] = ", ".join(ozn_ozs)

    dane["pog_uwagi"] = "; ".join(uwagi)
    return dane


# =====================================================================
# 2. AUTOMAT WYBOROW (warianty rozdzielone "/" w nowym wzorze analizy)
# =====================================================================

PODSTAWA_PAR2_UST2 = "§ 2 ust. 2"
PODSTAWA_PAR2_UST3 = "§ 2 ust. 3"

ZDANIE_PAR2 = {
    PODSTAWA_PAR2_UST2: (
        "zgodnie z § 2 ust. 2 rozporządzenia, ustalenia, o których mowa w § 1 "
        "rozporządzenia, zostaną określone na podstawie istniejącej na obszarze "
        "analizowanym zabudowy i zagospodarowania terenu o takiej samej funkcji, "
        "jak funkcja zabudowy i zagospodarowania terenu określona we wniosku,"
    ),
    PODSTAWA_PAR2_UST3: (
        "zgodnie z § 2 ust. 3 rozporządzenia, ustalenia, o których mowa w § 1 "
        "rozporządzenia, zostaną określone na podstawie zabudowy i zagospodarowania "
        "terenu wszystkich działek zabudowanych w obszarze analizowanym,"
    ),
}

ZAKRES_WYSTEPUJACA = {
    PODSTAWA_PAR2_UST2: "w obszarze analizowanym na terenach o takiej samej funkcji jak wnioskowana",
    PODSTAWA_PAR2_UST3: "na wszystkich terenach zabudowanych znajdujących się w obszarze analizowanym",
}

ZAKRES_POLOZONEJ = {
    PODSTAWA_PAR2_UST2: "położonej w obszarze analizowanym na terenach o takiej samej funkcji jak wnioskowana",
    PODSTAWA_PAR2_UST3: "położonej w obszarze analizowanym",
}

# Frazy porownan: (wariant zgodny z planem ogolnym, wariant niezgodny).
# Zmien tutaj, jesli gmina oczekuje innego brzmienia.
FRAZY_ZGODNOSCI = {
    "nadz_intens": ("jest nie większa", "jest większa"),
    "udzial_pow_zab": ("jest nie większy", "jest większy"),
    "wysokosc": ("jest nie większa", "jest większa"),
    # PBC: ustalenie decyzji musi byc NIE MNIEJSZE niz minimum ze strefy
    "pbc": ("jest nie mniejszy", "jest mniejszy"),
}


def _porownaj(ustalone, plan, klucz, kierunek="max"):
    """
    Zwraca (fraza, ok) dla porownania parametru decyzji z parametrem strefy.

    kierunek='max' — parametr planu jest gorna granica (ustalone <= plan),
    kierunek='min' — parametr planu jest dolna granica (ustalone >= plan).
    """
    zgodne, niezgodne = FRAZY_ZGODNOSCI[klucz]
    u = _num(ustalone)
    p = _num(plan)
    if u is None or p is None:
        # Brak danych — nie zgadujemy; zwracamy wariant zgodny i sygnalizujemy
        return zgodne, None
    eps = 1e-6
    ok = (u <= p + eps) if kierunek == "max" else (u >= p - eps)
    return (zgodne if ok else niezgodne), ok


def _maks_wysokosc_ustalona(context, buildings):
    """
    Wysokosc ustalona w decyzji = najwyzsza z gornych granic dla typow budynkow.
    W szablonie gorna granica to `budynek.srWysZab`.
    """
    wartosci = []
    for b in (buildings or []):
        for klucz in ("srWysZab", "w_wys_max"):
            v = _num(b.get(klucz))
            if v is not None:
                wartosci.append(v)
                break
    if not wartosci:
        v = _num(context.get("srWysZab_x"))
        if v is not None:
            wartosci.append(v)
    return max(wartosci) if wartosci else None


def uzupelnij_wybory(context, buildings=None):
    """
    Uzupelnia kontekst szablonu o zmienne rozstrzygajace warianty "/" .
    Modyfikuje i zwraca `context`.
    """
    ostrzezenia = []

    # --- podstawa ustalen: § 2 ust. 2 albo ust. 3 -------------------------
    podstawa = str(context.get("podstawa_ustalen", "") or "").strip()
    if "ust. 3" in podstawa or "ust.3" in podstawa:
        podstawa = PODSTAWA_PAR2_UST3
    else:
        podstawa = PODSTAWA_PAR2_UST2
    context["podstawa_ustalen"] = podstawa
    context["podstawa_ustalen_zdanie"] = ZDANIE_PAR2[podstawa]
    context["zakres_wystepujaca"] = ZAKRES_WYSTEPUJACA[podstawa]
    context["zakres_polozonej"] = ZAKRES_POLOZONEJ[podstawa]

    # --- § 3 (linia zabudowy) i § 7 (wysokosc) ---------------------------
    par3 = str(context.get("wyb_par3", "") or "1").strip() or "1"
    if par3 not in ("1", "2", "3"):
        par3 = "1"
    context["wyb_par3"] = par3
    context["par3_fraza"] = f"zgodnie z § 3 ust. {par3} rozporządzenia"

    par7 = str(context.get("wyb_par7", "") or "1-2").strip() or "1-2"
    par7 = par7.replace("–", "-").replace("—", "-").replace(" ", "")
    if par7 not in ("1", "2", "1-2", "3"):
        par7 = "1-2"
    context["wyb_par7"] = par7
    context["par7_fraza"] = f"zgodnie z § 7 ust. {par7} rozporządzenia"

    # --- zgodnosc funkcji z profilem strefy ------------------------------
    zg = str(context.get("pog_zgodnosc_funkcji", "") or "").strip()
    if zg not in ("mieści się", "nie mieści się"):
        zg = "mieści się"
    context["pog_zgodnosc_funkcji"] = zg

    # --- porownania liczbowe z ustaleniami strefy ------------------------
    fraza, ok = _porownaj(
        context.get("maks_nadz_inten_zab_inw"),
        context.get("pog_maks_nadz_intens_val") or context.get("pog_maks_nadz_intens"),
        "nadz_intens", "max",
    )
    context["pog_ocena_nadz_intens"] = fraza
    if ok is False:
        ostrzezenia.append("nadziemna intensywność zabudowy PRZEKRACZA wartość ze strefy")
    if ok is None:
        ostrzezenia.append("brak danych do porównania nadziemnej intensywności zabudowy")

    fraza, ok = _porownaj(
        context.get("Sredni_wpz"),
        context.get("pog_maks_udzial_pow_zab_val") or context.get("pog_maks_udzial_pow_zab"),
        "udzial_pow_zab", "max",
    )
    context["pog_ocena_udzial_pow_zab"] = fraza
    if ok is False:
        ostrzezenia.append("udział powierzchni zabudowy PRZEKRACZA wartość ze strefy")
    if ok is None:
        ostrzezenia.append("brak danych do porównania udziału powierzchni zabudowy")

    fraza, ok = _porownaj(
        _maks_wysokosc_ustalona(context, buildings),
        context.get("pog_maks_wysokosc_val") or context.get("pog_maks_wysokosc"),
        "wysokosc", "max",
    )
    context["pog_ocena_wysokosc"] = fraza
    if ok is False:
        ostrzezenia.append("wysokość zabudowy PRZEKRACZA wartość ze strefy")
    if ok is None:
        ostrzezenia.append("brak danych do porównania wysokości zabudowy")

    fraza, ok = _porownaj(
        context.get("Sredni_wpbc"),
        context.get("pog_min_pbc_val") or context.get("pog_min_pbc"),
        "pbc", "min",
    )
    context["pog_ocena_pbc"] = fraza
    if ok is False:
        ostrzezenia.append("udział PBC jest MNIEJSZY niż minimum ze strefy")
    if ok is None:
        ostrzezenia.append("brak danych do porównania udziału powierzchni biologicznie czynnej")

    # --- OUZ i obszar zabudowy srodmiejskiej -----------------------------
    w_ouz = str(context.get("pog_ouz", "nie") or "nie").strip().lower() in ("tak", "true", "1")
    ozn_ouz = str(context.get("pog_ouz_oznaczenie", "") or "").strip()
    if w_ouz:
        context["pog_ouz_zdanie"] = (
            "jest położony na obszarze uzupełnienia zabudowy oznaczonym symbolem "
            f"{ozn_ouz or '…'} w planie ogólnym."
        )
    else:
        context["pog_ouz_zdanie"] = (
            "nie jest położony na obszarze uzupełnienia zabudowy w planie ogólnym."
        )

    w_ozs = str(context.get("pog_ozs", "nie") or "nie").strip().lower() in ("tak", "true", "1")
    context["pog_ozs_zdanie"] = (
        "jest położony na obszarze zabudowy śródmiejskiej, określonym w planie ogólnym."
        if w_ozs else
        "nie jest położony na obszarze zabudowy śródmiejskiej, określonym w planie ogólnym."
    )

    # --- srednia wysokosc na dzialkach sasiednich (§ 7 ust. 3) ------------
    if not str(context.get("sr_wys_dz_sasiednie", "") or "").strip():
        context["sr_wys_dz_sasiednie"] = "nie dotyczy"

    # --- wartosci zastepcze, gdy planu ogolnego nie odczytano ------------
    for klucz, zastepcza in (
        ("pog_strefa_nazwa", "…"),
        ("pog_strefa_oznaczenie", "…"),
        ("pog_profil_podstawowy", "…"),
        ("pog_profil_dodatkowy", "…"),
        ("pog_maks_nadz_intens", "nie określono"),
        ("pog_maks_udzial_pow_zab", "nie określono"),
        ("pog_maks_wysokosc", "nie określono"),
        ("pog_min_pbc", "nie określono"),
    ):
        if not str(context.get(klucz, "") or "").strip():
            context[klucz] = zastepcza

    context["pog_ostrzezenia"] = ostrzezenia
    return context
