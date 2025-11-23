#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ULTIMATE Building Classifier z prawidłowym zapisywaniem modelu
"""
import os
import sys

# Wyłączenie GUI dla matplotlib
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

# Wyłączenie Qt dla PIL
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# Dla systemów bez wyświetlacza
os.environ['MPLBACKEND'] = 'Agg'

# Wyłączenie interaktywnych elementów
import warnings
warnings.filterwarnings('ignore', category=UserWarning)

# Dla niektórych bibliotek
os.environ['PYTHONIOENCODING'] = 'utf-8'


import pandas as pd
from qgis.core import QgsProject
from pathlib import Path
import dill
from tqdm import tqdm
import torch
import torch.nn as nn
from datetime import datetime
import json
import os
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from PIL import Image, ImageEnhance, ImageFilter
import pickle
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

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

try:
    from scipy.ndimage import uniform_filter
    from scipy.stats import skew, kurtosis
    from scipy.signal import correlate2d
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

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
# SCRIPTS_PATH = "/home/adrian/Documents/JXPROJEKT/skrypty/wz_workflow_qgis_plugin/src"

np.random.seed(42)

class UltimateFeatureExtractor:
    """Najbardziej zaawansowana ekstrakcja cech"""
    
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
    """Zaawansowana augmentacja"""
    
    def __init__(self):
        pass
    
    def augment_image(self, image, augment_type='random'):
        """Rozszerzona augmentacja"""
        if isinstance(image, np.ndarray):
            pil_image = Image.fromarray((image * 255).astype(np.uint8))
        else:
            pil_image = image
        
        if augment_type == 'rotate':
            angle = np.random.choice([-20, -15, -10, -5, 5, 10, 15, 20])
            return pil_image.rotate(angle, fillcolor=128)
        
        elif augment_type == 'brightness':
            enhancer = ImageEnhance.Brightness(pil_image)
            factor = np.random.uniform(0.7, 1.3)
            return enhancer.enhance(factor)
        
        elif augment_type == 'contrast':
            enhancer = ImageEnhance.Contrast(pil_image)
            factor = np.random.uniform(0.7, 1.3)
            return enhancer.enhance(factor)
        
        elif augment_type == 'sharpness':
            enhancer = ImageEnhance.Sharpness(pil_image)
            factor = np.random.uniform(0.5, 2.0)
            return enhancer.enhance(factor)
        
        elif augment_type == 'blur':
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

class UltimateBuildingClassifier:
    """Ultimate klasyfikator z wszystkimi trickami"""
    
    def __init__(self, data_dir='ml_dataset', img_size=128):
        self.data_dir = data_dir
        self.img_size = img_size
        self.feature_extractor = UltimateFeatureExtractor(img_size)
        self.augmenter = AdvancedDataAugmenter()
        
        self.label_encoder = LabelEncoder()
        self.scaler = PowerTransformer(method='yeo-johnson')  # Lepszy niż RobustScaler
        self.feature_selector = None
        self.pca = None
        self.models = {}
        self.class_names = []
        self.cv_scores = {}
    
    def load_and_preprocess_dataset(self, max_images_per_class=None, test_size=0.15, 
                                  augment_factor=5, min_class_size=8):
        """Zaawansowane ładowanie z większą augmentacją"""
        print("Ładowanie datasetu z zaawansowaną augmentacją...")
        
        categories = [d for d in os.listdir(self.data_dir) 
                     if os.path.isdir(os.path.join(self.data_dir, d)) 
                     and not d.startswith('.')]
        
        # Sprawdzenie rozmiaru klas
        class_sizes = {}
        for category in categories:
            category_path = os.path.join(self.data_dir, category)
            image_files = [f for f in os.listdir(category_path) 
                          if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            class_sizes[category] = len(image_files)
        
        valid_categories = [cat for cat, size in class_sizes.items() 
                          if size >= min_class_size]
        print(f"Kategorie: {valid_categories}")
        
        all_features = []
        all_labels = []
        
        for category in valid_categories:
            category_path = os.path.join(self.data_dir, category)
            image_files = [f for f in os.listdir(category_path) 
                          if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            
            if max_images_per_class:
                image_files = image_files[:max_images_per_class]
            
            print(f"Kategoria '{category}': {len(image_files)} oryginalnych obrazów")
            
            category_features = []
            
            # Oryginalne obrazy
            for img_file in image_files:
                img_path = os.path.join(category_path, img_file)
                try:
                    img = Image.open(img_path).convert('L')
                    img = img.resize((self.img_size, self.img_size), Image.Resampling.LANCZOS)
                    img_array = np.array(img, dtype=np.float32) / 255.0
                    
                    features = self.feature_extractor.extract_all_features(img_array)
                    category_features.append(features)
                    
                except Exception as e:
                    print(f"Błąd: {img_path}: {e}")
                    continue
            
            # Intensywna augmentacja
            original_count = len(category_features)
            target_count = original_count * augment_factor
            
            print(f"  Augmentacja: {original_count} → {target_count}")
            
            while len(category_features) < target_count:
                img_file = np.random.choice(image_files)
                img_path = os.path.join(category_path, img_file)
                
                try:
                    img = Image.open(img_path).convert('L')
                    img = img.resize((self.img_size, self.img_size), Image.Resampling.LANCZOS)
                    
                    # Podwójna augmentacja czasami
                    aug_img = self.augmenter.augment_image(img)
                    if np.random.random() < 0.3:  # 30% szans na drugą augmentację
                        aug_img = self.augmenter.augment_image(aug_img)
                    
                    aug_array = np.array(aug_img, dtype=np.float32) / 255.0
                    features = self.feature_extractor.extract_all_features(aug_array)
                    category_features.append(features)
                    
                except Exception as e:
                    continue
            
            all_features.extend(category_features)
            all_labels.extend([category] * len(category_features))
            
            print(f"  Finalne próbki: {len(category_features)}")
        
        X = np.array(all_features, dtype=np.float32)
        y_encoded = self.label_encoder.fit_transform(all_labels)
        self.class_names = self.label_encoder.classes_
        
        print(f"\nDataset final: {len(X)} próbek, {X.shape[1]} cech")
        print(f"Klasy: {len(self.class_names)}")
        
        for cls, count in Counter(all_labels).items():
            print(f"  {cls}: {count} próbek")
        
        # Mniejszy test set dla większego train set
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_encoded, test_size=test_size, 
            stratify=y_encoded, random_state=42
        )
        
        print(f"\nPodział: Train {len(X_train)}, Test {len(X_test)}")
        
        return (X_train, y_train), (X_test, y_test)
    
    def advanced_preprocessing(self, X_train, X_test, y_train, use_feature_selection=True):        
        print("Zaawansowany preprocessing...")
        
        # Czyszczenie
        X_train = np.nan_to_num(X_train, nan=0.0, posinf=1.0, neginf=-1.0)
        X_test = np.nan_to_num(X_test, nan=0.0, posinf=1.0, neginf=-1.0)
        
        # Power transformation (lepsze niż standardowe skalowanie)
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Feature selection
        if use_feature_selection and X_train_scaled.shape[1] > 100:
            n_features = min(500, X_train_scaled.shape[1] // 2)
            self.feature_selector = SelectKBest(score_func=f_classif, k=n_features)
            X_train_selected = self.feature_selector.fit_transform(X_train_scaled, y_train)
            X_test_selected = self.feature_selector.transform(X_test_scaled)
            
            print(f"Feature selection: {X_train_scaled.shape[1]} → {X_train_selected.shape[1]}")
        else:
            X_train_selected = X_train_scaled
            X_test_selected = X_test_scaled
        
        # PCA (mniej agresywne)
        if X_train_selected.shape[1] > 200:
            self.pca = PCA(n_components=0.98, random_state=42)  # 98% wariancji
            X_train_pca = self.pca.fit_transform(X_train_selected)
            X_test_pca = self.pca.transform(X_test_selected)
            
            print(f"PCA: {X_train_selected.shape[1]} → {X_train_pca.shape[1]} (98% wariancji)")
            
            return X_train_pca, X_test_pca
        
        return X_train_selected, X_test_selected
    
    def hyperparameter_tuning(self, X_train, y_train, model_name, quick_mode=False):
        """Intensywne strojenie hiperparametrów"""
        print(f"Tuning hiperparametrów dla {model_name}...")
        
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        
        if model_name == 'rf':
            model = RandomForestClassifier(random_state=42, n_jobs=-1)
            if quick_mode:
                param_grid = {
                    'n_estimators': [200, 300],
                    'max_depth': [15, 20, 25],
                    'min_samples_split': [2, 3],
                    'min_samples_leaf': [1, 2]
                }
            else:
                param_grid = {
                    'n_estimators': [150, 200, 300, 400],
                    'max_depth': [10, 15, 20, 25, 30],
                    'min_samples_split': [2, 3, 4],
                    'min_samples_leaf': [1, 2],
                    'max_features': ['sqrt', 'log2', None]
                }
        
        elif model_name == 'xgb':
            model = xgb.XGBClassifier(random_state=42, eval_metric='mlogloss')
            if quick_mode:
                param_grid = {
                    'n_estimators': [200, 300],
                    'max_depth': [4, 6, 8],
                    'learning_rate': [0.1, 0.15],
                    'subsample': [0.8, 1.0]
                }
            else:
                param_grid = {
                    'n_estimators': [150, 200, 300, 400],
                    'max_depth': [3, 4, 5, 6, 7, 8],
                    'learning_rate': [0.05, 0.1, 0.15, 0.2],
                    'subsample': [0.7, 0.8, 0.9, 1.0],
                    'colsample_bytree': [0.8, 0.9, 1.0]
                }
        
        elif model_name == 'et':  # Extra Trees
            model = ExtraTreesClassifier(random_state=42, n_jobs=-1)
            param_grid = {
                'n_estimators': [200, 300, 400],
                'max_depth': [15, 20, 25],
                'min_samples_split': [2, 3],
                'min_samples_leaf': [1, 2]
            }
        
        elif model_name == 'svm':
            model = SVC(random_state=42, probability=True)
            param_grid = {
                'C': [1, 10, 50, 100],
                'kernel': ['rbf', 'poly'],
                'gamma': ['scale', 'auto', 0.001, 0.01]
            }
        
        else:
            return None
        
        # RandomizedSearchCV dla szybszego tuningu
        if quick_mode:
            search = GridSearchCV(model, param_grid, cv=cv, 
                                scoring='accuracy', n_jobs=-1)
        else:
            search = RandomizedSearchCV(model, param_grid, n_iter=50, cv=cv,
                                      scoring='accuracy', n_jobs=-1, random_state=42)
        
        search.fit(X_train, y_train)
        
        print(f"  Najlepszy wynik: {search.best_score_:.4f}")
        print(f"  Najlepsze parametry: {search.best_params_}")
        
        return search.best_estimator_
    
    def train_ultimate_models(self, X_train, y_train, intensive_tuning=True):
        """Trening z intensywnym tuningiem"""
        print("Trening ultimate models...")
        
        # Cross-validation setup
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        
        # Modele do treningu
        model_list = ['rf', 'xgb', 'et']
        if X_train.shape[0] < 2000:  # SVM tylko dla mniejszych datasetów
            model_list.append('svm')
        
        for model_name in model_list:
            print(f"\n=== Trenowanie {model_name.upper()} ===")
            
            # Hyperparameter tuning
            best_model = self.hyperparameter_tuning(
                X_train, y_train, model_name, 
                quick_mode=not intensive_tuning
            )
            
            if best_model is not None:
                # Cross-validation score
                cv_scores = cross_val_score(best_model, X_train, y_train, 
                                          cv=cv, scoring='accuracy')
                
                self.models[model_name] = best_model
                self.cv_scores[model_name] = {
                    'mean': cv_scores.mean(),
                    'std': cv_scores.std(),
                    'scores': cv_scores
                }
                
                print(f"  CV Score: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
        
        # Calibrated models (lepsza probabilistyka)
        print("\n=== Kalibracja modeli ===")
        calibrated_models = {}
        for name, model in self.models.items():
            if hasattr(model, 'predict_proba'):
                try:
                    calibrated = CalibratedClassifierCV(model, method='isotonic', cv=3)
                    calibrated.fit(X_train, y_train)
                    calibrated_models[f"{name}_cal"] = calibrated
                    print(f"  {name} skalibrowany")
                except:
                    print(f"  {name} błąd kalibracji")
        
        self.models.update(calibrated_models)
    
    def create_ultimate_ensemble(self, X_train, y_train):
        """Tworzy zaawansowany ensemble"""
        print("Tworzenie ultimate ensemble...")
        
        if len(self.models) < 2:
            return False
        
        # Wybierz najlepsze modele na podstawie CV scores
        sorted_models = sorted(self.cv_scores.items(), 
                              key=lambda x: x[1]['mean'], reverse=True)
        
        # Top 3-5 modeli
        top_models = sorted_models[:min(5, len(sorted_models))]
        print(f"Top modele do ensemble:")
        for name, scores in top_models:
            print(f"  {name}: {scores['mean']:.4f} ± {scores['std']:.4f}")
        
        # Różne typy ensemble
        estimators = [(name, self.models[name]) for name, _ in top_models 
                     if name in self.models]
        
        # Voting ensemble (soft voting)
        self.voting_ensemble = VotingClassifier(
            estimators=estimators, voting='soft'
        )
        
        # Weighted ensemble (wagi na podstawie CV performance)
        weights = [scores['mean'] for _, scores in top_models if scores is not None]
        weights = np.array(weights)
        weights = weights / np.sum(weights)  # normalizacja
        
        # Stacking ensemble (meta-learner)
        try:
            from sklearn.ensemble import StackingClassifier
            meta_learner = LogisticRegression(random_state=42, max_iter=1000)
            
            self.stacking_ensemble = StackingClassifier(
                estimators=estimators,
                final_estimator=meta_learner,
                cv=3  # 3-fold dla meta-learnera
            )
            print("  Utworzono stacking ensemble")
        except ImportError:
            self.stacking_ensemble = None
            print("  Stacking niedostępny")
        
        # Trenowanie ensemble
        print("  Trenowanie ensemble...")
        self.voting_ensemble.fit(X_train, y_train)
        
        if self.stacking_ensemble:
            self.stacking_ensemble.fit(X_train, y_train)
        
        return True
    
    def evaluate_ultimate_models(self, X_test, y_test):
        """Ultimate ewaluacja"""
        print("\n" + "="*60)
        print("ULTIMATE EVALUATION")
        print("="*60)
        
        results = {}
        
        # Ewaluuj pojedyncze modele
        print("Pojedyncze modele:")
        for name, model in self.models.items():
            try:
                y_pred = model.predict(X_test)
                accuracy = accuracy_score(y_test, y_pred)
                results[name] = accuracy
                
                # Pokaż też CV score dla porównania
                cv_score = self.cv_scores.get(name.replace('_cal', ''), {}).get('mean', 0)
                print(f"  {name:15}: {accuracy:.4f} (CV: {cv_score:.4f})")
                
            except Exception as e:
                print(f"  Błąd {name}: {e}")
                results[name] = 0.0
        
        # Ewaluuj ensemble
        print("\nEnsemble modele:")
        
        # Voting ensemble
        try:
            y_pred_voting = self.voting_ensemble.predict(X_test)
            acc_voting = accuracy_score(y_test, y_pred_voting)
            results['voting_ensemble'] = acc_voting
            print(f"  {'voting':15}: {acc_voting:.4f}")
        except Exception as e:
            print(f"  Voting error: {e}")
            results['voting_ensemble'] = 0.0
        
        # Stacking ensemble
        if hasattr(self, 'stacking_ensemble') and self.stacking_ensemble:
            try:
                y_pred_stacking = self.stacking_ensemble.predict(X_test)
                acc_stacking = accuracy_score(y_test, y_pred_stacking)
                results['stacking_ensemble'] = acc_stacking
                print(f"  {'stacking':15}: {acc_stacking:.4f}")
            except Exception as e:
                print(f"  Stacking error: {e}")
                results['stacking_ensemble'] = 0.0
        
        # Najlepszy model
        best_model_name = max(results, key=results.get)
        best_accuracy = results[best_model_name]
        
        print(f"\nNAJLEPSZY MODEL: {best_model_name.upper()}")
        print(f"ACCURACY: {best_accuracy:.4f}")
        
        return results, best_model_name
    
    def detailed_analysis(self, best_model_name, X_test, y_test):
        """Szczegółowa analiza najlepszego modelu"""
        print(f"\n" + "="*60)
        print(f"SZCZEGÓŁOWA ANALIZA: {best_model_name.upper()}")
        print("="*60)
        
        # Pobierz model
        if best_model_name == 'voting_ensemble':
            best_model = self.voting_ensemble
        elif best_model_name == 'stacking_ensemble':
            best_model = self.stacking_ensemble
        else:
            best_model = self.models[best_model_name]
        
        # Predykcje
        y_pred = best_model.predict(X_test)
        y_pred_proba = best_model.predict_proba(X_test)
        
        accuracy = accuracy_score(y_test, y_pred)
        
        # Classification report
        print("Classification Report:")
        print(classification_report(y_test, y_pred, target_names=self.class_names))
        
        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)
        
        plt.figure(figsize=(12, 10))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                   xticklabels=self.class_names, 
                   yticklabels=self.class_names)
        plt.title(f'Confusion Matrix - {best_model_name.upper()}\nAccuracy: {accuracy:.4f}')
        plt.xlabel('Predicted')
        plt.ylabel('Actual')
        plt.tight_layout()
        plt.show()
        
        # Feature importance (jeśli dostępne)
        self.analyze_feature_importance(best_model, best_model_name)
        
        # Error analysis
        self.error_analysis(y_test, y_pred, y_pred_proba)
        
        return accuracy, best_model
    
    def analyze_feature_importance(self, model, model_name):
        """Analiza ważności cech"""
        print("\nAnaliza ważności cech:")
        
        # Feature importance dla tree-based models
        if hasattr(model, 'feature_importances_'):
            importances = model.feature_importances_
            top_indices = np.argsort(importances)[-15:]  # Top 15
            
            # Nazwy grup cech
            feature_groups = []
            for idx in top_indices:
                if idx < 16:
                    group = f"gabor_{idx}"
                elif idx < 116:  # texture features (~100)
                    group = f"texture_{idx-16}"
                elif idx < 131:  # shape features (~15)
                    group = f"shape_{idx-116}"
                elif idx < 157:  # statistical features (~26)
                    group = f"stats_{idx-131}"
                elif idx < 175:  # spatial features (~18)
                    group = f"spatial_{idx-157}"
                else:
                    group = f"pixel_{idx-175}"
                
                feature_groups.append((group, importances[idx]))
            
            print("Top 15 najważniejszych cech:")
            for group, importance in reversed(feature_groups):
                print(f"  {group:20}: {importance:.4f}")
        
        # Dla ensemble - pokaż wagi modeli
        elif hasattr(model, 'estimators_'):
            if hasattr(model, 'weights') or model_name == 'voting_ensemble':
                print("Wagi modeli w ensemble:")
                for i, (name, _) in enumerate(model.estimators_):
                    weight = getattr(model, 'weights', [1.0] * len(model.estimators_))[i]
                    print(f"  {name:15}: {weight:.4f}")
    
    def error_analysis(self, y_test, y_pred, y_pred_proba):
        """Analiza błędów"""
        print("\nAnaliza błędów:")
        
        # Confidence analysis
        max_proba = np.max(y_pred_proba, axis=1)
        correct = (y_pred == y_test)
        
        # Błędy wysokiej pewności (overconfident errors)
        high_conf_errors = (max_proba > 0.8) & (~correct)
        if np.sum(high_conf_errors) > 0:
            print(f"Błędy wysokiej pewności: {np.sum(high_conf_errors)}")
        
        # Błędy niskiej pewności (uncertain errors)
        low_conf_errors = (max_proba < 0.6) & (~correct)
        if np.sum(low_conf_errors) > 0:
            print(f"Błędy niskiej pewności: {np.sum(low_conf_errors)}")
        
        # Najczęstsze błędy
        misclassified_idx = np.where(~correct)[0]
        if len(misclassified_idx) > 0:
            error_pairs = [(self.class_names[y_test[i]], self.class_names[y_pred[i]]) 
                          for i in misclassified_idx]
            error_counts = Counter(error_pairs)
            
            print("Najczęstsze błędne klasyfikacje:")
            for (true_class, pred_class), count in error_counts.most_common(7):
                print(f"  {true_class} → {pred_class}: {count}")
    
    def performance_summary(self, final_accuracy):
        """Podsumowanie wydajności"""
        print(f"\n" + "="*60)
        print("FINAL PERFORMANCE SUMMARY")
        print("="*60)
        
        if final_accuracy >= 0.85:
            grade = "EXCELLENT"
            message = "Model gotowy do produkcji!"
        elif final_accuracy >= 0.80:
            grade = "VERY GOOD"
            message = "Model bardzo przydatny z małymi ograniczeniami"
        elif final_accuracy >= 0.75:
            grade = "GOOD"
            message = "Model użyteczny, ale może wymagać dodatkowej walidacji"
        elif final_accuracy >= 0.70:
            grade = "ACCEPTABLE"
            message = "Model przeciętny, rozważ ulepszenia"
        else:
            grade = "NEEDS IMPROVEMENT"
            message = "Model wymaga znacznych ulepszeń"
        
        print(f"Final Accuracy: {final_accuracy:.4f}")
        print(f"Grade: {grade}")
        print(f"Recommendation: {message}")
        
        # Rekomendacje dalszych ulepszeń
        if final_accuracy < 0.85:
            print(f"\nSuggestions for improvement:")
            if final_accuracy < 0.75:
                print("- Collect more diverse training data")
                print("- Check label quality and consistency")
                print("- Try deep learning models (CNN)")
            print("- Fine-tune hyperparameters more extensively")
            print("- Consider class-specific augmentation strategies")
            print("- Analyze misclassified examples manually")

def save_ultimate_model(classifier, best_model, best_model_name, final_accuracy, 
                       hyperparameters=None, filepath=None):
    """
    Zapisuje model z wszystkimi komponentami potrzebnymi do predykcji
    """
    if filepath is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f'ultimate_building_classifier_{best_model_name}_{final_accuracy:.3f}_{timestamp}.pkl'
    
    # Przygotowanie danych do zapisania
    model_package = {
        # Model i jego nazwa
        'best_model': best_model,
        'model_name': best_model_name,
        
        # Preprocessing components
        'label_encoder': classifier.label_encoder,
        'scaler': classifier.scaler,
        'feature_selector': classifier.feature_selector,
        'pca': classifier.pca,
        
        # Dane o klasach
        'class_names': classifier.class_names,
        
        # Wyniki
        'accuracy': final_accuracy,
        'cv_scores': classifier.cv_scores,
        
        # Feature extractor
        'feature_extractor': classifier.feature_extractor,
        
        # Metadane
        'hyperparameters': hyperparameters or {},
        'timestamp': datetime.now().isoformat(),
        'model_type': 'sklearn_ensemble',
        'img_size': classifier.img_size,
        
        # Wszystkie modele (opcjonalnie)
        'all_models': classifier.models,
        
        # Ensemble models
        'voting_ensemble': getattr(classifier, 'voting_ensemble', None),
        'stacking_ensemble': getattr(classifier, 'stacking_ensemble', None)
    }
    
    # Zapisanie
    with open(filepath, 'wb') as f:
        pickle.dump(model_package, f)
    
    print(f"Model pakiet zapisany: {filepath}")
    print(f"Zawartość pakietu:")
    print(f"  - Najlepszy model: {best_model_name}")
    print(f"  - Accuracy: {final_accuracy:.4f}")
    print(f"  - Klasy: {len(classifier.class_names)}")
    print(f"  - Feature extractor: UltimateFeatureExtractor")
    print(f"  - Preprocessing: scaler, feature_selector, PCA")
    
    return filepath

def load_ultimate_model(filepath):
    """
    Ładuje kompletny pakiet modelu
    """
    print(f"Ładowanie modelu z: {filepath}")
    
    with open(filepath, 'rb') as f:
        model_package = pickle.load(f)
    
    print(f"Załadowano model:")
    print(f"  - Model: {model_package['model_name']}")
    print(f"  - Accuracy: {model_package['accuracy']:.4f}")
    print(f"  - Klasy: {model_package['class_names']}")
    print(f"  - Timestamp: {model_package['timestamp']}")
    
    return model_package

def predict_with_ultimate_model(model_package, image_path_or_array):
    """
    Wykonuje predykcję za pomocą załadowanego modelu
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
        # Ścieżka do pliku
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

def main():
    """Ultimate main function z prawidłowym zapisywaniem"""
    print("ULTIMATE BUILDING CLASSIFIER")
    print("="*60)
    
    DATA_DIR = 'ml_dataset'
    
    # Sprawdź istnienie datasetu
    if not os.path.exists(DATA_DIR):
        print(f"Błąd: Katalog {DATA_DIR} nie istnieje!")
        return
    
    # Parametry treningu
    IMG_SIZE = 128
    AUGMENT_FACTOR = 4
    MAX_IMAGES_PER_CLASS = 150
    INTENSIVE_TUNING = True
    
    # Hiperparametry do zapisania
    hyperparameters = {
        'img_size': IMG_SIZE,
        'augment_factor': AUGMENT_FACTOR,
        'max_images_per_class': MAX_IMAGES_PER_CLASS,
        'intensive_tuning': INTENSIVE_TUNING,
        'test_size': 0.15,
        'min_class_size': 6,
        'feature_selection': True,
        'pca_variance': 0.98,
        'cv_folds': 5,
        'model_types': ['rf', 'xgb', 'et', 'svm'],
        'ensemble_methods': ['voting', 'stacking']
    }
    
    print(f"Parametry:")
    print(f"- Image size: {IMG_SIZE}x{IMG_SIZE}")
    print(f"- Augmentation factor: {AUGMENT_FACTOR}x")
    print(f"- Max images per class: {MAX_IMAGES_PER_CLASS}")
    print(f"- Intensive tuning: {INTENSIVE_TUNING}")
    
    # Inicjalizacja
    classifier = UltimateBuildingClassifier(
        data_dir=DATA_DIR, 
        img_size=IMG_SIZE
    )
    
    # Ładowanie danych
    print(f"\n" + "="*60)
    print("LOADING & PREPROCESSING")
    print("="*60)
    
    train_data, test_data = classifier.load_and_preprocess_dataset(
        max_images_per_class=MAX_IMAGES_PER_CLASS,
        augment_factor=AUGMENT_FACTOR,
        min_class_size=6
    )
    
    X_train, y_train = train_data
    X_test, y_test = test_data
    
    # Preprocessing
    X_train_processed, X_test_processed = classifier.advanced_preprocessing(
        X_train, X_test, y_train, use_feature_selection=True
    )
    
    print(f"Final feature dimensions: {X_train_processed.shape}")
    
    # Trenowanie
    print(f"\n" + "="*60)
    print("ULTIMATE TRAINING")
    print("="*60)
    
    classifier.train_ultimate_models(
        X_train_processed, y_train, 
        intensive_tuning=INTENSIVE_TUNING
    )
    
    # Ensemble
    if classifier.create_ultimate_ensemble(X_train_processed, y_train):
        print("Ultimate ensemble created successfully")
    
    # Ewaluacja
    results, best_model_name = classifier.evaluate_ultimate_models(
        X_test_processed, y_test
    )
    
    # Analiza szczegółowa
    final_accuracy, best_model = classifier.detailed_analysis(
        best_model_name, X_test_processed, y_test
    )
    
    # Podsumowanie
    classifier.performance_summary(final_accuracy)
    
    # ZAPISANIE MODELU
    print(f"\n" + "="*60)
    print("SAVING MODEL")
    print("="*60)
    
    model_filepath = save_ultimate_model(
        classifier=classifier,
        best_model=best_model,
        best_model_name=best_model_name,
        final_accuracy=final_accuracy,
        hyperparameters=hyperparameters
    )
    
    print(f"\nTrening zakończony! Final accuracy: {final_accuracy:.4f}")
    print(f"Model zapisany: {model_filepath}")
    
    # PRZYKŁAD UŻYCIA
    print(f"\n" + "="*60)
    print("PRZYKŁAD UŻYCIA")
    print("="*60)
    
    print("# Ładowanie modelu:")
    print(f"model_package = load_ultimate_model('{model_filepath}')")
    print()
    print("# Predykcja:")
    print("result = predict_with_ultimate_model(model_package, 'path_to_image.png')")
    print("print(f\"Predicted: {result['predicted_class']} (confidence: {result['confidence']:.3f})\")")
    
    return model_filepath

# URUCHOM TRENING MODELU
#main()
    
def batch_predict_buildings(model_package, output_dir, csv_output_path=None):
    """
    Wykonuje predykcje dla wszystkich plików PNG w katalogu i zapisuje wyniki do CSV
    
    Args:
        model_package: Załadowany model z load_ultimate_model()
        output_dir: Ścieżka do katalogu z plikami PNG
        csv_output_path: Ścieżka do pliku CSV (opcjonalna)
    
    Returns:
        str: Ścieżka do zapisanego pliku CSV
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
    
    # Przetwarzanie każdego pliku
    for filename in tqdm(png_files, desc="Przetwarzanie obrazów"):
        try:
            # Wyciągnij ID budynku z nazwy pliku
            # Wzorzec: 301701_1_0143_16_BUD.png -> ID = 301701_1_0143_16_BUD
            building_id = os.path.splitext(filename)[0]  # Usuń rozszerzenie
            
            # Pełna ścieżka do pliku
            image_path = os.path.join(output_dir, filename)
            
            # Wykonaj predykcję
            prediction_result = predict_with_ultimate_model(model_package, image_path)
            
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


def predict_buildings_simple(model_package, output_dir, csv_filename='predictions.csv'):
    """
    Uproszczona wersja - tylko ID budynku i predykcja
    """
    
    # Sprawdź katalog
    if not os.path.exists(output_dir):
        raise FileNotFoundError(f"Katalog {output_dir} nie istnieje!")
    
    # Znajdź pliki PNG
    png_files = [f for f in os.listdir(output_dir) if f.lower().endswith('.png')]
    
    if not png_files:
        print(f"Brak plików PNG w {output_dir}")
        return None
    
    print(f"Przetwarzanie {len(png_files)} obrazów...")
    
    # Lista wyników
    results = []
    
    for filename in tqdm(png_files):
        try:
            # ID budynku (nazwa bez rozszerzenia)
            building_id = os.path.splitext(filename)[0]
            
            # Predykcja
            image_path = os.path.join(output_dir, filename)
            result = predict_with_ultimate_model(model_package, image_path)
            
            # Zapisz podstawowe info
            results.append({
                'ID_BUDYNKU': building_id,
                'PREDYKCJA': result['predicted_class']
            })
            
        except Exception as e:
            print(f"Błąd: {filename} - {e}")
            results.append({
                'ID_BUDYNKU': os.path.splitext(filename)[0],
                'PREDYKCJA': 'ERROR'
            })
    
    # Zapisz CSV
    df = pd.DataFrame(results)
    csv_path = os.path.join(output_dir, csv_filename)
    df.to_csv(csv_path, index=False)
    
    print(f"Zapisano: {csv_path}")
    print(f"Predykcje: {df['PREDYKCJA'].value_counts().to_dict()}")
    
    return csv_path

def predict_with_ultimate_model(model_package, image_path_or_array):
    """
    Wykonuje predykcję za pomocą załadowanego modelu
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
        # Ścieżka do pliku
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

def load_ultimate_model(filepath):
    """
    Ładuje kompletny pakiet modelu
    """
    print(f"Ładowanie modelu z: {filepath}")
    
    with open(filepath, 'rb') as f:
        model_package = pickle.load(f)
    
    print(f"Załadowano model:")
    print(f"  - Model: {model_package['model_name']}")
    print(f"  - Accuracy: {model_package['accuracy']:.4f}")
    print(f"  - Klasy: {model_package['class_names']}")
    print(f"  - Timestamp: {model_package['timestamp']}")
    
    return model_package
# PRZYKŁAD UŻYCIA:
"""
# Załaduj model
model_package = load_ultimate_model('ultimate_building_classifier_rf_0.924_20241201_143022.pkl')

# Wersja pełna (z prawdopodobieństwami)
csv_path = batch_predict_buildings(
    model_package=model_package,
    output_dir='OUTPUT_DIR',
    csv_output_path='building_predictions_full.csv'
)

# Wersja prosta (tylko ID i predykcja)
csv_path = predict_buildings_simple(
    model_package=model_package,
    output_dir='OUTPUT_DIR',
    csv_filename='predictions_simple.csv'
)
"""
# project_path = QgsProject.instance().fileName()
# project_directory = Path(project_path).parent
project_directory = os.getcwd()
OUTPUT_DIR = f"{project_directory}/prediction_data"
model_name='ultimate_building_classifier_svm_0.957_20250911_114900.pkl'
model_path = os.path.join(SCRIPTS_PATH, model_name)

model_package = load_ultimate_model(f"{model_path}")
if model_package:
    print("Załadowano model")
    print("Klasyfikacja")
else:
    print("Nie załadowano modelu")
    
csv_path = batch_predict_buildings(
    model_package=model_package,
    output_dir=project_directory,
    csv_output_path='building_predictions_full.csv'
)    