#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Ciezkie biblioteki — czytelny komunikat zamiast surowego bledu importu.
try:
    import pandas as pd
    import numpy as np
except ImportError as _exc:
    raise ImportError(
        "Ten krok wymaga bibliotek naukowych (numpy/pandas/scipy). "
        "Zainstaluj je w srodowisku Pythona QGIS:  "
        "python3 -m pip install numpy pandas scipy scikit-learn joblib\n"
        f"Szczegoly: {_exc}"
    ) from _exc

"""
headless_classifier.py  —  WERSJA PRZENOŚNA (odbudowa architektury + wagi)
=========================================================================
Predyktor uruchamiany w tle przez przygotuj_dachy_do_klasyfikacji.py:

    python headless_classifier.py <project_path>

Zamiast ładować pełny .keras (przywiązany do wersji Keras, jaką go zapisano),
ODBUDOWUJE architekturę w kodzie i wczytuje WAGI (.weights.h5). Wagi to czyste
tablice — ładują się na dowolnym Kerasie 3.x, więc wtyczka działa u każdego
użytkownika niezależnie od jego wersji Keras/Pythona (zweryfikowane: wagi z
Keras 3.14.1 wczytują się pod 3.12.2).

Model: EfficientNetV2B0 (include_preprocessing=True) + głowa
       GAP -> Dropout(0.3) -> Dense(128, relu) -> Dropout(0.4) -> Dense(5, softmax)

Czyta turbo-PNG 96x96 z <projekt>/prediction_data/, predykuje i zapisuje
building_predictions.csv (ID_BUDYNKU, PREDYKCJA, PEWNOSC) w tym samym katalogu.

NIE importuje qgis — może działać pod dowolnym Pythonem z TensorFlow/Keras.
Wymaga: tensorflow/keras, numpy, pillow, pandas.
"""
import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from pathlib import Path
from PIL import Image

SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# KONFIGURACJA
# ============================================================
WEIGHTS_NAME = "best_dachy_efficient.weights.h5"   # wagi w folderze wtyczki
IMG = 96                                            # rozmiar wejścia modelu

# Baza EfficientNetV2B0 ma include_preprocessing=True (wewnętrzny Rescaling 1/255
# + Normalization ImageNet), więc model przyjmuje SUROWE [0,255]. Nie normalizujemy
# tutaj -> RESCALE=False. (Gdyby kiedyś podmienić na model bez preprocessingu, ustaw True.)
RESCALE = False

# Kolejność klas = train_generator.class_indices (alfabetyczna, foldery ASCII).
CLASS_NAMES = ["czterospadowy", "dwuspadowy", "jednospadowy", "plaski", "wielospadowy"]

# Mapowanie nazw modelu -> kategorie wtyczki (różni się tylko 'plaski' -> 'płaski')
DO_KATEGORII = {
    "czterospadowy": "czterospadowy",
    "dwuspadowy":    "dwuspadowy",
    "jednospadowy":  "jednospadowy",
    "plaski":        "płaski",
    "wielospadowy":  "wielospadowy",
}
BATCH = 32
# ============================================================

if len(sys.argv) > 1:
    project_path = sys.argv[1]
    project_directory = os.path.dirname(project_path)
else:
    print("⚠️ Nie podano ścieżki projektu jako argumentu. Używam katalogu roboczego.")
    project_directory = os.getcwd()

OUTPUT_DIR   = str(Path(project_directory) / "prediction_data")
WEIGHTS_PATH = os.path.join(SCRIPTS_PATH, WEIGHTS_NAME)


def build_roof_model():
    """
    Odbudowuje architekturę 1:1 z wytrenowanej sieci (EfficientNetV2B0 + głowa).
    weights=None -> nie pobiera wag ImageNet; wszystkie wagi (baza + głowa) wczytujemy
    z .weights.h5. include_preprocessing=True -> baza sama robi Rescaling+Normalization,
    więc karmimy ją surowym [0,255]. Współczynniki Dropout nie wpływają na inferencję
    ani na kształt wag.
    """
    import keras
    from keras.applications import EfficientNetV2B0
    from keras.layers import GlobalAveragePooling2D, Dropout, Dense
    base = EfficientNetV2B0(include_top=False, weights=None,
                            input_shape=(IMG, IMG, 3), include_preprocessing=True)
    model = keras.Sequential([
        keras.Input((IMG, IMG, 3)),
        base,
        GlobalAveragePooling2D(),
        Dropout(0.3),
        Dense(128, activation="relu"),
        Dropout(0.4),
        Dense(len(CLASS_NAMES), activation="softmax"),
    ])
    return model


def load_image(path):
    """Wczytuje turbo-PNG jako tablicę [0,255] float32 (normalizacja niżej, wg RESCALE)."""
    img = Image.open(path).convert("RGB")
    if img.size != (IMG, IMG):
        img = img.resize((IMG, IMG), Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.float32)


def atomic_to_csv(df, path):
    """Zapis do pliku tymczasowego i podmiana — wait_for_file() w QGIS nie złapie połówki."""
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False, encoding="utf-8")
    os.replace(tmp, path)


def main():
    if not os.path.isdir(OUTPUT_DIR):
        raise FileNotFoundError(f"Katalog nie istnieje: {OUTPUT_DIR}")

    pngs = sorted(f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".png"))
    if not pngs:
        print(f"Nie znaleziono plików PNG w {OUTPUT_DIR}")
        return

    print(f"Znaleziono {len(pngs)} plików PNG")
    ids = [os.path.splitext(f)[0] for f in pngs]
    X = np.stack([load_image(os.path.join(OUTPUT_DIR, f)) for f in pngs]).astype(np.float32)
    if RESCALE:
        X = X / 255.0

    print(f"Buduję architekturę (EfficientNetV2B0) i wczytuję wagi: {WEIGHTS_PATH}")
    model = build_roof_model()
    model.load_weights(WEIGHTS_PATH)

    probs = model.predict(X, batch_size=BATCH, verbose=0)
    cls = probs.argmax(axis=1)
    conf = probs.max(axis=1)

    rows = []
    for bid, fname, c, p, pr in zip(ids, pngs, cls, conf, probs):
        row = {
            "ID_BUDYNKU": bid,
            "PREDYKCJA": DO_KATEGORII[CLASS_NAMES[c]],
            "PEWNOSC": round(float(p), 4),
            "PLIK": fname,
        }
        for k, name in enumerate(CLASS_NAMES):
            row[f"PROB_{DO_KATEGORII[name].upper()}"] = round(float(pr[k]), 4)
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("ID_BUDYNKU")
    out_csv = os.path.join(OUTPUT_DIR, "building_predictions.csv")
    atomic_to_csv(df, out_csv)

    print(f"\n{'='*50}")
    print("PODSUMOWANIE PREDYKCJI (EfficientNetV2B0)")
    print(f"{'='*50}")
    print(f"Przetworzono: {len(df)}  ->  {out_csv}")
    for k, n in df["PREDYKCJA"].value_counts().items():
        print(f"  {k:16s} {n}")
    print(f"Średnia pewność: {df['PEWNOSC'].mean():.3f}")


if __name__ == "__main__":
    main()
