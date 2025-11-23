# WZ Workflow - QGIS Plugin

[![QGIS](https://img.shields.io/badge/QGIS-3.0+-green.svg)](https://qgis.org)
[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-GPL--3.0-orange.svg)](LICENSE)

> Kompleksowe narzędzie do automatycznej analizy **warunków zabudowy (WZ)** w Polsce  
> Comprehensive tool for Polish urban planning analysis (Building Permit Conditions)

---

## 🎯 Co to jest?

**WZ Workflow** to wtyczka QGIS automatyzująca proces analizy warunków zabudowy w Polsce. Wykorzystuje uczenie maszynowe do klasyfikacji terenu i budynków, integruje dane katastralne, przetwarza chmury punktów LiDAR i generuje profesjonalne raporty.

### Dla kogo?

- 🏗️ **Urbaniści** - automatyczna analiza zgodności z planem zagospodarowania
- 📐 **Projektanci** - szybka ocena parametrów zabudowy
- 🏛️ **Urzędy** - standaryzacja procesu wydawania WZ
- 🎓 **Studenci** - narzędzie edukacyjne do planowania przestrzennego

---

## ✨ Funkcje

### 🤖 Automatyzacja
- ✅ **14-stopniowy workflow** - pełna automatyzacja analizy
- ✅ **Inteligentna klasyfikacja** - ML rozpoznaje typy budynków i dachów
- ✅ **Przetwarzanie LiDAR** - automatyczna ekstrakcja parametrów z chmur punktów
- ✅ **Generowanie raportów** - export do Word z mapami i tabelami

### 📊 Analiza terenu
- Klasyfikacja typów dachów: płaski / dwuspadowy / jednospadowy / czterospadowy
- Wykrywanie granic działek i budynków
- Obliczanie odległości od granic
- Analiza wysokości z chmur punktów

### 🔢 Wskaźniki urbanistyczne
- **WPZ** - Wskaźnik powierzchni zabudowy
- **WIZ** - Wskaźnik intensywności zabudowy
- **WPBC** - Wskaźnik powierzchni biologicznie czynnej
- Automatyczne sprawdzanie zgodności z przepisami

---

## 📦 Instalacja

### Przez QGIS Plugin Repository (ZALECANE)

1. Otwórz QGIS
2. Menu: **Wtyczki → Zarządzaj wtyczkami**
3. Zakładka: **Wszystkie**
4. Wyszukaj: `WZ Workflow`
5. Kliknij: **Zainstaluj wtyczkę**

**Przy pierwszym uruchomieniu** wtyczka automatycznie pobierze modele ML (~173 MB).

### Ręczna instalacja

```bash
# 1. Pobierz najnowszą wersję z Releases
# 2. Rozpakuj do katalogu wtyczek QGIS:

# Linux:
~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/

# Windows:
C:\Users\USERNAME\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\

# Mac:
~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/

# 3. Uruchom ponownie QGIS
```

---

## 🚀 Szybki start

### 1. Przygotuj dane

Potrzebujesz:
- 📍 Warstwa działek (polygon) - z ULDK lub BDOT
- 🏠 Warstwa budynków (polygon) - z ULDK lub BDOT
- ☁️ Chmura punktów LiDAR - format LAZ/LAS

### 2. Uruchom workflow

```
Menu QGIS → Wtyczki → WZ Workflow
```

Postępuj zgodnie z 14 krokami workflow.

### 3. Wyniki

Otrzymasz:
- 📊 Raport Word z analizą
- 🗺️ Warstwy GIS z wynikami
- 📈 Tabele z parametrami

---

## 📋 Wymagania

- **QGIS:** 3.0 lub nowszy
- **Python:** 3.7+
- **RAM:** min. 8 GB (zalecane dla chmur punktów)
- **Dysk:** ~500 MB (wtyczka + modele)

### Zależności Python (instalowane automatycznie)
- PyTorch, python-docx, numpy, scikit-learn

---

## 🐛 Zgłaszanie błędów

Znalazłeś błąd? [Utwórz issue](https://github.com/AdrLin/wz-workflow/issues/new)

---

## 📄 Licencja

GNU GPL v3.0 - szczegóły w [LICENSE](LICENSE)

---

## 👨‍💻 Autor

**Adrian Linkowski**
- 📧 Email: link.mapy@gmail.com
- 🐙 GitHub: [@TwojeUsername](https://github.com/AdrLin)

---

<p align="center">
  Wykonane z ❤️ dla polskiej społeczności GIS
</p>
