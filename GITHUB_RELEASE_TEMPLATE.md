# Template opisu dla GitHub Release

Skopiuj i dostosuj przy tworzeniu Release na GitHubie.

---

## WZ Workflow v2.1.0

Zgodnosc z Qt6 / QGIS 4 oraz utrwalenie zmian z serii 2.0.x.

### 🔧 Zgodnosc z QGIS 4 (Qt6)

- Importy PyQt przechodza przez warstwe zgodnosci `qgis.PyQt` (dziala na Qt5 i Qt6)
- Wszystkie enumy Qt i QGIS w pelnej formie (wymagane przez PyQt6, poprawne w PyQt5)
- `exec_()` zastapione przez `exec()`
- **Brak zmian funkcjonalnych** — wtyczka nadal dziala na QGIS 3

### 🔒 Bezpieczenstwo (z 2.0.1–2.0.3)

- Skrypty krokow uruchamiane standardowym mechanizmem `runpy` zamiast `exec()`
- Pobieranie modeli waliduje schemat i host URL, pobiera strumieniowo
- Usunieta automatyczna instalacja pakietow przez powloke — brakujace zaleznosci
  zglaszaja teraz czytelny komunikat

---

Wersja 2.0.0 wprowadzila przebudowany klasyfikator PBC (Random Forest)
oraz nowy model rozpoznawania ksztaltu dachow (CNN).

### 🌿 Nowy klasyfikator PBC (Random Forest)

- **Las losowy** zastępuje wcześniejsze podejście SVM / MLP
- **13 klas pokrycia terenu** odzwierciedlających realia analiz WZ (trawnik zadbany,
  roślinność ruderalna, pole uprawne, zaorane pole, droga gruntowa, asfalt, beton,
  kostka czerwona i niebieska, kort, powierzchnie zacienione)
- **28 cech**: chromatyczność, indeksy spektralne (GRI/GBI/RBI), surowa intensywność
  odbicia, jasność oraz geometria sąsiedztwa (planarność, chropowatość, jednorodność otoczenia)
- **Konfigurowalny próg decyzyjny** — w razie niepewności model przechyla się na stronę
  bezpieczniejszą, zamiast zawyżać wskaźnik
- Warstwa wynikowa zawiera **prawdopodobieństwo decyzji** (`p_pbc`), co pozwala obejrzeć
  obszary o najniższej pewności i zweryfikować je ręcznie

### 🏠 Nowy model dachów (CNN)

Klasyfikacja kształtu dachu siecią **EfficientNetV2** (płaski / dwuspadowy / jednospadowy /
czterospadowy), zastępująca wcześniejszy klasyfikator.

### ⚡ Pozostałe zmiany

- Przetwarzanie bardzo dużych chmur LiDAR bez przepełnienia pamięci (praca per działka)
- Ustabilizowane skrypty wewnętrzne
- Nowa ikona wtyczki

---

### 📦 Instalacja

#### Przez QGIS Plugin Repository (zalecane)
```
QGIS → Wtyczki → Zarządzaj wtyczkami → Wyszukaj "WZ Workflow" → Zainstaluj
```

#### Ręczna instalacja
1. Pobierz `wz_workflow_plugin_for_REPO-2.1.0.zip` (poniżej, w sekcji Assets)
2. W QGIS: **Wtyczki → Zarządzaj wtyczkami → Zainstaluj z ZIP**
3. Wskaż pobrany plik

---

### 📥 Modele uczenia maszynowego

**Modele pobierają się automatycznie przy pierwszym uruchomieniu wtyczki.**
Ze względu na rozmiar nie są dołączone do paczki ZIP.

| Plik | Rozmiar | Opis |
|------|---------|------|
| `rf_pbc_ostrow.pkl` | ~179 MB | Klasyfikator PBC (Random Forest, 13 klas, 28 cech) |
| `best_dachy_efficient.weights.h5` | ~39 MB | Klasyfikator kształtu dachu (CNN, EfficientNetV2) |

**Instalacja ręczna modeli** (gdy automatyczne pobieranie zawiedzie):

1. Pobierz oba pliki z sekcji **Assets** poniżej
2. Umieść je bezpośrednio w katalogu wtyczki:
   - **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/wz_workflow/`
   - **Windows:** `C:\Users\USERNAME\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\wz_workflow\`
   - **macOS:** `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/wz_workflow/`

---

### 📋 Wymagania

- QGIS 3.0 lub nowszy
- Python 3.9+
- Połączenie z internetem przy pierwszym uruchomieniu (pobieranie modeli)
- Zalecane min. 8 GB RAM (przetwarzanie chmur punktów)

### 🔧 Zależności Python

- scikit-learn, joblib (klasyfikator PBC)
- TensorFlow / Keras (klasyfikator dachów)
- scipy, numpy, pandas
- python-docx (raporty)
- PDAL (opcjonalnie — przetwarzanie chmur punktów)

### 🐛 Znane ograniczenia

- Model PBC wytrenowano na danych z **jednego obszaru** (Ostrów Wielkopolski).
  Na nalotach o innej kalibracji sensora dokładność może być niższa — planowana jest
  możliwość samodzielnego dotrenowania modelu na własnym regionie.
- Najtrudniejsze do rozróżnienia pary to **beton ↔ droga gruntowa** oraz powierzchnie
  w cieniu. Warstwa `p_pbc` pozwala wychwycić takie przypadki.
- Pierwsze uruchomienie wymaga pobrania ~218 MB modeli.

---

### 🆘 Wsparcie

- **Dokumentacja:** [README.md](https://github.com/AdrLin/wz-workflow#readme)
- **Zgłaszanie błędów:** [Issues](https://github.com/AdrLin/wz-workflow/issues)

### 📄 Licencja

GPL-3.0

### 👨‍💻 Autor

Adrian Linkowski

---

## ✅ Checklista Assets do dodania do Release

1. `wz_workflow_plugin_for_REPO-2.1.0.zip` — wtyczka **BEZ modeli** (~370 KB)

Modeli **NIE dodajesz ponownie** — sa juz w Release v2.0.0 i downloader z nich korzysta.
NIE USUWAJ Release v2.0.0, bo wtyczka przestanie pobierac modele!

**⚠️ UWAGA — modele zostaja pod tagiem v2.0.0:**

Modele (`rf_pbc_ostrow.pkl`, `best_dachy_efficient.weights.h5`) sa juz opublikowane
jako assety Release **v2.0.0** i sie NIE zmienily. `model_downloader.py` celowo
nadal na nie wskazuje:

```python
GITHUB_RELEASE_URL = "https://github.com/AdrLin/wz-workflow/releases/download/v2.0.0/"
```

Po opublikowaniu Release sprawdź, czy pliki są pobieralne:
```
https://github.com/AdrLin/wz-workflow/releases/download/v2.0.0/rf_pbc_ostrow.pkl
https://github.com/AdrLin/wz-workflow/releases/download/v2.0.0/best_dachy_efficient.weights.h5
```
