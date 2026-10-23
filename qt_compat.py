# -*- coding: utf-8 -*-
"""
qt_compat.py — warstwa zgodnosci Qt5 (QGIS 3) / Qt6 (QGIS 4).

PROBLEM
-------
W Qt6 usunieto stale typow z QVariant:
    QVariant.Int, QVariant.Double, QVariant.String, ...  →  NIE ISTNIEJA
Ich odpowiedniki zyja teraz w QMetaType.Type:
    QMetaType.Type.Int, QMetaType.Type.Double, QMetaType.Type.QString, ...

Wtyczka uzywa QVariant.X w ~100 miejscach (definicje pol QgsField).

DLACZEGO LATKA, A NIE PRZEPISANIE KODU
--------------------------------------
Kuszace bylo zamienic QVariant.Int → QMetaType.Type.Int w calym kodzie.
ALE: konstruktor QgsField przyjmujacy QMetaType pojawil sie dopiero
w QGIS 3.38. W QGIS 3.34 LTR (wciaz szeroko uzywanym) QgsField oczekuje
QVariant.Type i odrzucilby QMetaType.

Dlatego:
  • pod Qt5 (QGIS 3)  — zostawiamy oryginalne QVariant.X  → dziala wszedzie
  • pod Qt6 (QGIS 4)  — przywracamy te nazwy, mapujac je na QMetaType.Type,
                         czyli dokladnie to, czego QGIS 4 oczekuje

Efekt: kod wtyczki pozostaje bez zmian, a dziala w obu swiatach.

UZYCIE
------
Zaimportuj RAZ, przy starcie wtyczki (wz_workflow_plugin.py):

    from .qt_compat import patch_qvariant
    patch_qvariant()

QVariant to obiekt klasy wspoldzielony w calym procesie Pythona, wiec
jedno wywolanie zalatwia sprawe we wszystkich skryptach krokow.
"""

from qgis.PyQt.QtCore import QVariant

# QVariant.X  →  QMetaType.Type.Y   (uwaga: String → QString, Date → QDate)
_TYPE_MAP = {
    "Int":        "Int",
    "UInt":       "UInt",
    "LongLong":   "LongLong",
    "ULongLong":  "ULongLong",
    "Double":     "Double",
    "Bool":       "Bool",
    "String":     "QString",
    "StringList": "QStringList",
    "Date":       "QDate",
    "Time":       "QTime",
    "DateTime":   "QDateTime",
    "ByteArray":  "QByteArray",
}


def patch_qvariant():
    """
    Pod Qt6 przywraca QVariant.Int, QVariant.String itd., mapujac je
    na odpowiedniki z QMetaType.Type.

    Pod Qt5 nie robi nic (stale juz istnieja).
    Jesli QGIS sam kiedys doda te stale — tez nie robi nic.
    """
    if hasattr(QVariant, "Int"):
        return False          # Qt5 albo juz zalatane

    try:
        from qgis.PyQt.QtCore import QMetaType
    except ImportError:
        return False

    patched = 0
    for old_name, meta_name in _TYPE_MAP.items():
        if hasattr(QVariant, old_name):
            continue
        meta_member = getattr(QMetaType.Type, meta_name, None)
        if meta_member is None:
            continue
        # KLUCZOWE: bierzemy WARTOSC LICZBOWA enuma (.value), a nie sam obiekt
        # enuma. W PyQt5 QVariant.Double bylo liczba 6; QgsField i inne API
        # QGIS oczekuja tej liczby. Podstawienie obiektu QMetaType.Type.Double
        # powoduje, ze pola typu double sa zle interpretowane i odrzucaja
        # wartosci (np. "Could not convert 1.0 to double").
        try:
            value = meta_member.value      # int, np. Double → 6
        except AttributeError:
            value = int(meta_member)
        try:
            setattr(QVariant, old_name, value)
            patched += 1
        except (AttributeError, TypeError):
            pass  # nosec B110 - jesli SIP nie pozwala, trudno; zglosi sie dalej

    return patched > 0
