# Plan ogólny w WZ Workflow — co się zmieniło

## Pliki

| Plik | Status | Co robi |
|---|---|---|
| `plan_ogolny.py` | **NOWY** | odczyt strefy planistycznej z warstw APP 2.0 + automat wyborów |
| `improved_wz_workflow.py` | zmieniony | sekcja „🗺️ Plan ogólny gminy" w oknie *Dane działki przedmiotowej* (krok 13) |
| `generator_analiz_opisowych.py` | zmieniony | wywołanie automatu przed renderowaniem szablonu (krok 14) |
| `analizaWZ_szablony/analiza_wz_szablon 1_budynek_ostrow_POG_2026.docx` | **NOWY** | szablon dla jednego typu budynku |
| `analizaWZ_szablony/analiza_wz_szablon_multi_ostrow_POG_2026.docx` | **NOWY** | szablon dla wielu typów budynków |

Stare szablony zostają — nadal działają dla spraw wszczętych przed uchwaleniem
planu (generator dokłada zmienne `pog_*`, ale stary szablon ich po prostu nie używa).

## Wymagania w projekcie QGIS

Krok 13 przecina geometrię warstwy `granica_terenu` z warstwami planu ogólnego.
Muszą być wczytane (np. z `POG.qlr`):

- `StrefaPlanistyczna` — wymagana
- `ObszarUzupelnieniaZabudowy` — opcjonalna (bez niej OUZ = „nie")
- `ObszarZabudowySrodmiejskiej` — opcjonalna

Nazwy są dopasowywane trójstopniowo: dokładna nazwa → nazwa zawierająca wzorzec →
zestaw pól (`maksNadziemnaIntensywnoscZabudowy`). Zmiana nazwy warstwy w projekcie
nie psuje odczytu. Układ współrzędnych jest transformowany automatycznie.

Gdy działka leży w kilku strefach, przyjmowana jest strefa o **największym udziale
powierzchniowym**, a pozostałe trafiają do `pog_uwagi` i wyskakują jako ostrzeżenie
przy generowaniu dokumentu.

## Warianty „/" ze wzoru — jak zakodowane

### Rozstrzygane automatycznie (porównanie liczbowe)

| Miejsce we wzorze | Zmienna | Porównanie |
|---|---|---|
| maks. nadziemna intensywność | `pog_ocena_nadz_intens` | `maks_nadz_inten_zab_inw` ≤ `maksNadziemnaIntensywnoscZabudowy` |
| udział pow. zabudowy | `pog_ocena_udzial_pow_zab` | `Sredni_wpz` ≤ `maksUdzialPowierzchniZabudowy` |
| wysokość zabudowy | `pog_ocena_wysokosc` | max(`budynek.srWysZab`) ≤ `maksWysokoscZabudowy` |
| udział PBC | `pog_ocena_pbc` | `Sredni_wpbc` ≥ `minUdzialPowierzchniBiologicznieCzynnej` |
| OUZ | `pog_ouz_zdanie` | przecięcie z warstwą OUZ |
| obszar zabudowy śródmiejskiej | `pog_ozs_zdanie` | przecięcie z warstwą OZS |
| „występuje / nie występuje żadna zabudowa" | `obecne_zagospodarowanie` | jak dotąd — z combo w oknie |

Brzmienie fraz siedzi w jednym miejscu — słownik `FRAZY_ZGODNOSCI` w `plan_ogolny.py`:

```python
FRAZY_ZGODNOSCI = {
    "nadz_intens":     ("jest nie większa", "jest większa"),
    "udzial_pow_zab":  ("jest nie większy", "jest większy"),
    "wysokosc":        ("jest nie większa", "jest większa"),
    "pbc":             ("jest nie mniejszy", "jest mniejszy"),
}
```

Jeżeli któregoś parametru strefa nie określa (w Ostrowie np. cała strefa SK ma
wszystkie cztery puste, SO ma tylko PBC), automat **nie zgaduje** — wstawia wariant
zgodny i dokłada ostrzeżenie „brak danych do porównania…".

### Wybierane w oknie dialogowym

| Wybór | Zmienna | Domyślnie |
|---|---|---|
| § 2 ust. 2 / ust. 3 | `podstawa_ustalen` | ust. 2 |
| zgodność funkcji z profilem | `pog_zgodnosc_funkcji` | „mieści się" |
| § 3 ust. 1 / 2 / 3 (linia zabudowy) | `wyb_par3` | 1 |
| § 7 ust. 1-2 / 3 (wysokość) | `wyb_par7` | 1-2 |
| śr. wysokość na działkach sąsiednich | `sr_wys_dz_sasiednie` | „nie dotyczy" |

Wybór § 2 steruje **sześcioma** miejscami w dokumencie naraz, przez dwie zmienne
pochodne — wzór ma dwa różne brzmienia tej samej frazy:

- `zakres_wystepujaca` → „…występująca **w obszarze analizowanym na terenach
  o takiej samej funkcji jak wnioskowana**:" (intensywność, udział pow. zabudowy, PBC)
- `zakres_polozonej` → „…zabudowy **położonej w obszarze analizowanym**:"
  (szerokość elewacji, wysokość, geometria dachu)

## Dwie poprawki merytoryczne względem wzoru

1. **P60**: wzór mówi „**minimalny** udział powierzchni zabudowy określonej dla
   strefy". Plan ogólny definiuje wyłącznie `maksUdzialPowierzchniZabudowy`,
   a następne zdanie (P62) porównuje z „maksymalnym". W szablonie jest
   „maksymalny".

2. **P89**: wzór mówi „minimalny udział PBC ustalony dla inwestycji **jest nie
   większy / jest większy** niż minimalny udział PBC dla strefy". Zgodność
   z planem wymaga, żeby był **nie mniejszy** — to wygląda na kopiuj-wklej
   z akapitów o intensywności. Automat porównuje `≥` i wstawia „jest nie
   mniejszy". Jeśli gmina upiera się przy oryginale, zmieniasz jedną krotkę
   w `FRAZY_ZGODNOSCI`.

Dodatkowo poprawiona literówka odziedziczona ze starego szablonu:
`{{budynek.kalenicaProj}}m do frontu działki` → `{{budynek.kalenicaProj}} do frontu działki`.

## Odmiana nazw stref

Wzór ma „znajduje się w strefie planistycznej …" i „dla strefy … oznaczonej
symbolem …". W obu miejscach potrzebna jest ta sama forma (miejscownik
i dopełniacz rodzaju żeńskiego są tu identyczne), więc `pog_strefa_nazwa`
przechowuje formę odmienioną: *„wielofunkcyjnej z zabudową mieszkaniową
jednorodzinną"*. Mianownik siedzi w `pog_strefa_nazwa_mian` i jest używany
w oknie dialogowym oraz w arkuszu `dane_dzialki`.

## Sprawy sprzed uchwalenia planu ogólnego

Stare szablony działają bez zmian. Generator sam rozpoznaje, który szablon
wybrałeś — sprawdza, czy `word/document.xml` zawiera placeholdery `pog_*`
(funkcja `szablon_uzywa_planu_ogolnego`):

- **stary szablon** → w konsoli leci tylko notka „wybrano szablon sprzed planu
  ogólnego"; żadnych okienek, żadnych ostrzeżeń, dokument jak dotąd;
- **szablon POG** → pełny raport porównań w konsoli, a gdy czegoś brakuje —
  jedno okno zbiorcze z listą kwestii do sprawdzenia.

Sekcję „🗺️ Plan ogólny" w oknie danych działki możesz przy takich sprawach
zignorować. Nic się nie zepsuje:

- brak warstw planu w projekcie → sekcja pokaże „⚠️ Nie odczytano strefy
  planistycznej", `pog_dostepny = nie`, reszta pól `pog_*` zostanie pusta;
- combosy zapiszą wartości domyślne (§ 2 ust. 2, § 3 ust. 1, § 7 ust. 1-2,
  „mieści się") — trafią do `do_eksportu`, ale stary szablon ich nie czyta;
- automat porównań nie zgaduje przy braku danych — wstawia wariant zgodny
  i odnotowuje „brak danych do porównania…", co przy starym szablonie nigdzie
  nie wypływa.

Jedyny scenariusz, w którym zobaczysz głośne ostrzeżenie, to **szablon POG bez
odczytanej strefy** — wtedy w dokumencie zostałyby wielokropki, więc generator
mówi o tym wprost.

## Znane ograniczenie

W szablonie **multi** wiersz „średnia wysokość zabudowy na działkach sąsiednich"
znalazł się wewnątrz pętli `{% for budynek in budynki %}` — przy dwóch typach
budynków powtórzy się dwa razy. Wyciągnięcie go poza pętlę psuje kolejność
względem „§ 7 … ustala się", więc zostawiłem. Przy jednym typie budynku problemu
nie ma; pole i tak domyślnie ma wartość „nie dotyczy".

## Wdrożenie

Skopiuj cztery pliki do katalogu wtyczki (`plan_ogolny.py`,
`improved_wz_workflow.py`, `generator_analiz_opisowych.py` oraz oba szablony do
`analizaWZ_szablony/`), przeładuj wtyczkę (Plugin Reloader lub restart QGIS).
Nie trzeba nic rejestrować — `plan_ogolny.py` jest importowany leniwie, a przy
uruchomieniu przez `runpy` ładuje się po ścieżce z `SCRIPTS_PATH`.
