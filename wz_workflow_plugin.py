# -*- coding: utf-8 -*-

# --- Zgodnosc Qt5 (QGIS 3) / Qt6 (QGIS 4) ---
# Musi byc PRZED reszta importow: przywraca QVariant.Int, QVariant.String itd.,
# ktore w Qt6 zostaly usuniete. Patrz qt_compat.py.
from .qt_compat import patch_qvariant
patch_qvariant()

# QAction: w Qt5 mieszka w QtWidgets, w Qt6 przeniesiono go do QtGui.
try:
    from qgis.PyQt.QtGui import QAction        # Qt6 / QGIS 4
except ImportError:
    from qgis.PyQt.QtWidgets import QAction    # Qt5 / QGIS 3

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import Qgis
import os
from .model_downloader import ModelDownloader

class WZWorkflowPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dock_widget = None  # Przechowuj referencję do dock widget
        self.model_downloader = ModelDownloader(self.plugin_dir)

    def tr(self, message):
        return QCoreApplication.translate('WZWorkflow', message)

    def initGui(self):
        """Inicjalizacja GUI"""
        try:
            # Utwórz action dla narzędzia
            icon_path = os.path.join(self.plugin_dir, 'icon.png')
            self.action = QAction(
                QIcon(icon_path) if os.path.exists(icon_path) else QIcon(),
                self.tr('WZ Workflow'),
                self.iface.mainWindow()
            )
            
            # Połącz action z funkcją
            self.action.triggered.connect(self.run)
            
            # Ustaw tooltip
            self.action.setStatusTip(self.tr('Uruchom WZ Workflow'))
            self.action.setWhatsThis(self.tr('Uruchamia WZ Workflow dock widget'))
            
            # Dodaj do menu i paska narzędzi
            self.iface.addToolBarIcon(self.action)
            self.iface.addPluginToMenu(self.tr('&WZ Workflow'), self.action)
            
            print("WZ Workflow Plugin: GUI zainicjalizowane pomyślnie")
            
        except Exception as e:
            print(f"BŁĄD inicjalizacji GUI WZ Workflow: {e}")
            import traceback
            traceback.print_exc()

    def unload(self):
        """Poprawne czyszczenie zasobów podczas deinstalacji"""
        try:
            # Usuń dock widget jeśli istnieje
            if self.dock_widget:
                try:
                    self.dock_widget.close()
                    self.dock_widget.setParent(None)
                    self.dock_widget = None
                except Exception as e:
                    print(f"Problem z zamykaniem dock widget: {e}")
            
            # Usuń z menu i paska narzędzi
            if self.action:
                self.iface.removePluginMenu(self.tr('&WZ Workflow'), self.action)
                self.iface.removeToolBarIcon(self.action)
                self.action = None
            
            print("WZ Workflow Plugin: Zasoby wyczyszczone pomyślnie")
            
        except Exception as e:
            print(f"BŁĄD podczas unload WZ Workflow: {e}")
        finally:
            # Wyczyść referencje
            self.iface = None

    def run(self):
        """Uruchamia główną funkcję"""
        try:
            print("WZ Workflow: Rozpoczynam uruchamianie...")
            
            # Sprawdź czy dock widget już istnieje
            if self.dock_widget and not self.dock_widget.isHidden():
                # Jeśli istnieje i jest widoczny, po prostu go pokaż
                self.dock_widget.show()
                self.dock_widget.raise_()
                self.iface.messageBar().pushMessage(
                    "Info", 
                    "WZ Workflow jest już otwarty", 
                    level=Qgis.MessageLevel.Info,
                    duration=2
                )
                return
            
            # DODAJ TUTAJ - sprawdź modele
            all_present, missing = self.model_downloader.check_models()
        
            if not all_present:
                # Pobierz z dialogiem i progressbarem
                success = self.model_downloader.download_all_missing(self.iface.mainWindow())
                
                if not success:
                    self.iface.messageBar().pushMessage(
                        "Błąd", 
                        "Nie udało się pobrać modeli ML. Wtyczka może nie działać poprawnie.", 
                        level=Qgis.MessageLevel.Critical,
                        duration=5
                    )
                    # Można dodać return żeby nie kontynuować, lub pozwolić kontynuować
                    return

            # Import głównego modułu
            try:
                from .improved_wz_workflow import create_wz_workflow_dock
                print("WZ Workflow: Moduł zaimportowany pomyślnie")
            except ImportError as ie:
                import traceback
                details = traceback.format_exc()
                print(f"BŁĄD importu: {ie}\n{details}")
                self.show_import_error(str(ie), details)
                return
            
            # Utwórz dock widget
            try:
                self.dock_widget = create_wz_workflow_dock()
                print("WZ Workflow: Dock widget utworzony pomyślnie")
                
                self.iface.messageBar().pushMessage(
                    "Sukces", 
                    "WZ Workflow został uruchomiony pomyślnie!", 
                    level=Qgis.MessageLevel.Success,  # Success
                    duration=3
                )
                
            except Exception as ce:
                print(f"BŁĄD tworzenia dock widget: {ce}")
                import traceback
                traceback.print_exc()
                self.show_creation_error(str(ce))
                return
                
        except Exception as e:
            print(f"BŁĄD ogólny w run(): {e}")
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushMessage(
                "Błąd", 
                f"Wystąpił błąd: {str(e)}", 
                level=Qgis.MessageLevel.Critical,  # Critical
                duration=5
            )
    
    def show_import_error(self, error=None, details=None):
        """Pokaż błąd importu"""
        from qgis.PyQt.QtWidgets import QMessageBox
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("WZ Workflow - Błąd importu")
        msg.setText("Nie można zaimportować głównego modułu!")

        info = ""
        if error:
            info += f"Błąd:\n{error}\n\n"
        info += (
            "Najczęstsza przyczyna to brakująca biblioteka Pythona.\n"
            "Wtyczka wymaga m.in.: pandas, scipy, scikit-learn, joblib.\n\n"
            "Zainstaluj brakującą bibliotekę w środowisku Pythona QGIS, np.:\n"
            "    python3 -m pip install pandas"
        )
        msg.setInformativeText(info)
        if details:
            msg.setDetailedText(details)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        
        self.iface.messageBar().pushMessage(
            "Błąd", 
            "Błąd importu modułu WZ Workflow", 
            level=Qgis.MessageLevel.Critical,
            duration=5
        )
    
    def show_creation_error(self, error_msg):
        """Pokaż błąd tworzenia dock widget"""
        from qgis.PyQt.QtWidgets import QMessageBox
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("WZ Workflow - Błąd uruchamiania")
        msg.setText("Nie można utworzyć interfejsu WZ Workflow!")
        msg.setInformativeText(f"Szczegóły błędu:\n{error_msg}")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
