# Template opisu dla GitHub Release

Skopiuj i dostosuj ten template podczas tworzenia Release na GitHubie.

---

## WZ Workflow v1.0.0

Pierwsza publiczna wersja wtyczki QGIS do automatycznej analizy warunków zabudowy w Polsce.

### 🎯 Główne funkcje

- ✅ **14-stopniowy zautomatyzowany workflow** analizy urbanistycznej
- ✅ **Klasyfikacja terenu ML** - rozpoznawanie typów dachów (płaski/dwuspadowy/jednospadowy/czterospadowy)
- ✅ **Analiza parametrów zabudowy** - automatyczne obliczanie WPZ, WIZ, WPBC
- ✅ **Przetwarzanie chmur punktów** - integracja z danymi LiDAR
- ✅ **Integracja z danymi katastralnymi** - działki i budynki z ULDK/BDOT
- ✅ **Generowanie raportów Word** - automatyczne tworzenie dokumentacji

### 📦 Instalacja

#### Przez QGIS Plugin Repository (zalecane)
```
QGIS → Wtyczki → Zarządzaj wtyczkami → Wyszukaj "WZ Workflow" → Zainstaluj
```

#### Ręczna instalacja
1. Pobierz `wz-workflow-1.0.0.zip` (poniżej)
2. W QGIS: Wtyczki → Zarządzaj wtyczkami → Zainstaluj z ZIP
3. Wybierz pobrany plik

### 📥 Modele uczenia maszynowego

**Modele są pobierane automatycznie przy pierwszym uruchomieniu wtyczki.**

Jeśli chcesz pobrać je ręcznie:

| Plik | Rozmiar | Opis |
|------|---------|------|
| `best_hex_model.pth` | 173 MB | Model PyTorch do klasyfikacji terenu (hexagony) |
| `ultimate_building_classifier_svm.pkl` | ~5 MB | Model SVM do klasyfikacji budynków |
| `scaler_hex.pkl` | <1 MB | Scaler dla modelu hexagonowego |

**Instalacja ręczna modeli:**
1. Pobierz pliki z sekcji Assets poniżej
2. Umieść w katalogu wtyczki:
   - Windows: `C:\Users\USERNAME\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\wz-workflow\`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/wz-workflow/`
   - Mac: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/wz-workflow/`

### 🚀 Szybki start

1. Załaduj warstwę działek katastralnych
2. Załaduj warstwę budynków
3. Uruchom: **Wtyczki → WZ Workflow**
4. Postępuj zgodnie z 14-stopniowym workflow
5. Wygeneruj raport analizy

### 📋 Wymagania

- QGIS 3.0 lub nowszy
- Python 3.7+
- Połączenie z internetem (przy pierwszym uruchomieniu - pobieranie modeli)

### 🔧 Zależności Python (instalowane automatycznie)

- PyTorch
- python-docx
- NumPy
- PDAL (opcjonalnie - dla przetwarzania chmur punktów)

### 🐛 Znane problemy

- Pierwsze uruchomienie wymaga czasu na pobranie modeli (~173 MB)
- Chmury punktów wymagają dużo pamięci RAM (zalecane min. 8 GB)

### 📝 Changelog

**v1.0.0** (2024-XX-XX)
- Pierwsza publiczna wersja
- Pełny 14-stopniowy workflow analizy WZ
- Automatyczne pobieranie modeli ML
- Klasyfikacja terenu (4 typy dachów)
- Klasyfikacja budynków
- Przetwarzanie chmur punktów LiDAR
- Automatyczne generowanie raportów Word
- Obliczanie wskaźników urbanistycznych

### 🆘 Wsparcie

- **Dokumentacja:** [README.md](https://github.com/TwojeRepo/wz-workflow#readme)
- **Zgłaszanie błędów:** [Issues](https://github.com/TwojeRepo/wz-workflow/issues)
- **Pytania:** [Discussions](https://github.com/TwojeRepo/wz-workflow/discussions)

### 📄 Licencja

[Twoja licencja, np. GPL-3.0]

### 👨‍💻 Autor

Adrian Linkowski

---

## Assets do dodania do Release:

1. ✅ `wz-workflow-1.0.0.zip` - Pełna wtyczka (BEZ modeli)
2. ✅ `best_hex_model.pth` - Model klasyfikacji terenu
3. ✅ `ultimate_building_classifier_svm.pkl` - Model SVM
4. ✅ `scaler_hex.pkl` - Scaler

**WAŻNE:** Po utworzeniu Release skopiuj dokładne URLe do plików i zaktualizuj je w `model_downloader.py`!

Przykładowy URL:
```
https://github.com/username/wz-workflow/releases/download/v1.0.0/best_hex_model.pth
```
