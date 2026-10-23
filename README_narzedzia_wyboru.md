# Narzędzia liczące z zaznaczenia na mapie

## Pliki

| Plik | Status | Gdzie wgrać |
|---|---|---|
| `narzedzia_wyboru.py` | **NOWY** | katalog wtyczki |
| `improved_wz_workflow.py` | zmieniony | katalog wtyczki |
| `output_and_results_unified.py` | zmieniony | katalog wtyczki |
| `plan_ogolny.py` | zmieniony | katalog wtyczki |
| `analizaWZ_szablony/analiza_wz_szablon 1_budynek_ostrow_POG_2026.docx` | zmieniony | `analizaWZ_szablony/` |
| `analizaWZ_szablony/analiza_wz_szablon_multi_ostrow_POG_2026.docx` | zmieniony | `analizaWZ_szablony/` |
| `Szablony_decyzji/decyzja_standardowa_POG_szablon_ostrow26.docx` | zmieniony | folder szablonów decyzji |
| `wz_decision_app.py` | zmieniony | katalog aplikacji decyzji |

`output_and_results_unified.py` zawiera też poprzednią zmianę (listy parametrów
budynków zamiast średnich).

---

## Naprawiony błąd

Pole średniej wysokości było aktywne tylko przy § 7 ust. 3. Blokada usunięta —
pole jest dostępne zawsze, a `on_par7_changed()` przestało być potrzebne
i zostało wyrzucone.

## Narzędzie 1 — średnia wysokość z działek sąsiednich

Warstwa `budynki_parametry`, pole `wysokosc` (z fallbackiem na `wysokość`,
`wys_zab`, `wysokosc_bud`, `height`).

1. **Zaznacz na mapie** — ustawia warstwę jako aktywną, czyści poprzednie
   zaznaczenie i włącza narzędzie zaznaczania QGIS.
2. Klikasz budynki (Ctrl = dokładanie).
3. **Policz średnią** — wpisuje wynik do pola i pokazuje pod spodem, z ilu
   budynków i z jakich wysokości powstał.

Budynki bez wypełnionej wysokości są pomijane i zliczane osobno. Gdy zaznaczysz
liczbę inną niż dwa, dostajesz przypomnienie, że przepis mówi o przylegających
działkach sąsiednich dostępnych z tej samej drogi — ale liczenie nie jest
blokowane. Pole zostaje edytowalne, więc możesz nadpisać wynik ręcznie.

Zapisywane klucze: `sr_wys_dz_sasiednie`, `sr_wys_dz_sasiednie_lista`.

## Narzędzie 2 — linia zabudowy z dwóch działek sąsiednich

Warstwa `linie_zabudowy`, pole `distance`.

Po zaznaczeniu dwóch linii i kliknięciu **Porównaj**:

- różnica ≤ **0,10 m** → § 3 **ust. 1**, combo przestawia się samo,
- różnica > 0,10 m → § 3 **ust. 2**,
- jako ustaloną linię zabudowy przyjmowana jest **większa** z odległości.

Tolerancja siedzi w `TOLERANCJA_LZ_M` na górze `narzedzia_wyboru.py` — linie
obrysowujesz ręcznie z mapy, więc kilka centymetrów to szum pomiaru, nie
faktyczna różnica w usytuowaniu zabudowy. Jeśli to za dużo albo za mało, to
jedna liczba do zmiany.

Zapisywane klucze: `Lz_ustalona`, `Lz_sasiednie_lista`, `Lz_sasiednie_rowne`,
plus `wyb_par3` ustawiane automatycznie.

**Czego narzędzie nie robi:** nie ustawia `rodzaj_Lz` (obowiązująca /
nieprzekraczalna). Nie znam treści § 3 rozporządzenia na tyle pewnie, żeby
zakodować przełożenie ustępu na rodzaj linii, a zgadywanie w projekcie decyzji
to zły pomysł. Combo zostaje po Twojej stronie — jeśli podasz mi regułę,
dopnę to jedną linijką.

---

## Nowe klucze zamiast nadpisywania starych

`Lz_max` i `srWysZab` występują w analizie **dwa razy każdy** — raz jako opis
obszaru analizowanego, raz w zdaniu „ustala się". Nadpisanie ich wartością
z narzędzia zepsułoby pierwsze zdanie, więc doszły osobne klucze:

| zdanie w analizie | placeholder |
|---|---|
| linie zabudowy w odległościach od … do … | `{{Lz_min}}` / `{{Lz_max}}` (bez zmian) |
| ustala się … linię zabudowy w odległości … | `{{Lz_ustalona}}` |
| średnia wysokość zabudowy w obszarze analizowanym | `{{budynek.srWysZab}}` (bez zmian) |
| ustala się wysokość zabudowy … do … | `{{budynek.wys_ustalona}}` |

## Maksymalna ustalona wysokość

`wys_ustalona_{suffix}` liczy się w `create_results()`: **średnia z działek
sąsiednich**, a gdy jej nie policzono — średnia z całego obszaru. Do arkusza
trafia też `wys_ustalona_zrodlo_{suffix}` („działki sąsiednie" / „obszar
analizowany"), żeby po fakcie było widać, skąd wzięła się liczba. W konsoli
QGIS leci komunikat przy każdym uruchomieniu kroku 14.

Test na danych syntetycznych (budynki 6,0 m i 8,0 m, średnia obszaru 7,0 m):

```
narzędzie użyte      wys_ustalona_x = 9.2 m   źródło: działki sąsiednie
narzędzie nieużyte   wys_ustalona_x = 7.0 m   źródło: obszar analizowany
```

## Zgodność wsteczna

Trzy poziomy fallbacku, żeby stare sprawy działały bez zmian:

- `plan_ogolny.uzupelnij_wybory()` — `Lz_ustalona` pusta → bierze `Lz_max`;
  `budynek.wys_ustalona` pusta → bierze `srWysZab`;
- `create_results()` — brak `sr_wys_dz_sasiednie` w danych działki → średnia
  z obszaru;
- `wz_decision_app.py` — słownik `ZAMIENNIKI_KLUCZY` mapuje `Lz_ustalona → Lz_max`
  i `wys_ustalona → srWysZab` przy czytaniu starych arkuszy.

Stare szablony (bez `_POG_`) używają `Lz_max` i `srWysZab`, więc renderują się
jak dotąd.

Sprawdzone renderowaniem obu szablonów analizy w dwóch wariantach:

```
narzędzia UŻYTE:      ustala się ... linię zabudowy w odległości 7,30 m
                      ustala się wysokość zabudowy na poziomie od 3.0 m do 9,20 m
narzędzia NIEUŻYTE:   Lz_ustalona -> 9,80 m (z Lz_max)
                      budynek.wys_ustalona -> 7,63 m (z srWysZab)
```

Testy jednostkowe obu narzędzi przeszły dla: dwóch budynków, budynku bez
wysokości, pustego zaznaczenia, braku warstwy, linii równych, równych
w tolerancji, różnych, trzech linii i jednej linii.
