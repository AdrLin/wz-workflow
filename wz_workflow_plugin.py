# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QCoreApplication
import os

class WZWorkflowPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dock_widget = None  # Przechowuj referencję do dock widget
        
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
                    level=0,
                    duration=2
                )
                return
            
            # Import głównego modułu
            try:
                from .improved_wz_workflow import create_wz_workflow_dock
                print("WZ Workflow: Moduł zaimportowany pomyślnie")
            except ImportError as ie:
                print(f"BŁĄD importu: {ie}")
                self.show_import_error()
                return
            
            # Utwórz dock widget
            try:
                self.dock_widget = create_wz_workflow_dock()
                print("WZ Workflow: Dock widget utworzony pomyślnie")
                
                self.iface.messageBar().pushMessage(
                    "Sukces", 
                    "WZ Workflow został uruchomiony pomyślnie!", 
                    level=3,  # Success
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
                level=2,  # Critical
                duration=5
            )
    
    def show_import_error(self):
        """Pokaż błąd importu"""
        from qgis.PyQt.QtWidgets import QMessageBox
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("WZ Workflow - Błąd importu")
        msg.setText("Nie można zaimportować głównego modułu!")
        msg.setInformativeText(
            "Sprawdź czy wszystkie pliki wtyczki są prawidłowo zainstalowane:\n"
            "- improved_wz_workflow.py\n"
            "- wz_workflow_plugin.py\n"
            "- __init__.py\n"
            "- metadata.txt"
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
        
        self.iface.messageBar().pushMessage(
            "Błąd", 
            "Błąd importu modułu WZ Workflow", 
            level=2,
            duration=5
        )
    
    def show_creation_error(self, error_msg):
        """Pokaż błąd tworzenia dock widget"""
        from qgis.PyQt.QtWidgets import QMessageBox
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("WZ Workflow - Błąd uruchamiania")
        msg.setText("Nie można utworzyć interfejsu WZ Workflow!")
        msg.setInformativeText(f"Szczegóły błędu:\n{error_msg}")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()