"""
Model Downloader dla wtyczki WZ Workflow
Automatycznie pobiera duże pliki modeli z GitHub Releases
"""
import os
import urllib.request
import json
from pathlib import Path
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsMessageLog, Qgis


class ModelDownloader:
    """Zarządza pobieraniem dużych plików modeli"""
    
    # Konfiguracja - ZAKTUALIZUJ PO UTWORZENIU RELEASE
    GITHUB_RELEASE_URL = "https://github.com/AdrLin/wz-workflow/releases/download/v1.0.0/"
    
    MODELS = {
        "ultimate_building_classifier_svm_0.957_20250911_114900.pkl": {
            "url": GITHUB_RELEASE_URL + "ultimate_building_classifier_svm_0.957_20250911_114900.pkl",
            "size_mb": None,  # nieznany rozmiar
            "description": "Model klasyfikacji budynków (SVM)"
        }
    }
    
    def __init__(self, plugin_dir):
        """
        Args:
            plugin_dir: ścieżka do katalogu wtyczki
        """
        self.plugin_dir = Path(plugin_dir)
        self.models_dir = self.plugin_dir
        
    def check_models(self):
        """
        Sprawdza czy wszystkie wymagane modele są dostępne
        
        Returns:
            tuple: (all_present: bool, missing: list)
        """
        missing = []
        for model_name in self.MODELS.keys():
            model_path = self.models_dir / model_name
            if not model_path.exists():
                missing.append(model_name)
        
        return len(missing) == 0, missing
    
    def download_model(self, model_name, parent=None):
        """
        Pobiera pojedynczy model z progressbarem
        
        Args:
            model_name: nazwa modelu z MODELS dict
            parent: widget rodzica dla dialogu
            
        Returns:
            bool: True jeśli sukces
        """
        if model_name not in self.MODELS:
            QgsMessageLog.logMessage(
                f"Nieznany model: {model_name}",
                "WZ Workflow",
                Qgis.Warning
            )
            return False
        
        model_info = self.MODELS[model_name]
        url = model_info["url"]
        output_path = self.models_dir / model_name
        
        # Utwórz katalog jeśli nie istnieje
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        # Dialog z progressbarem
        size_text = f" ({model_info['size_mb']} MB)" if model_info['size_mb'] else ""
        progress = QProgressDialog(
            f"Pobieranie {model_info['description']}{size_text}...\n\n"
            f"Ten proces może potrwać kilka minut.\n"
            f"Model jest pobierany tylko raz.",
            "Anuluj",
            0,
            100,
            parent
        )
        progress.setWindowTitle("WZ Workflow - Pobieranie modelu")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        def report_progress(block_num, block_size, total_size):
            """Callback dla urllib do aktualizacji progressbara"""
            if progress.wasCanceled():
                raise InterruptedError("Pobieranie anulowane przez użytkownika")
            
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(int(downloaded * 100 / total_size), 100)
                progress.setValue(percent)
                
                # Dodaj informację o MB
                downloaded_mb = downloaded / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                progress.setLabelText(
                    f"Pobieranie {model_info['description']}{size_text}...\n\n"
                    f"Postęp: {downloaded_mb:.1f} / {total_mb:.1f} MB\n"
                    f"Model jest pobierany tylko raz."
                )
        
        try:
            QgsMessageLog.logMessage(
                f"Rozpoczynam pobieranie: {url}",
                "WZ Workflow",
                Qgis.Info
            )
            
            # Pobierz plik
            urllib.request.urlretrieve(url, output_path, report_progress)
            
            progress.setValue(100)
            
            QgsMessageLog.logMessage(
                f"Pomyślnie pobrano: {model_name}",
                "WZ Workflow",
                Qgis.Success
            )
            
            return True
            
        except InterruptedError:
            # Użytkownik anulował
            if output_path.exists():
                output_path.unlink()  # usuń częściowy plik
            
            QgsMessageLog.logMessage(
                f"Pobieranie anulowane: {model_name}",
                "WZ Workflow",
                Qgis.Warning
            )
            return False
            
        except Exception as e:
            # Błąd pobierania
            if output_path.exists():
                output_path.unlink()  # usuń częściowy plik
            
            error_msg = f"Błąd pobierania {model_name}: {str(e)}"
            QgsMessageLog.logMessage(error_msg, "WZ Workflow", Qgis.Critical)
            
            QMessageBox.critical(
                parent,
                "Błąd pobierania modelu",
                f"Nie udało się pobrać modelu:\n\n{error_msg}\n\n"
                f"Sprawdź połączenie internetowe i spróbuj ponownie."
            )
            return False
        
        finally:
            progress.close()
    
    def download_all_missing(self, parent=None):
        """
        Pobiera wszystkie brakujące modele
        
        Args:
            parent: widget rodzica dla dialogów
            
        Returns:
            bool: True jeśli wszystkie pobrane pomyślnie
        """
        all_present, missing = self.check_models()
        
        if all_present:
            return True
        
        # Zapytaj użytkownika
        total_size = sum(
            self.MODELS[m]["size_mb"] for m in missing 
            if self.MODELS[m]["size_mb"]
        )
        
        msg = QMessageBox(parent)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("WZ Workflow - Pobieranie modeli")
        msg.setText(
            "Wtyczka wymaga pobrania modeli uczenia maszynowego."
        )
        msg.setInformativeText(
            f"Brakujące modele ({len(missing)}):\n" +
            "\n".join(f"• {self.MODELS[m]['description']}" for m in missing) +
            f"\n\nŁączny rozmiar: ~{total_size:.0f} MB\n"
            f"Modele zostaną pobrane tylko raz."
        )
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Ok)
        
        if msg.exec_() != QMessageBox.Ok:
            return False
        
        # Pobierz wszystkie
        for model_name in missing:
            success = self.download_model(model_name, parent)
            if not success:
                return False
        
        QMessageBox.information(
            parent,
            "Sukces",
            "Wszystkie modele zostały pobrane pomyślnie!"
        )
        
        return True
    
    def get_model_path(self, model_name):
        """
        Zwraca ścieżkę do modelu, pobierając go jeśli nie istnieje
        
        Args:
            model_name: nazwa modelu
            
        Returns:
            Path or None: ścieżka do modelu lub None jeśli błąd
        """
        model_path = self.models_dir / model_name
        
        if model_path.exists():
            return model_path
        
        # Spróbuj pobrać
        success = self.download_model(model_name)
        
        if success and model_path.exists():
            return model_path
        
        return None
