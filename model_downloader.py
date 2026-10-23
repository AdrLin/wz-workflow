"""
Model Downloader dla wtyczki WZ Workflow
Automatycznie pobiera duże pliki modeli z GitHub Releases
"""
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsMessageLog, Qgis


class ModelDownloader:
    """Zarządza pobieraniem dużych plików modeli"""
    
    # Konfiguracja - ZAKTUALIZUJ PO UTWORZENIU RELEASE
    GITHUB_RELEASE_URL = "https://github.com/AdrLin/wz-workflow/releases/download/v2.0.0/"

    MODELS = {
        "best_dachy_efficient.weights.h5": {
            "url": GITHUB_RELEASE_URL + "best_dachy_efficient.weights.h5",
            "size_mb": 39,
            "description": "Model klasyfikacji dachów (CNN, EfficientNetV2)"
        },
        "rf_pbc_ostrow.pkl": {
            "url": GITHUB_RELEASE_URL + "rf_pbc_ostrow.pkl",
            "size_mb": 154,
            "description": "Model klasyfikacji powierzchni biologicznie czynnej (Random Forest)"
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
                Qgis.MessageLevel.Warning
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
        progress.setWindowModality(Qt.WindowModality.WindowModal)
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
                Qgis.MessageLevel.Info
            )
            
            # Walidacja schematu URL — dopuszczamy WYLACZNIE https.
            # Chroni przed file:// i innymi schematami (Bandit B310).
            parsed = urlparse(url)
            if parsed.scheme != "https":
                raise ValueError(
                    f"Niedozwolony schemat URL: '{parsed.scheme}'. "
                    f"Modele pobierane sa wylacznie przez https."
                )
            if parsed.netloc != "github.com":
                raise ValueError(
                    f"Niedozwolony host: '{parsed.netloc}'. "
                    f"Modele pobierane sa wylacznie z github.com."
                )

            # Pobieranie strumieniowe (bez urlretrieve — Bandit B310)
            self._download_https(url, output_path, report_progress)

            progress.setValue(100)
            
            QgsMessageLog.logMessage(
                f"Pomyślnie pobrano: {model_name}",
                "WZ Workflow",
                Qgis.MessageLevel.Success
            )
            
            return True
            
        except InterruptedError:
            # Użytkownik anulował
            if output_path.exists():
                output_path.unlink()  # usuń częściowy plik
            
            QgsMessageLog.logMessage(
                f"Pobieranie anulowane: {model_name}",
                "WZ Workflow",
                Qgis.MessageLevel.Warning
            )
            return False
            
        except Exception as e:
            # Błąd pobierania
            if output_path.exists():
                output_path.unlink()  # usuń częściowy plik
            
            error_msg = f"Błąd pobierania {model_name}: {str(e)}"
            QgsMessageLog.logMessage(error_msg, "WZ Workflow", Qgis.MessageLevel.Critical)
            
            QMessageBox.critical(
                parent,
                "Błąd pobierania modelu",
                f"Nie udało się pobrać modelu:\n\n{error_msg}\n\n"
                f"Sprawdź połączenie internetowe i spróbuj ponownie."
            )
            return False
        
        finally:
            progress.close()
    
    def _download_https(self, url, output_path, report_progress):
        """
        Pobiera plik przez https strumieniowo.

        Zastepuje urllib.request.urlretrieve, ktore Bandit flaguje (B310),
        bo pozwalaloby na schematy file:// i inne. Tutaj otwieramy polaczenie
        jawnie, po wczesniejszej walidacji schematu i hosta.
        """
        req = urllib.request.Request(url, headers={"User-Agent": "WZ-Workflow-QGIS"})
        block_size = 8192
        block_num = 0

        with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310
            total_size = int(response.headers.get("Content-Length", 0))
            report_progress(0, block_size, total_size)

            with open(output_path, "wb") as f:
                while True:
                    chunk = response.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    block_num += 1
                    report_progress(block_num, block_size, total_size)

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
        msg.setIcon(QMessageBox.Icon.Information)
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
        msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Ok)
        
        if msg.exec() != QMessageBox.StandardButton.Ok:
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
