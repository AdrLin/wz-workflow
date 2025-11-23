#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jul 30 11:42:20 2025
@author: adrian
Klasyfikacja pokrycia terenu z wykorzystaniem klasteryzacji heksagonalnej
"""
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import pickle
import time
from collections import defaultdict
import math

# Optymalizacja dla słabszego sprzętu
torch.set_num_threads(4)

# === Parametry ===
INPUT_FEATURES = ['Z', 'Intensity', 'ReturnNumber', 'NumberOfReturns', 'Red', 'Green', 'Blue']
CSV_PATH = "training_data.csv"
MODEL_PATH = "terrain_model.pt"
SCALER_PATH = "scaler_params.npz"
HEX_SIZE = 1.0  # Średnica heksagonu w metrach

def hex_grid_coordinates(x, y, hex_size):
    """
    Konwertuje współrzędne kartezjańskie na współrzędne siatki heksagonalnej
    """
    # Wysokość heksagonu
    hex_height = hex_size * math.sqrt(3) / 2
    
    # Konwersja do współrzędnych heksagonalnych
    q = (2/3 * x) / hex_size
    r = (-1/3 * x + math.sqrt(3)/3 * y) / hex_size
    
    # Zaokrąglenie do najbliższego heksagonu
    q_round = round(q)
    r_round = round(r)
    s_round = round(-q - r)
    
    # Korekcja zaokrągleń (suma q+r+s musi być 0)
    q_diff = abs(q_round - q)
    r_diff = abs(r_round - r)
    s_diff = abs(s_round - (-q - r))
    
    if q_diff > r_diff and q_diff > s_diff:
        q_round = -r_round - s_round
    elif r_diff > s_diff:
        r_round = -q_round - s_round
    else:
        s_round = -q_round - r_round
    
    return (q_round, r_round)

def create_hexagon_features(points_data):
    """
    Grupuje punkty w heksagony i tworzy cechy dla każdego heksagonu
    """
    hex_groups = defaultdict(list)
    
    # Grupowanie punktów według współrzędnych heksagonalnych
    print("🔄 Grupowanie punktów w heksagony...")
    for idx, row in points_data.iterrows():
        hex_coord = hex_grid_coordinates(row['X'], row['Y'], HEX_SIZE)
        hex_groups[hex_coord].append(row)
    
    print(f"📊 Utworzono {len(hex_groups)} heksagonów z {len(points_data)} punktów")
    
    # Tworzenie cech dla każdego heksagonu
    hex_features = []
    hex_labels = []
    
    for hex_coord, points in hex_groups.items():
        if len(points) < 3:  # Pomijamy heksagony z małą liczbą punktów
            continue
            
        points_df = pd.DataFrame(points)
        
        # Podstawowe statystyki dla każdej cechy
        features = []
        
        for feature in INPUT_FEATURES:
            values = points_df[feature].values
            # Zabezpieczenie przed NaN
            if len(values) > 0:
                features.extend([
                    np.mean(values),      # średnia
                    np.std(values) if len(values) > 1 else 0.0,       # odchylenie standardowe
                    np.min(values),       # minimum
                    np.max(values),       # maksimum
                    np.percentile(values, 25),  # kwartyl dolny
                    np.percentile(values, 75),  # kwartyl górny
                ])
            else:
                features.extend([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # domyślne wartości
        
        # Dodatkowe cechy przestrzenne
        features.extend([
            len(points),  # liczba punktów w heksagonie
            points_df['Z'].max() - points_df['Z'].min(),  # różnica wysokości
            np.std(points_df['Z']),  # szorstkość powierzchni (std wysokości)
        ])
        
        # Cechy dotyczące zwrotów lasera
        if 'ReturnNumber' in points_df.columns and 'NumberOfReturns' in points_df.columns:
            # Proporcja pierwszych zwrotów
            first_returns = (points_df['ReturnNumber'] == 1).sum()
            features.append(first_returns / len(points))
            
            # Proporcja ostatnich zwrotów
            last_returns = (points_df['ReturnNumber'] == points_df['NumberOfReturns']).sum()
            features.append(last_returns / len(points))
            
            # Średnia liczba zwrotów
            features.append(points_df['NumberOfReturns'].mean())
        
        # Cechy kolorystyczne (jeśli dostępne)
        if all(col in points_df.columns for col in ['Red', 'Green', 'Blue']):
            # Normalized Difference Vegetation Index (NDVI-like)
            # Używamy Green-Red zamiast NIR-Red
            ndvi_like = (points_df['Green'] - points_df['Red']) / (points_df['Green'] + points_df['Red'] + 1e-8)
            features.extend([
                np.mean(ndvi_like),
                np.std(ndvi_like)
            ])
            
            # Brightness
            brightness = (points_df['Red'] + points_df['Green'] + points_df['Blue']) / 3
            features.extend([
                np.mean(brightness),
                np.std(brightness)
            ])
        
        hex_features.append(features)
        
        # Etykieta - najczęstsza klasa w heksagonie
        labels = points_df['label'].values
        unique_labels, counts = np.unique(labels, return_counts=True)
        dominant_label = int(unique_labels[np.argmax(counts)])  # Konwersja na int
        hex_labels.append(dominant_label)
    
    return np.array(hex_features), np.array(hex_labels)

# === Wczytaj dane ===
print("📁 Wczytywanie danych...")
df = pd.read_csv(CSV_PATH)

# Sprawdzenie czy mamy współrzędne X, Y
if 'X' not in df.columns or 'Y' not in df.columns:
    print("❌ Brak współrzędnych X, Y w danych!")
    print("Dostępne kolumny:", df.columns.tolist())
    exit(1)

print(f"📊 Wczytano {len(df)} punktów")
print(f"🏷️  Dostępne klasy: {sorted(df['label'].unique())}")

# === Tworzenie cech heksagonalnych ===
X_hex, y_hex = create_hexagon_features(df)

print(f"🔢 Wymiary cech heksagonalnych: {X_hex.shape}")
print(f"📊 Liczba heksagonów: {len(X_hex)}")

# Sprawdzenie czy mamy wystarczającą liczbę próbek
if len(X_hex) < 100:
    print("⚠️  Zbyt mało heksagonów do treningu! Spróbuj zwiększyć HEX_SIZE lub dodać więcej danych.")

# === Normalizacja danych ===
print("🔄 Normalizacja danych...")
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_hex)

# Zapisz parametry scalera
with open('scaler_hex.pkl', 'wb') as f:
    pickle.dump(scaler, f)
print("💾 Zapisano parametry normalizacji")

# === Podział na zbiór treningowy/testowy ===
X_train, X_test, y_train, y_test = train_test_split(X_scaled, y_hex, test_size=0.2, random_state=42, stratify=y_hex)

# Konwersja etykiet na int (wymagane dla CrossEntropyLoss)
y_train = y_train.astype(int)
y_test = y_test.astype(int)

print(f"🎯 Zbiór treningowy: {len(X_train)} próbek")
print(f"🧪 Zbiór testowy: {len(X_test)} próbek")

# === Konwersja do tensora ===
train_ds = TensorDataset(torch.tensor(X_train, dtype=torch.float32), torch.tensor(y_train, dtype=torch.long))
test_ds = TensorDataset(torch.tensor(X_test, dtype=torch.float32), torch.tensor(y_test, dtype=torch.long))
train_loader = DataLoader(train_ds, batch_size=64, shuffle=True)
test_loader = DataLoader(test_ds, batch_size=64)

# === Model MLP dostosowany do większej liczby cech ===
class HexTerrainNet(nn.Module):
    def __init__(self, input_dim, hidden_dim=128, output_dim=5):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),
            
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.BatchNorm1d(hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(0.2),
            
            nn.Linear(hidden_dim // 2, hidden_dim // 4),
            nn.ReLU(),
            nn.Dropout(0.1),
            
            nn.Linear(hidden_dim // 4, output_dim)
        )
    
    def forward(self, x):
        return self.net(x)

# Liczba unikalnych klas
num_classes = len(np.unique(y_hex))
input_features = X_scaled.shape[1]

model = HexTerrainNet(input_dim=input_features, output_dim=num_classes)
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', patience=10, factor=0.5)

# === Trening z progress tracking ===
print(f"📊 Rozpoczynam trening na {len(train_ds)} heksagonach")
print(f"🔢 Liczba cech wejściowych: {input_features}")
print(f"🔢 Liczba parametrów modelu: {sum(p.numel() for p in model.parameters()):,}")

best_acc = 0
patience = 25
counter = 0
start_time = time.time()

for epoch in range(200):
    # --- trening ---
    model.train()
    total_loss = 0
    batch_count = 0
    
    for xb, yb in train_loader:
        optimizer.zero_grad()
        preds = model(xb)
        loss = criterion(preds, yb)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        batch_count += 1
    
    avg_loss = total_loss / batch_count
    
    # --- walidacja ---
    model.eval()
    val_preds, val_targets = [], []
    with torch.no_grad():
        for xb, yb in test_loader:
            out = model(xb)
            pred = torch.argmax(out, dim=1)
            val_preds.extend(pred.cpu().numpy())
            val_targets.extend(yb.cpu().numpy())
    
    val_acc = accuracy_score(val_targets, val_preds)
    elapsed = time.time() - start_time
    
    # Aktualizacja learning rate
    scheduler.step(val_acc)
    current_lr = optimizer.param_groups[0]['lr']
    
    print(f"Epoch {epoch+1:3d}: Loss {avg_loss:.4f}, Val Acc {val_acc:.4f}, LR {current_lr:.6f} | Time: {elapsed:.1f}s")
    
    # --- early stopping + checkpoint ---
    if val_acc > best_acc:
        best_acc = val_acc
        counter = 0
        torch.save({
            'model_state_dict': model.state_dict(),
            'scaler': scaler,
            'hex_size': HEX_SIZE,
            'input_features': INPUT_FEATURES,
            'num_classes': num_classes,
            'input_dim': input_features
        }, "best_hex_model.pth")
        print(f"💾 Zapisano najlepszy model (acc: {best_acc:.4f})")
    else:
        counter += 1
        if counter >= patience:
            print(f"🔚 Early stopping — brak poprawy przez {patience} epok")
            break

print(f"✅ Trening zakończony. Najlepsza dokładność: {best_acc:.4f}")
print(f"⏱️  Całkowity czas: {time.time() - start_time:.1f}s")

# === Analiza wyników ===
print("\n📈 Analiza wyników:")
print(f"📊 Dokładność na poziomie heksagonów: {best_acc:.4f}")

# Macierz konfuzji
from sklearn.metrics import classification_report, confusion_matrix

# Wczytaj najlepszy model
checkpoint = torch.load("best_hex_model.pth")
model.load_state_dict(checkpoint['model_state_dict'])

model.eval()
final_preds, final_targets = [], []
with torch.no_grad():
    for xb, yb in test_loader:
        out = model(xb)
        pred = torch.argmax(out, dim=1)
        final_preds.extend(pred.cpu().numpy())
        final_targets.extend(yb.cpu().numpy())

print("\n📋 Raport klasyfikacji:")
print(classification_report(final_targets, final_preds))

print("\n🔢 Macierz konfuzji:")
conf_matrix = confusion_matrix(final_targets, final_preds)
print(conf_matrix)