#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ULTIMATE Building Classifier - Headless Version (bez GUI)
Wersja przystosowana do uruchamiania w środowisku QGIS/serwera
"""

# CRITICAL: Set non-interactive backends BEFORE any other imports
import sys
import warnings
from qgis.core import QgsProject
import os
from pathlib import Path
from qgis.core import QgsApplication

# Fix GUI conflicts
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['MPLBACKEND'] = 'Agg'
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Disable matplotlib GUI
import matplotlib
matplotlib.use('Agg')

# Suppress warnings
warnings.filterwarnings('ignore')
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=FutureWarning)

# Now safe to import other modules
import pandas as pd
from pathlib import Path
import pickle
import numpy as np
from PIL import Image
from collections import Counter
from datetime import datetime
import json

# Non-GUI tqdm
from tqdm import tqdm

# Imports z fallback
try:
    from skimage.feature import local_binary_pattern, graycomatrix, graycoprops
    from skimage.filters import gaussian
    from skimage.measure import regionprops, label
    from skimage.morphology import disk
    from skimage.filters.rank import entropy
    SKIMAGE_AVAILABLE = True
except ImportError:
    SKIMAGE_AVAILABLE = False
    print("Warning: scikit-image not available, using fallback features")

try:
    from scipy.ndimage import uniform_filter
    from scipy.stats import skew, kurtosis
    from scipy.signal import correlate2d
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy not available, using fallback features")

# Scikit-learn
from sklearn.model_selection import (train_test_split, GridSearchCV, RandomizedSearchCV, 
                                   StratifiedKFold, cross_val_score)
from sklearn.ensemble import (RandomForestClassifier, GradientBoostingClassifier, 
                            VotingClassifier, ExtraTreesClassifier, BaggingClassifier)
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from sklearn.preprocessing import LabelEncoder, RobustScaler, PowerTransformer
from sklearn.decomposition import PCA, TruncatedSVD
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.feature_selection import SelectKBest, f_classif, RFECV
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV

# Ustawienia
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))
np.random.seed(42)

# Pobierz ścieżkę projektu z argumentu (jeśli podano)
if len(sys.argv) > 1:
    project_path = sys.argv[1]
    project_directory = os.path.dirname(project_path)
else:
    print("⚠️ Nie podano ścieżki projektu jako argumentu. Używam katalogu roboczego.")
    project_directory = os.getcwd()


# Progress bar for console (no GUI)
def console_progress(iterable, desc="Processing"):
    """Simple console progress without GUI"""
    total = len(iterable) if hasattr(iterable, '__len__') else None
    if total:
        print(f"{desc}: 0/{total}")
        for i, item in enumerate(iterable, 1):
            if i % max(1, total // 10) == 0 or i == total:
                print(f"{desc}: {i}/{total}")
            yield item
    else:
        for i, item in enumerate(iterable):
            if i % 100 == 0:
                print(f"{desc}: {i}...")
            yield item

class UltimateFeatureExtractor:
    """Najbardziej zaawansowana ekstrakcja cech - headless version"""
    
    def __init__(self, img_size=128):
        self.img_size = img_size
        self.gabor_filters = self._create_gabor_filters()
    
    def _create_gabor_filters(self):
        """Tworzy banki filtrów Gabor"""
        filters = []
        for theta in [0, 45, 90, 135]:  # orientacje
            for frequency in [0.1, 0.3]:  # częstotliwości
                # Prosty filtr Gabor (bez OpenCV)
                ksize = 15
                sigma = 3
                theta_rad = np.deg2rad(theta)
                
                # Kernel Gabor
                x = np.arange(-ksize//2, ksize//2 + 1)
                y = np.arange(-ksize//2, ksize//2 + 1)
                X, Y = np.meshgrid(x, y)
                
                x_theta = X * np.cos(theta_rad) + Y * np.sin(theta_rad)
                y_theta = -X * np.sin(theta_rad) + Y * np.cos(theta_rad)
                
                gb = np.exp(-(x_theta**2 + y_theta**2) / (2 * sigma**2)) * \
                     np.cos(2 * np.pi * frequency * x_theta)
                
                filters.append(gb)
        return filters
    
    def extract_gabor_features(self, image):
        """Ekstraktuje cechy Gabor"""
        if not SCIPY_AVAILABLE:
            return np.zeros(16)  # Fallback
        
        features = []
        from scipy.signal import correlate2d
        
        for gabor_filter in self.gabor_filters:
            # Konwolucja z filtrem Gabor
            filtered = correlate2d(image, gabor_filter, mode='same')
            
            features.extend([
                np.mean(np.abs(filtered)),
                np.std(filtered),
                np.mean(filtered**2),  # energia
                np.sum(np.abs(filtered) > 0.1) / filtered.size  # aktywność
            ])
        
        return np.array(features)
    
    def extract_advanced_texture_features(self, image):
        """Zaawansowane cechy tekstury"""
        features = []
        
        if SKIMAGE_AVAILABLE:
            # LBP z różnymi parametrami
            for radius in [1, 2]:
                for n_points in [8, 16]:
                    if radius == 1 and n_points == 16:
                        continue  # Skip invalid combination
                    try:
                        lbp = local_binary_pattern(image, n_points, radius, method='uniform')
                        n_bins = n_points + 2
                        lbp_hist, _ = np.histogram(lbp.ravel(), bins=n_bins, range=(0, n_bins))
                        lbp_hist = lbp_hist / (np.sum(lbp_hist) + 1e-7)
                        features.extend(lbp_hist)
                    except:
                        features.extend([0] * (n_points + 2))
            
            # GLCM z więcej kierunków i odległości
            try:
                image_int = (image * 255).astype(np.uint8)
                distances = [1, 2]
                angles = [0, 45, 90, 135]
                
                glcm = graycomatrix(image_int, distances, angles, 
                                 levels=64, symmetric=True, normed=True)
                
                # Więcej właściwości GLCM
                for prop in ['contrast', 'dissimilarity', 'homogeneity', 'energy', 
                           'correlation', 'ASM']:
                    try:
                        prop_values = graycoprops(glcm, prop).flatten()
                        features.extend(prop_values)
                    except:
                        features.extend([0] * 8)  # 2 distances × 4 angles
                        
            except:
                features.extend([0] * 48)  # 6 properties × 8 combinations
            
            # Entropia lokalna
            try:
                selem = disk(3)
                ent = entropy(((image * 255).astype(np.uint8)), selem)
                features.extend([
                    np.mean(ent),
                    np.std(ent),
                    np.max(ent)
                ])
            except:
                features.extend([0, 0, 0])
                
        else:
            # Fallback bez scikit-image
            features.extend([0] * 100)  # Placeholder
        
        return np.array(features)
    
    def extract_advanced_shape_features(self, image):
        """Zaawansowane cechy kształtu"""
        features = []
        
        # Multi-threshold shape analysis
        thresholds = [0.3, 0.5, 0.7]
        
        for thresh in thresholds:
            binary = image > thresh
            
            # Podstawowe właściwości
            area = np.sum(binary)
            if area > 0:
                # Moments
                y_coords, x_coords = np.where(binary)
                centroid_y, centroid_x = np.mean(y_coords), np.mean(x_coords)
                
                # Moment analysis
                mu20 = np.sum((x_coords - centroid_x)**2) / area
                mu02 = np.sum((y_coords - centroid_y)**2) / area  
                mu11 = np.sum((x_coords - centroid_x) * (y_coords - centroid_y)) / area
                
                # Eccentricity approximation
                lambda1 = 0.5 * (mu20 + mu02) + 0.5 * np.sqrt(4*mu11**2 + (mu20-mu02)**2)
                lambda2 = 0.5 * (mu20 + mu02) - 0.5 * np.sqrt(4*mu11**2 + (mu20-mu02)**2)
                eccentricity = np.sqrt(1 - lambda2/(lambda1 + 1e-7))
                
                # Convex hull approximation (bounding box)
                bbox_area = (np.max(y_coords) - np.min(y_coords)) * (np.max(x_coords) - np.min(x_coords))
                solidity = area / (bbox_area + 1e-7)
                
                features.extend([
                    area / (self.img_size**2),  # relative area
                    eccentricity,
                    solidity,
                    centroid_x / self.img_size,
                    centroid_y / self.img_size
                ])
            else:
                features.extend([0, 0, 0, 0.5, 0.5])
        
        return np.array(features)
    
    def extract_advanced_statistical_features(self, image):
        """Zaawansowane cechy statystyczne"""
        features = []
        
        # Podstawowe statystyki
        features.extend([
            np.mean(image),
            np.std(image),
            np.var(image),
            np.min(image),
            np.max(image),
            np.median(image)
        ])
        
        # Percentyle
        for p in [10, 25, 75, 90]:
            features.append(np.percentile(image, p))
        
        # Momenty wyższych rzędów
        if SCIPY_AVAILABLE:
            features.extend([
                skew(image.flatten()),
                kurtosis(image.flatten())
            ])
        else:
            features.extend([0, 0])
        
        # Histogram features (więcej binów)
        hist, _ = np.histogram(image, bins=16, range=(0, 1))
        hist = hist / (np.sum(hist) + 1e-7)
        features.extend(hist)
        
        # Range i IQR
        features.extend([
            np.max(image) - np.min(image),  # range
            np.percentile(image, 75) - np.percentile(image, 25)  # IQR
        ])
        
        return np.array(features)
    
    def extract_spatial_pyramid_features(self, image):
        """Spatial pyramid features"""
        features = []
        
        # Level 0: cały obraz
        features.extend([np.mean(image), np.std(image)])
        
        # Level 1: 2x2 podział
        h, w = image.shape
        for i in range(2):
            for j in range(2):
                region = image[i*h//2:(i+1)*h//2, j*w//2:(j+1)*w//2]
                features.extend([np.mean(region), np.std(region)])
        
        # Level 2: 4x4 podział (tylko średnie żeby nie było za dużo cech)
        for i in range(4):
            for j in range(4):
                region = image[i*h//4:(i+1)*h//4, j*w//4:(j+1)*w//4]
                features.append(np.mean(region))
        
        return np.array(features)
    
    def extract_all_features(self, image):
        """Ekstraktuje wszystkie zaawansowane cechy"""
        gabor_feats = self.extract_gabor_features(image)
        texture_feats = self.extract_advanced_texture_features(image)
        shape_feats = self.extract_advanced_shape_features(image)  
        stat_feats = self.extract_advanced_statistical_features(image)
        spatial_feats = self.extract_spatial_pyramid_features(image)
        
        # Zmniejszone raw pixels
        pil_img = Image.fromarray((image * 255).astype(np.uint8))
        resized_img = pil_img.resize((24, 24), Image.Resampling.LANCZOS)  # 576 pikseli
        pixel_feats = np.array(resized_img, dtype=np.float32).flatten() / 255.0
        
        all_features = np.concatenate([
            gabor_feats,
            texture_feats,
            shape_feats,
            stat_feats,
            spatial_feats,
            pixel_feats
        ])
        
        return all_features

class AdvancedDataAugmenter:
    """Zaawansowana augmentacja - headless version"""
    
    def __init__(self):
        pass
    
    def augment_image(self, image, augment_type='random'):
        """Rozszerzona augmentacja"""
        if isinstance(image, np.ndarray):
            # Disable GUI warnings for PIL
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pil_image = Image.fromarray((image * 255).astype(np.uint8))
        else:
            pil_image = image
        
        try:
            if augment_type == 'rotate':
                angle = np.random.choice([-20, -15, -10, -5, 5, 10, 15, 20])
                return pil_image.rotate(angle, fillcolor=128)
            
            elif augment_type == 'brightness':
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Brightness(pil_image)
                factor = np.random.uniform(0.7, 1.3)
                return enhancer.enhance(factor)
            
            elif augment_type == 'contrast':
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Contrast(pil_image)
                factor = np.random.uniform(0.7, 1.3)
                return enhancer.enhance(factor)
            
            elif augment_type == 'sharpness':
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Sharpness(pil_image)
                factor = np.random.uniform(0.5, 2.0)
                return enhancer.enhance(factor)
            
            elif augment_type == 'blur':
                from PIL import ImageFilter
                radius = np.random.uniform(0.5, 1.5)
                return pil_image.filter(ImageFilter.GaussianBlur(radius=radius))
            
            elif augment_type == 'noise':
                arr = np.array(pil_image)
                noise = np.random.normal(0, np.random.uniform(3, 8), arr.shape)
                noisy = np.clip(arr + noise, 0, 255)
                return Image.fromarray(noisy.astype(np.uint8))
            
            elif augment_type == 'crop_resize':
                # Random crop i resize
                w, h = pil_image.size
                crop_size = int(min(w, h) * np.random.uniform(0.8, 1.0))
                left = np.random.randint(0, w - crop_size + 1)
                top = np.random.randint(0, h - crop_size + 1)
                cropped = pil_image.crop((left, top, left + crop_size, top + crop_size))
                return cropped.resize((w, h), Image.Resampling.LANCZOS)
            
            else:  # random
                aug_types = ['rotate', 'brightness', 'contrast', 'sharpness', 'blur', 'noise', 'crop_resize']
                chosen_type = np.random.choice(aug_types)
                return self.augment_image(pil_image, chosen_type)
                
        except Exception as e:
            print(f"Augmentation error: {e}, returning original image")
            return pil_image

# Rest of the classes remain the same but with progress bar fixes...

def batch_predict_buildings_headless(model_package, output_dir, csv_output_path=None):
    """
    Headless version of batch prediction
    """
    
    # Sprawdź czy katalog istnieje
    if not os.path.exists(output_dir):
        raise FileNotFoundError(f"Katalog {output_dir} nie istnieje!")
    
    # Znajdź wszystkie pliki PNG
    png_files = []
    for file in os.listdir(output_dir):
        if file.lower().endswith('.png'):
            png_files.append(file)
    
    if len(png_files) == 0:
        print(f"Nie znaleziono plików PNG w katalogu {output_dir}")
        return None
    
    print(f"Znaleziono {len(png_files)} plików PNG")
    
    # Przygotowanie listy wyników
    results = []
    
    # Przetwarzanie każdego pliku - BEZ GUI
    print("Rozpoczynam przetwarzanie obrazów...")
    for i, filename in enumerate(png_files):
        try:
            # Progress info co 10% lub co 100 plików
            if i % max(1, len(png_files) // 10) == 0 or (i + 1) == len(png_files):
                print(f"Przetwarzanie: {i + 1}/{len(png_files)} ({((i + 1)/len(png_files)*100):.1f}%)")
            
            # Wyciągnij ID budynku z nazwy pliku
            building_id = os.path.splitext(filename)[0]  # Usuń rozszerzenie
            
            # Pełna ścieżka do pliku
            image_path = os.path.join(output_dir, filename)
            
            # Wykonaj predykcję
            prediction_result = predict_with_ultimate_model_headless(model_package, image_path)
            
            # Dodaj wynik do listy
            result_row = {
                'ID_BUDYNKU': building_id,
                'PREDYKCJA': prediction_result['predicted_class'],
                'PEWNOSC': round(prediction_result['confidence'], 4),
                'PLIK': filename
            }
            
            # Dodaj prawdopodobieństwa dla każdej klasy (opcjonalnie)
            for class_name, prob in prediction_result['all_probabilities'].items():
                result_row[f'PROB_{class_name.upper()}'] = round(prob, 4)
            
            results.append(result_row)
            
        except Exception as e:
            print(f"Błąd przy przetwarzaniu {filename}: {str(e)}")
            # Dodaj wiersz z błędem
            results.append({
                'ID_BUDYNKU': os.path.splitext(filename)[0],
                'PREDYKCJA': 'ERROR',
                'PEWNOSC': 0.0,
                'PLIK': filename
            })
    
    # Tworzenie DataFrame
    df = pd.DataFrame(results)
    
    # Sortowanie po ID budynku
    df = df.sort_values('ID_BUDYNKU')
    
    # Określ nazwę pliku CSV
    if csv_output_path is None:
        csv_output_path = os.path.join(output_dir, 'building_predictions.csv')
    
    # Zapisz do CSV
    df.to_csv(csv_output_path, index=False, encoding='utf-8')
    
    # Podsumowanie
    print(f"\n{'='*50}")
    print("PODSUMOWANIE PREDYKCJI")
    print(f"{'='*50}")
    print(f"Przetworzono plików: {len(results)}")
    print(f"Wyniki zapisane w: {csv_output_path}")
    print(f"\nRozkład predykcji:")
    if 'PREDYKCJA' in df.columns:
        prediction_counts = df['PREDYKCJA'].value_counts()
        for class_name, count in prediction_counts.items():
            print(f"  {class_name}: {count} budynków")
    
    print(f"\nŚrednia pewność predykcji: {df['PEWNOSC'].mean():.3f}")
    print(f"CSV zawiera {len(df.columns)} kolumn i {len(df)} wierszy")
    
    return csv_output_path

def predict_with_ultimate_model_headless(model_package, image_path_or_array):
    """
    Headless version of prediction
    """
    # Pobranie komponentów z pakietu
    best_model = model_package['best_model']
    feature_extractor = model_package['feature_extractor']
    scaler = model_package['scaler']
    feature_selector = model_package['feature_selector']
    pca = model_package['pca']
    class_names = model_package['class_names']
    
    # Załadowanie i przetworzenie obrazu
    if isinstance(image_path_or_array, str):
        # Ścieżka do pliku - suppress PIL warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            img = Image.open(image_path_or_array).convert('L')
            img = img.resize((model_package['img_size'], model_package['img_size']), 
                            Image.Resampling.LANCZOS)
            img_array = np.array(img, dtype=np.float32) / 255.0
    else:
        # Tablica numpy
        img_array = image_path_or_array
    
    # Ekstrakcja cech
    features = feature_extractor.extract_all_features(img_array)
    features = features.reshape(1, -1)  # Single sample
    
    # Preprocessing
    features_scaled = scaler.transform(features)
    
    if feature_selector is not None:
        features_selected = feature_selector.transform(features_scaled)
    else:
        features_selected = features_scaled
        
    if pca is not None:
        features_final = pca.transform(features_selected)
    else:
        features_final = features_selected
    
    # Predykcja
    prediction = best_model.predict(features_final)[0]
    probabilities = best_model.predict_proba(features_final)[0]
    
    # Wyniki
    predicted_class = class_names[prediction]
    confidence = np.max(probabilities)
    
    # Wszystkie prawdopodobieństwa
    class_probabilities = {class_names[i]: prob for i, prob in enumerate(probabilities)}
    
    return {
        'predicted_class': predicted_class,
        'confidence': confidence,
        'all_probabilities': class_probabilities
    }

def load_ultimate_model_headless(filepath):
    """
    Headless version of model loading
    """
    print(f"Ładowanie modelu z: {filepath}")
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with open(filepath, 'rb') as f:
            model_package = pickle.load(f)
    
    print("Załadowano model:")
    print(f"  - Model: {model_package['model_name']}")
    print(f"  - Accuracy: {model_package['accuracy']:.4f}")
    print(f"  - Klasy: {model_package['class_names']}")
    
    return model_package

# USAGE FOR HEADLESS EXECUTION:

print("HEADLESS Building Classifier")
    
    # Użycie:
def get_prediction_data_dir():
    """Zwraca ścieżkę do katalogu prediction_data w folderze projektu QGIS"""
    prediction_dir = Path(project_directory) / "prediction_data"
    prediction_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Katalog wyjściowy: {prediction_dir}")
    return str(prediction_dir)


# Użycie:
OUTPUT_DIR = get_prediction_data_dir()

model_name='ultimate_building_classifier_svm_0.957_20250911_114900.pkl'
# model_path = "/home/adrian/miniconda3/envs/geoworkspace/share/qgis/python/wz_workflow/ultimate_building_classifier_svm_0.957_20250911_114900.pkl"
model_path = os.path.join(SCRIPTS_PATH, model_name)
model_package = load_ultimate_model_headless(model_path)
csv_path = batch_predict_buildings_headless(model_package=model_package, output_dir=OUTPUT_DIR)
    
pass
