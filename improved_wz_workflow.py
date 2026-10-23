import os
import runpy
import json
from datetime import datetime
from qgis.PyQt.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QListWidget, QMessageBox, 
                             QTextEdit, QFrame, QScrollArea,
                             QGroupBox, QSizePolicy, QSpacerItem, QComboBox,
                             QDialog, QDialogButtonBox, QFormLayout, QLineEdit)

from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject
from qgis.core import (QgsVectorFileWriter,
                       QgsField, QgsVectorLayer, QgsProcessingContext,
                       QgsProcessingFeedback,QgsCoordinateTransformContext
)
from qgis.PyQt.QtCore import QVariant
from pathlib import Path

# pandas jest ciezka biblioteka i NIE musi byc dostepna, zeby wtyczka sie
# zaladowala — uzywamy jej tylko w kilku krokach (eksport/import Excela).
# Import leniwy: wtyczka wstaje nawet bez pandas, a brak biblioteki zglasza
# sie czytelnym komunikatem dopiero przy kroku, ktory jej wymaga.
pd = None
def _ensure_pandas():
    """Zwraca modul pandas; jesli go brak — rzuca czytelny blad."""
    global pd
    if pd is None:
        try:
            import pandas as _pd
            pd = _pd
        except ImportError as exc:
            raise ImportError(
                "Ten krok wymaga biblioteki 'pandas', ktorej nie znaleziono "
                "w srodowisku Pythona QGIS.\\n"
                "Zainstaluj ja, np.:  python3 -m pip install pandas"
            ) from exc
    return pd

# sip: w Qt6 nie istnieje samodzielny modul `sip` (jest PyQt6.sip).
# Kazda sciezka moze zawiesc — brak sip nie moze wywalac calej wtyczki.
sip = None
for _sip_source in ("qgis.PyQt", "PyQt6", "PyQt5"):
    try:
        _mod = __import__(_sip_source, fromlist=["sip"])
        sip = _mod.sip
        break
    except (ImportError, AttributeError):
        continue

if sip is None:
    # Ostatnia deska ratunku: samodzielny modul `sip` (stare srodowiska Qt5)
    try:
        import sip  # noqa: F811
    except ImportError:
        # Brak sip — wtyczka MUSI dzialac dalej. sip.isdeleted() sluzy tylko
        # do sprawdzania, czy obiekt Qt zostal usuniety; zakladamy, ze zyje.
        class _SipFallback:
            @staticmethod
            def isdeleted(obj):
                return False
        sip = _SipFallback()
        
# Import bezpieczny dla iface
try:
    from qgis.utils import iface
    IFACE_AVAILABLE = True
except ImportError:
    print("UWAGA: iface nie jest dostępne")
    iface = None
    IFACE_AVAILABLE = False

def safe_iface_call(method_name, *args, **kwargs):
    """Bezpieczne wywołanie metod iface"""
    if not IFACE_AVAILABLE or not iface:
        print(f"UWAGA: Nie można wywołać iface.{method_name} - iface niedostępne")
        return None
    
    try:
        method = getattr(iface, method_name)
        return method(*args, **kwargs)
    except Exception as e:
        print(f"BŁĄD wywołania iface.{method_name}: {e}")
        return None

# Ścieżki
SCRIPTS_PATH = os.path.dirname(os.path.abspath(__file__))


def _narzedzia_wyboru():
    """Leniwy import modulu narzedzia_wyboru.py (analogicznie do plan_ogolny)."""
    try:
        from . import narzedzia_wyboru as _nw
        return _nw
    except Exception:  # nosec B110
        pass
    import importlib.util
    sciezka = os.path.join(SCRIPTS_PATH, "narzedzia_wyboru.py")
    if not os.path.exists(sciezka):
        raise ImportError(f"Brak pliku {sciezka}")
    spec = importlib.util.spec_from_file_location("wz_narzedzia_wyboru", sciezka)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plan_ogolny():
    """
    Leniwy import modulu plan_ogolny.py (odczyt strefy planistycznej + automat
    wyborow w analizie opisowej). Import wzgledny dziala, gdy modul jest czescia
    pakietu wtyczki; fallback laduje plik po sciezce (przydatne przy runpy).
    """
    try:
        from . import plan_ogolny as _pog
        return _pog
    except Exception:  # nosec B110
        pass
    import importlib.util
    sciezka = os.path.join(SCRIPTS_PATH, "plan_ogolny.py")
    if not os.path.exists(sciezka):
        raise ImportError(f"Brak pliku {sciezka}")
    spec = importlib.util.spec_from_file_location("wz_plan_ogolny", sciezka)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
CHECKPOINT_FILE = os.path.join(SCRIPTS_PATH, 'workflow_checkpoint.json')

# Style CSS
MODERN_STYLE = """
QDockWidget {
    background-color: #f8f9fa;
    border: 1px solid #dee2e6;
    font-family: 'Segoe UI', Arial, sans-serif;
}

QDockWidget::title {
    background-color: #007bff;
    color: white;
    padding: 8px;
    font-weight: bold;
    font-size: 14px;
    text-align: center;
}

QPushButton {
    background-color: #007bff;
    color: white;
    border: none;
    padding: 10px 15px;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 500;
    min-height: 35px;
}

QPushButton:hover {
    background-color: #0056b3;
}

QPushButton:pressed {
    background-color: #004085;
}

QPushButton:disabled {
    background-color: #6c757d;
    color: #adb5bd;
}

QPushButton.secondary {
    background-color: #6c757d;
}

QPushButton.secondary:hover {
    background-color: #545b62;
}

QPushButton.danger {
    background-color: #dc3545;
}

QPushButton.danger:hover {
    background-color: #c82333;
}

QPushButton.success {
    background-color: #28a745;
}

QPushButton.success:hover {
    background-color: #1e7e34;
}

QTextEdit {
    background-color: white;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 8px;
    font-size: 11px;
    font-family: 'Consolas', 'Courier New', monospace;
}

QLabel {
    color: #495057;
    font-size: 12px;
}

QLabel.title {
    font-size: 16px;
    font-weight: bold;
    color: #212529;
    padding: 5px 0;
}

QLabel.subtitle {
    font-size: 14px;
    font-weight: 600;
    color: #495057;
    padding: 3px 0;
}

QLabel.info {
    color: #17a2b8;
    font-weight: 500;
}

QLabel.warning {
    color: #ffc107;
    font-weight: 500;
}

QLabel.success {
    color: #28a745;
    font-weight: 500;
}

QLabel.error {
    color: #dc3545;
    font-weight: 500;
}

QGroupBox {
    font-weight: bold;
    border: 2px solid #ced4da;
    border-radius: 5px;
    margin-top: 10px;
    padding-top: 10px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px 0 5px;
    color: #495057;
}

QListWidget {
    border: 1px solid #ced4da;
    border-radius: 4px;
    background-color: white;
    font-size: 11px;
}

QFrame.separator {
    background-color: #dee2e6;
    max-height: 1px;
    margin: 5px 0;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QComboBox {
    background-color: white;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 5px;
    min-height: 30px;
    color: #495057;
}

QComboBox:hover {
    border-color: #007bff;
}

QComboBox::drop-down {
    border: none;
}

QComboBox QAbstractItemView {
    background-color: white;
    border: 1px solid #ced4da;
    selection-background-color: #e3f2fd;
    selection-color: #007bff;
    color: #495057;
}

QComboBox QAbstractItemView::item {
    padding: 5px;
    min-height: 25px;
    color: #495057;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #f0f0f0;
    color: #007bff;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #e3f2fd;
    color: #007bff;
}

QLineEdit {
    background-color: white;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 5px;
    min-height: 25px;
}

QLineEdit:focus {
    border-color: #007bff;
}
"""


def get_project_directory():
    project_path = QgsProject.instance().fileName()
    if not project_path:
        return None
    return Path(project_path).parent


def utworz_folder(sciezka_folderu):
    try:
        os.makedirs(sciezka_folderu, exist_ok=True)
        print(f"Folder utworzony lub już istnieje: {sciezka_folderu}")
    except Exception as e:
        print(f"Błąd podczas tworzenia folderu: {e}")


def zapisz_warstwe_do_gpkg(layer, output_directory, layer_name=None):
    """
    Uniwersalna funkcja do zapisu warstwy do GeoPackage z nadpisywaniem
    
    Args:
        layer: Warstwa do zapisania (QgsVectorLayer)
        output_directory: Katalog docelowy (Path lub str)
        layer_name: Opcjonalna nazwa warstwy (jeśli None, użyje layer.name())
    
    Returns:
        QgsVectorLayer: Zapisana i wczytana warstwa lub None w przypadku błędu
    """
    if layer_name is None:
        layer_name = layer.name()
    
    output_path = str(Path(output_directory) / f"{layer_name}.gpkg")
    
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.fileEncoding = 'UTF-8'
    options.layerName = layer_name
    options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, 
        output_path, 
        QgsCoordinateTransformContext(), 
        options
    )
    
    if result[0] == QgsVectorFileWriter.WriterError.NoError:
        print(f"✅ Warstwa '{layer_name}' zapisana do: {output_path}")
        
        QgsProject.instance().removeMapLayer(layer)
        
        saved_layer = QgsVectorLayer(f"{output_path}|layername={layer_name}", layer_name, "ogr")
        if saved_layer.isValid():
            QgsProject.instance().addMapLayer(saved_layer)
            return saved_layer
        else:
            print(f"❌ Błąd podczas wczytywania warstwy '{layer_name}'")
            return None
    else:
        print(f"❌ Błąd podczas zapisywania warstwy '{layer_name}': {result[1]}")
        return None



def remove_memory_layers():
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.dataProvider().name() == 'memory':
            QgsProject.instance().removeMapLayer(lyr.id())


class LineMeasurementController:
    def __init__(self):
        self.measurement_layer = None
        
    def create_line_layer(self):
        try:
            self.measurement_layer = QgsVectorLayer('LineString?crs=EPSG:2177', 'linie_zabudowy', 'memory')
            
            if not self.measurement_layer.isValid():
                print("❌ Błąd: Nie udało się utworzyć warstwy!")
                return None
            
            provider = self.measurement_layer.dataProvider()
            fields = [QgsField('distance', QVariant.Double, 'double', 10, 2)]
            provider.addAttributes(fields)
            self.measurement_layer.updateFields()
            QgsProject.instance().addMapLayer(self.measurement_layer)
            self.measurement_layer.startEditing()
            
            print(f"✅ Utworzono warstwę '{self.measurement_layer.name()}' w trybie edycji")
            return self.measurement_layer
            
        except Exception as e:
            print(f"❌ Błąd podczas tworzenia warstwy: {e}")
            return None
    
    def setup_auto_length_calculation(self):
        if not self.measurement_layer or not self.measurement_layer.isValid():
            return
            
        try:
            distance_field_index = self.measurement_layer.fields().indexFromName('distance')
            
            if distance_field_index == -1:
                print("❌ Błąd: Nie znaleziono pola 'distance'")
                return
            
            try:
                self.measurement_layer.featureAdded.disconnect()
                self.measurement_layer.geometryChanged.disconnect()
            except Exception:
                # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
                pass  # nosec B110
            
            self.measurement_layer.featureAdded.connect(self.safe_on_feature_added)
            self.measurement_layer.geometryChanged.connect(self.safe_on_geometry_changed)
            
            print("✅ Skonfigurowano automatyczne obliczanie długości")
            
        except Exception as e:
            print(f"❌ Błąd podczas konfiguracji sygnałów: {e}")
    
    def safe_on_feature_added(self, feature_id):
        try:
            if not self.measurement_layer or not self.measurement_layer.isValid() or not self.measurement_layer.isEditable():
                return
                
            feature = self.measurement_layer.getFeature(feature_id)
            if not feature.hasGeometry():
                return
            
            distance_field_index = self.measurement_layer.fields().indexFromName('distance')
            if distance_field_index == -1:
                return
            
            length = feature.geometry().length()
            self.measurement_layer.changeAttributeValue(feature_id, distance_field_index, round(length, 2))
            print(f"📏 Dodano linię o długości: {round(length, 2)} m")
            
        except Exception as e:
            print(f"BŁĄD w safe_on_feature_added: {e}")
    
    def safe_on_geometry_changed(self, feature_id, geometry):
        try:
            if not self.measurement_layer or not self.measurement_layer.isValid():
                return
            if not self.measurement_layer.isEditable() or not geometry:
                return
            
            distance_field_index = self.measurement_layer.fields().indexFromName('distance')
            if distance_field_index == -1:
                return
            
            length = geometry.length()
            self.measurement_layer.changeAttributeValue(feature_id, distance_field_index, round(length, 2))
            print(f"🔄 Zaktualizowano długość: {round(length, 2)} m")
            
        except Exception as e:
            print(f"❌ Błąd w safe_on_geometry_changed: {e}")
    
    def start_measurement_process(self):
        try:
            if not self.create_line_layer():
                return False
                
            self.setup_auto_length_calculation()
            iface.setActiveLayer(self.measurement_layer)
            
            print("🚀 Rozpoczęto proces rysowania linii zabudowy")
            return True
            
        except Exception as e:
            print(f"❌ Błąd podczas uruchamiania procesu: {e}")
            return False
    
    def finish_measurement(self):
        try:
            print("🔄 Kończenie pomiarów...")
            
            if self.measurement_layer and self.measurement_layer.isValid():
                try:
                    self.measurement_layer.featureAdded.disconnect()
                    self.measurement_layer.geometryChanged.disconnect()
                    print("✅ Sygnały odłączone")
                except Exception as signal_error:
                    print(f"⚠️ Problem z odłączaniem sygnałów: {signal_error}")
                
                if self.measurement_layer.isEditable():
                    self.measurement_layer.commitChanges()
                    print("✅ Zmiany zapisane w warstwie")
            
            print("✅ Zakończono pomiary linii zabudowy")
            
            try:
                iface.messageBar().pushSuccess("Zakończono", "Pomiary linii zabudowy zostały zapisane!")
            except Exception as msg_error:
                print(f"⚠️ Problem z messageBar: {msg_error}")
            
        except Exception as e:
            print(f"❌ Błąd podczas zakończenia: {e}")
            import traceback
            traceback.print_exc()

line_controller = None


def setup_processing():
    context = QgsProcessingContext()
    feedback = QgsProcessingFeedback()
    return context, feedback


class StatusIndicator(QLabel):
    def __init__(self, text="", status="info"):
        super().__init__(text)
        self.set_status(status)
    
    def set_status(self, status):
        if status == "info":
            self.setProperty("class", "info")
        elif status == "warning":
            self.setProperty("class", "warning")
        elif status == "success":
            self.setProperty("class", "success")
        elif status == "error":
            self.setProperty("class", "error")
        self.style().unpolish(self)
        self.style().polish(self)


class ModernButton(QPushButton):
    def __init__(self, text="", button_type="primary"):
        super().__init__(text)
        self.set_type(button_type)
    
    def set_type(self, button_type):
        if button_type == "secondary":
            self.setProperty("class", "secondary")
        elif button_type == "success":
            self.setProperty("class", "success")
        elif button_type == "danger":
            self.setProperty("class", "danger")
        self.style().unpolish(self)
        self.style().polish(self)



# ==================== WALIDACJA I MAPOWANIE PÓL - NOWE FUNKCJE ====================

class FieldMappingDialog(QDialog):
    """Dialog do mapowania pól warstwy"""
    
    def __init__(self, layer, required_fields, layer_type="warstwa", parent=None):
        super().__init__(parent)
        self.layer = layer
        self.required_fields = required_fields
        self.layer_type = layer_type
        self.field_mapping = {}
        
        self.setWindowTitle(f"Mapowanie pól: {layer.name()}")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        
        self.init_ui()
    
    def init_ui(self):
        """Inicjalizacja interfejsu"""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        # Header
        header_label = QLabel(
            f"⚠️ Warstwa <b>{self.layer.name()}</b> nie zawiera wszystkich wymaganych pól.\n\n"
            f"Zmapuj istniejące pola do wymaganych pól systemu:"
        )
        header_label.setWordWrap(True)
        header_label.setStyleSheet("padding: 10px; background-color: #fff3cd; border-radius: 5px; border: 1px solid #ffc107;")
        layout.addWidget(header_label)
        
        # Pobierz dostępne pola
        available_fields = [field.name() for field in self.layer.fields()]
        
        # Form layout dla mapowania
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        self.combo_boxes = {}
        
        for required_field in self.required_fields:
            combo = QComboBox()
            combo.setMinimumHeight(35)
            
            # Dodaj opcję "Brak - utwórz nowe pole"
            combo.addItem("❌ Brak - utwórz nowe pole", None)
            
            # Dodaj dostępne pola
            for field_name in available_fields:
                combo.addItem(f"✓ {field_name}", field_name)
            
            # Spróbuj znaleźć automatyczne dopasowanie
            auto_match = self.find_best_match(required_field, available_fields)
            if auto_match:
                index = combo.findData(auto_match)
                if index >= 0:
                    combo.setCurrentIndex(index)
            
            form_layout.addRow(f"<b>{required_field}:</b>", combo)
            self.combo_boxes[required_field] = combo
        
        layout.addLayout(form_layout)
        
        # Info label
        info_label = QLabel(
            "💡 <i>Jeśli wybierzesz 'Brak - utwórz nowe pole', system utworzy nowe pole "
            "i wypełni je odpowiednimi danymi.</i>"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(info_label)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText("✓ Zatwierdź mapowanie")
        ok_button.setMinimumHeight(40)
        
        layout.addWidget(button_box)
        
        self.setLayout(layout)
    
    
    def find_best_match(self, required_field, available_fields):
        """Znajdź najlepsze dopasowanie pola"""
        required_lower = required_field.lower()
        
        # Dokładne dopasowanie
        for field in available_fields:
            if field.lower() == required_lower:
                return field
        
        # Częściowe dopasowanie
        search_terms = {
            'ID_DZIALKI': ['id', 'dzialki', 'iddzialki', 'identyfikator'],
            'NUMER_DZIALKI': ['numer', 'nr', 'dzialki', 'numerdzialki'],
            'NUMER_OBREBU': ['obreb', 'obrebu', 'numerob'],
            'POLE_EWIDENCYJNE': ['pole', 'pow', 'area', 'powierzchnia', 'ewidencyjne'],
            'KONDYGNACJE_NADZIEMNE': ['kondygnacje', 'kond', 'nadziemne', 'nadz', 'nadziemnych'],
            'KONDYGNACJE_PODZIEMNE': ['kondygnacje', 'kond', 'podziemne', 'podz', 'podziemnych'],
            'ID_BUDYNKU': ['id', 'budynku', 'idbudynku', 'identyfikator'],
            'rodzaj_zabudowy': ['rodzaj', 'zabudowy', 'funkcja', 'typ']
        }
        
        terms = search_terms.get(required_field, [])
        
        for field in available_fields:
            field_lower = field.lower()
            if any(term in field_lower for term in terms):
                return field
        
        return None
    
    def validate_and_accept(self):
        """Walidacja i zatwierdzenie"""
        for required_field, combo in self.combo_boxes.items():
            mapped_field = combo.currentData()
            self.field_mapping[required_field] = mapped_field
        
        self.accept()
    
    def get_field_mapping(self):
        """Zwróć mapowanie pól"""
        return self.field_mapping


def validate_and_fix_dzialki_layer(layer, project_directory):
    """
    Walidacja i naprawa struktury warstwy działek
    WERSJA 2.2 - z REPROJEKCJĄ do CRS projektu
    
    Returns:
        tuple: (success: bool, message: str)
    """
    from qgis.core import (QgsVectorLayer, QgsFeature, QgsField, QgsVectorFileWriter, 
                          QgsCoordinateTransformContext, QgsCoordinateTransform)
    from qgis.PyQt.QtCore import QVariant
    from pathlib import Path
    
    required_fields = {
        'ID_DZIALKI': QVariant.String,
        'NUMER_DZIALKI': QVariant.String,
        'NUMER_OBREBU': QVariant.String,
        'POLE_EWIDENCYJNE': QVariant.Double
    }
    
    print(f"\n{'='*60}")
    print(f"WALIDACJA WARSTWY DZIAŁEK: {layer.name()}")
    print(f"{'='*60}")
    
    # === POBIERZ CRS PROJEKTU ===
    project_crs = QgsProject.instance().crs()
    source_crs = layer.crs()
    
    print(f"  📍 CRS warstwy źródłowej: {source_crs.authid()}")
    print(f"  📍 CRS projektu: {project_crs.authid()}")
    
    # Czy potrzebna reprojekcja?
    needs_transform = (source_crs.authid() != project_crs.authid())
    if needs_transform:
        print(f"  🔄 Wymagana reprojekcja: {source_crs.authid()} → {project_crs.authid()}")
        transform = QgsCoordinateTransform(source_crs, project_crs, QgsProject.instance())
    else:
        print("  ✓ CRS zgodny - brak reprojekcji")
        transform = None
    
    # Sprawdź istniejące pola
    existing_fields = {field.name(): field for field in layer.fields()}
    missing_fields = []
    
    for req_field in required_fields.keys():
        if req_field not in existing_fields:
            missing_fields.append(req_field)
    
    # Jeśli brakuje pól - pokaż dialog mapowania
    field_mapping = {}
    if missing_fields:
        print(f"⚠️ Brakujące pola: {', '.join(missing_fields)}")
        
        dialog = FieldMappingDialog(
            layer=layer,
            required_fields=list(required_fields.keys()),
            layer_type="działek"
        )
        
        result = dialog.exec()
        if result != QDialog.DialogCode.Accepted:
            return False, "Anulowano mapowanie pól działek"
        
        field_mapping = dialog.get_field_mapping()
        print(f"✓ Mapowanie pól: {field_mapping}")
    else:
        print("✓ Wszystkie wymagane pola istnieją")
        for req_field in required_fields.keys():
            field_mapping[req_field] = req_field
    
    # === Stwórz warstwę memory Z CRS PROJEKTU ===
    print("  📋 Tworzę warstwę roboczą...")
    
    geom_type = layer.geometryType()
    
    if geom_type == 2:  # Polygon
        geom_str = "Polygon"
    elif geom_type == 1:  # Line
        geom_str = "LineString"
    else:  # Point
        geom_str = "Point"
    
    # ⬅️ UŻYWAJ CRS PROJEKTU!
    memory_layer = QgsVectorLayer(
        f"{geom_str}?crs={project_crs.authid()}", 
        "temp_dzialki", 
        "memory"
    )
    memory_provider = memory_layer.dataProvider()
    
    # Dodaj wszystkie wymagane pola
    fields_to_add = []
    for req_field, field_type in required_fields.items():
        new_field = QgsField(req_field, field_type)
        if req_field == 'POLE_EWIDENCYJNE':
            new_field.setLength(10)
            new_field.setPrecision(2)
        fields_to_add.append(new_field)
    
    memory_provider.addAttributes(fields_to_add)
    memory_layer.updateFields()
    print("  ✓ Utworzono pola w warstwie roboczej")
    
    # === Przepisz dane z mapowaniem I REPROJEKCJĄ ===
    print("  📝 Przepisuję dane z mapowaniem i reprojekcją...")
    
    features_to_add = []
    reprojected_count = 0
    
    for src_feature in layer.getFeatures():
        # Stwórz nowy feature
        new_feature = QgsFeature(memory_layer.fields())
        
        # ⬅️ REPROJEKCJA GEOMETRII
        geometry = src_feature.geometry()
        if transform:
            geometry.transform(transform)
            reprojected_count += 1
        
        new_feature.setGeometry(geometry)
        
        # Przepisz dane według mapowania
        for req_field, source_field in field_mapping.items():
            field_idx = memory_layer.fields().indexFromName(req_field)
            
            if req_field == 'POLE_EWIDENCYJNE':
                # ⬅️ OBLICZ POWIERZCHNIĘ PO REPROJEKCJI!
                area = round(geometry.area(), 2)
                new_feature.setAttribute(field_idx, area)
            elif source_field and source_field in existing_fields:
                # Skopiuj wartość
                value = src_feature[source_field]
                new_feature.setAttribute(field_idx, value)
            # else: pozostaw NULL
        
        features_to_add.append(new_feature)
    
    # Dodaj wszystkie features naraz
    memory_provider.addFeatures(features_to_add)
    memory_layer.updateExtents()
    
    print(f"  ✓ Przepisano {len(features_to_add)} obiektów")
    if reprojected_count > 0:
        print(f"  🔄 Reprojektowano {reprojected_count} geometrii")
    
    # === Zapisz do gpkg ===
    output_path = str(Path(project_directory) / "dzialki_EWGiB.gpkg")
    
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.fileEncoding = 'UTF-8'
    options.layerName = "dzialki_EWGiB"
    options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        memory_layer, 
        output_path, 
        QgsCoordinateTransformContext(), 
        options
    )
    
    if result[0] == QgsVectorFileWriter.WriterError.NoError:
        print(f"  ✅ Zapisano do: {output_path}")
        
        # Wczytaj zapisaną warstwę do projektu
        saved_layer = QgsVectorLayer(f"{output_path}|layername=dzialki_EWGiB", "dzialki_EWGiB", "ogr")
        if saved_layer.isValid():
            QgsProject.instance().addMapLayer(saved_layer)
            print("✅ Warstwa działek zwalidowana i zapisana")
            print(f"  📍 CRS warstwy wynikowej: {saved_layer.crs().authid()}")
            return True, "Warstwa działek gotowa"
        else:
            return False, "Nie udało się wczytać zapisanej warstwy działek"
    else:
        print(f"❌ Błąd podczas zapisywania: {result[1]}")
        return False, f"Nie udało się zapisać warstwy działek: {result[1]}"



def validate_and_fix_budynki_layer(layer, project_directory):
    """
    Walidacja i naprawa struktury warstwy budynków
    WERSJA 2.2 - z REPROJEKCJĄ do CRS projektu
    
    Returns:
        tuple: (success: bool, message: str)
    """
    from qgis.core import (QgsVectorLayer, QgsFeature, QgsField, QgsVectorFileWriter, 
                          QgsCoordinateTransformContext, QgsCoordinateTransform)
    from qgis.PyQt.QtCore import QVariant
    from pathlib import Path
    
    required_fields = {
        'KONDYGNACJE_NADZIEMNE': QVariant.Int,
        'KONDYGNACJE_PODZIEMNE': QVariant.Int,
        'ID_BUDYNKU': QVariant.String,
        'rodzaj_zabudowy': QVariant.String
    }
    
    calculated_fields = {
        'powierzchnia_zabudowy': QVariant.Double,
        'powBrutto': QVariant.Double,
        'sumaPowKondygNadziemnych': QVariant.Double
    }
    
    print(f"\n{'='*60}")
    print(f"WALIDACJA WARSTWY BUDYNKÓW: {layer.name()}")
    print(f"{'='*60}")
    
    # === POBIERZ CRS PROJEKTU ===
    project_crs = QgsProject.instance().crs()
    source_crs = layer.crs()
    
    print(f"  📍 CRS warstwy źródłowej: {source_crs.authid()}")
    print(f"  📍 CRS projektu: {project_crs.authid()}")
    
    # Czy potrzebna reprojekcja?
    needs_transform = (source_crs.authid() != project_crs.authid())
    if needs_transform:
        print(f"  🔄 Wymagana reprojekcja: {source_crs.authid()} → {project_crs.authid()}")
        transform = QgsCoordinateTransform(source_crs, project_crs, QgsProject.instance())
    else:
        print("  ✓ CRS zgodny - brak reprojekcji")
        transform = None
    
    # Sprawdź istniejące pola
    existing_fields = {field.name(): field for field in layer.fields()}
    missing_fields = []
    
    for req_field in required_fields.keys():
        if req_field not in existing_fields:
            missing_fields.append(req_field)
    
    # Jeśli brakuje pól - pokaż dialog mapowania
    field_mapping = {}
    if missing_fields:
        print(f"⚠️ Brakujące pola: {', '.join(missing_fields)}")
        
        dialog = FieldMappingDialog(
            layer=layer,
            required_fields=list(required_fields.keys()),
            layer_type="budynków"
        )
        
        result = dialog.exec()
        if result != QDialog.DialogCode.Accepted:
            return False, "Anulowano mapowanie pól budynków"
        
        field_mapping = dialog.get_field_mapping()
        print(f"✓ Mapowanie pól: {field_mapping}")
    else:
        print("✓ Wszystkie wymagane pola istnieją")
        for req_field in required_fields.keys():
            field_mapping[req_field] = req_field
    
    # === Stwórz warstwę memory Z CRS PROJEKTU ===
    print("  📋 Tworzę warstwę roboczą...")
    
    geom_type = layer.geometryType()
    
    if geom_type == 2:  # Polygon
        geom_str = "Polygon"
    elif geom_type == 1:  # Line
        geom_str = "LineString"
    else:  # Point
        geom_str = "Point"
    
    # ⬅️ UŻYWAJ CRS PROJEKTU!
    memory_layer = QgsVectorLayer(
        f"{geom_str}?crs={project_crs.authid()}", 
        "temp_budynki", 
        "memory"
    )
    memory_provider = memory_layer.dataProvider()
    
    # Dodaj wszystkie wymagane pola + obliczeniowe
    fields_to_add = []
    
    # Pola wymagane
    for req_field, field_type in required_fields.items():
        new_field = QgsField(req_field, field_type)
        if field_type == QVariant.Int:
            new_field.setLength(10)
        fields_to_add.append(new_field)
    
    # Pola obliczeniowe
    for calc_field, field_type in calculated_fields.items():
        new_field = QgsField(calc_field, field_type)
        new_field.setLength(10)
        new_field.setPrecision(2)
        fields_to_add.append(new_field)
    
    memory_provider.addAttributes(fields_to_add)
    memory_layer.updateFields()
    print("  ✓ Utworzono pola w warstwie roboczej")
    
    # === Przepisz dane z mapowaniem, naprawą I REPROJEKCJĄ ===
    print("  📝 Przepisuję i naprawiam dane...")
    
    fixed_nadz = 0
    fixed_podz = 0
    reprojected_count = 0
    
    features_to_add = []
    for src_feature in layer.getFeatures():
        # Stwórz nowy feature
        new_feature = QgsFeature(memory_layer.fields())
        
        # ⬅️ REPROJEKCJA GEOMETRII
        geometry = src_feature.geometry()
        if transform:
            geometry.transform(transform)
            reprojected_count += 1
        
        new_feature.setGeometry(geometry)
        
        # === Przepisz dane podstawowe ===
        for req_field, source_field in field_mapping.items():
            field_idx = memory_layer.fields().indexFromName(req_field)
            
            if source_field and source_field in existing_fields:
                value = src_feature[source_field]
                
                # === NAPRAWA KONDYGNACJI ===
                if req_field == 'KONDYGNACJE_NADZIEMNE':
                    try:
                        int_value = int(value) if value not in [None, '', 'NULL'] else 0
                        if int_value <= 0:
                            int_value = 1
                            fixed_nadz += 1
                        new_feature.setAttribute(field_idx, int_value)
                    except (ValueError, TypeError):
                        new_feature.setAttribute(field_idx, 1)
                        fixed_nadz += 1
                
                elif req_field == 'KONDYGNACJE_PODZIEMNE':
                    try:
                        int_value = int(value) if value not in [None, '', 'NULL'] else 0
                        if int_value < 0:
                            int_value = 0
                            fixed_podz += 1
                        new_feature.setAttribute(field_idx, int_value)
                    except (ValueError, TypeError):
                        new_feature.setAttribute(field_idx, 0)
                        fixed_podz += 1
                
                else:
                    # Zwykłe pole - przepisz
                    new_feature.setAttribute(field_idx, value)
            
            elif req_field in ['KONDYGNACJE_NADZIEMNE', 'KONDYGNACJE_PODZIEMNE']:
                # Brak mapowania - ustaw domyślne
                default_value = 1 if req_field == 'KONDYGNACJE_NADZIEMNE' else 0
                new_feature.setAttribute(field_idx, default_value)
        
        # === OBLICZ POLA POCHODNE (PO REPROJEKCJI!) ===
        kond_nadz_idx = memory_layer.fields().indexFromName('KONDYGNACJE_NADZIEMNE')
        kond_podz_idx = memory_layer.fields().indexFromName('KONDYGNACJE_PODZIEMNE')
        
        kond_nadz = new_feature.attribute(kond_nadz_idx)
        kond_podz = new_feature.attribute(kond_podz_idx)
        
        kond_nadz = int(kond_nadz) if kond_nadz is not None else 1
        kond_podz = int(kond_podz) if kond_podz is not None else 0
        
        # ⬅️ POWIERZCHNIA Z REPROJEKTOWANEJ GEOMETRII!
        area = round(geometry.area(), 2)
        pow_zab_idx = memory_layer.fields().indexFromName('powierzchnia_zabudowy')
        new_feature.setAttribute(pow_zab_idx, area)
        
        # powBrutto
        pow_brutto = round(area * (kond_nadz + kond_podz), 2)
        pow_brutto_idx = memory_layer.fields().indexFromName('powBrutto')
        new_feature.setAttribute(pow_brutto_idx, pow_brutto)
        
        # sumaPowKondygNadziemnych
        suma_nadz = round(area * kond_nadz, 2)
        suma_nadz_idx = memory_layer.fields().indexFromName('sumaPowKondygNadziemnych')
        new_feature.setAttribute(suma_nadz_idx, suma_nadz)
        
        features_to_add.append(new_feature)
    
    # Dodaj wszystkie features naraz
    memory_provider.addFeatures(features_to_add)
    memory_layer.updateExtents()
    
    print(f"  ✓ Przepisano {len(features_to_add)} obiektów")
    if reprojected_count > 0:
        print(f"  🔄 Reprojektowano {reprojected_count} geometrii")
    if fixed_nadz > 0:
        print(f"  ✓ Poprawiono {fixed_nadz} wartości KONDYGNACJE_NADZIEMNE")
    if fixed_podz > 0:
        print(f"  ✓ Poprawiono {fixed_podz} wartości KONDYGNACJE_PODZIEMNE")
    
    # === Zapisz do gpkg ===
    output_path = str(Path(project_directory) / "budynki_EWGiB.gpkg")
    
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.fileEncoding = 'UTF-8'
    options.layerName = "budynki_EWGiB"
    options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        memory_layer, 
        output_path, 
        QgsCoordinateTransformContext(), 
        options
    )
    
    if result[0] == QgsVectorFileWriter.WriterError.NoError:
        print(f"  ✅ Zapisano do: {output_path}")
        
        # Wczytaj zapisaną warstwę do projektu
        saved_layer = QgsVectorLayer(f"{output_path}|layername=budynki_EWGiB", "budynki_EWGiB", "ogr")
        if saved_layer.isValid():
            QgsProject.instance().addMapLayer(saved_layer)
            print("✅ Warstwa budynków zwalidowana i zapisana")
            print(f"  📍 CRS warstwy wynikowej: {saved_layer.crs().authid()}")
            return True, "Warstwa budynków gotowa"
        else:
            return False, "Nie udało się wczytać zapisanej warstwy budynków"
    else:
        print(f"❌ Błąd podczas zapisywania: {result[1]}")
        return False, f"Nie udało się zapisać warstwy budynków: {result[1]}"



def copy_and_save_base_layers_v2():
    """
    Funkcja główna - pokaż dialog wyboru i skopiuj warstwy z walidacją
    
    Returns:
        tuple: (success: bool, message: str)
    """
    project_directory = get_project_directory()
    if not project_directory:
        return False, "Projekt musi być najpierw zapisany!"
    
    dialog = LayerSelectionDialog()
    result = dialog.exec()
    
    if result != QDialog.DialogCode.Accepted:
        return False, "Anulowano wybór warstw"
    
    dzialki_layer, budynki_layer = dialog.get_selected_layers()
    
    if not dzialki_layer or not budynki_layer:
        return False, "Nie wybrano warstw"
    
    try:
        # === WALIDACJA I NAPRAWA WARSTWY DZIAŁEK ===
        print(f"\n{'='*80}")
        print("ROZPOCZYNAM WALIDACJĘ WARSTWY DZIAŁEK")
        print(f"{'='*80}")
        
        success, message = validate_and_fix_dzialki_layer(dzialki_layer, project_directory)
        if not success:
            QMessageBox.critical(None, "Błąd", f"Nie udało się przygotować warstwy działek:\n{message}")
            return False, message
        
        # === WALIDACJA I NAPRAWA WARSTWY BUDYNKÓW ===
        print(f"\n{'='*80}")
        print("ROZPOCZYNAM WALIDACJĘ WARSTWY BUDYNKÓW")
        print(f"{'='*80}")
        
        success, message = validate_and_fix_budynki_layer(budynki_layer, project_directory)
        if not success:
            QMessageBox.critical(None, "Błąd", f"Nie udało się przygotować warstwy budynków:\n{message}")
            return False, message
        
        # === PODSUMOWANIE ===
        success_msg = (
            f"✅ Warstwy bazowe utworzone i zwalidowane pomyślnie!\n\n"
            f"📊 WARSTWA DZIAŁEK:\n"
            f"  • Plik: dzialki_EWGiB.gpkg\n"
            f"  • Liczba obiektów: {dzialki_layer.featureCount()}\n"
            f"  • Wymagane pola: ✓ sprawdzone i uzupełnione\n\n"
            f"🏠 WARSTWA BUDYNKÓW:\n"
            f"  • Plik: budynki_EWGiB.gpkg\n"
            f"  • Liczba obiektów: {budynki_layer.featureCount()}\n"
            f"  • Wymagane pola: ✓ sprawdzone i uzupełnione\n"
            f"  • Pola obliczeniowe: ✓ utworzone\n\n"
            f"📂 Zapisano w: {project_directory}"
        )
        
        QMessageBox.information(None, "Sukces", success_msg)
        
        print(f"\n{'='*80}")
        print("WALIDACJA ZAKOŃCZONA POMYŚLNIE!")
        print(f"{'='*80}\n")
        
        return True, "Warstwy bazowe utworzone"
        
    except Exception as e:
        error_msg = f"Błąd podczas przygotowania warstw: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        
        QMessageBox.critical(None, "Błąd", error_msg)
        return False, error_msg



class LayerSelectionDialog(QDialog):
    """Dialog do wyboru warstw działek i budynków"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wybór warstw bazowych")
        self.setMinimumWidth(500)
        self.setMinimumHeight(250)
        
        self.selected_dzialki_layer = None
        self.selected_budynki_layer = None
        
        self.init_ui()
        self.populate_layers()
    
    def init_ui(self):
        """Inicjalizacja interfejsu"""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        header_label = QLabel(
            "Wybierz warstwy źródłowe do analizy:\n\n"
            "Wybrane warstwy zostaną skopiowane jako:\n"
            "• dzialki_EWGiB.gpkg\n"
            "• budynki_EWGiB.gpkg"
        )
        header_label.setWordWrap(True)
        header_label.setStyleSheet("font-weight: bold; padding: 10px; background-color: #e3f2fd; border-radius: 5px;")
        layout.addWidget(header_label)
        
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        self.dzialki_combo = QComboBox()
        self.dzialki_combo.setMinimumHeight(35)
        form_layout.addRow("🗺️ Warstwa działek:", self.dzialki_combo)
        
        self.budynki_combo = QComboBox()
        self.budynki_combo.setMinimumHeight(35)
        form_layout.addRow("🏠 Warstwa budynków:", self.budynki_combo)
        
        layout.addLayout(form_layout)
        
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #666; font-style: italic; padding: 5px;")
        layout.addWidget(self.info_label)
        
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText("✓ Zatwierdź wybór")
        ok_button.setMinimumHeight(40)
        ok_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText("✗ Anuluj")
        cancel_button.setMinimumHeight(40)
        
        layout.addWidget(button_box)
        
        self.setLayout(layout)
    
    def populate_layers(self):
        """Wypełnij combobox warstwami poligonowymi"""
        from qgis.core import QgsWkbTypes
        
        polygon_layers = []
        
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):  # warstwa wektorowa (dziala w QGIS 3 i 4)
                if layer.geometryType() == QgsWkbTypes.GeometryType.PolygonGeometry:
                    polygon_layers.append(layer)
        
        if len(polygon_layers) == 0:
            self.info_label.setText("⚠️ Nie znaleziono warstw poligonowych w projekcie!")
            self.info_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
        else:
            self.info_label.setText(f"✓ Znaleziono {len(polygon_layers)} warstw poligonowych")
            self.info_label.setStyleSheet("color: #4CAF50;")
        
        for layer in polygon_layers:
            layer_name = layer.name()
            feature_count = layer.featureCount()
            
            display_text = f"{layer_name} ({feature_count} obiektów)"
            
            self.dzialki_combo.addItem(display_text, layer)
            self.budynki_combo.addItem(display_text, layer)
        
        self.set_smart_defaults(polygon_layers)
    
    def set_smart_defaults(self, layers):
        """Ustaw inteligentne domyślne wybory na podstawie nazw warstw"""
        dzialki_keywords = ['dzialk', 'parcel', 'plot', 'ewgib', 'ewidencj']
        budynki_keywords = ['budyn', 'building', 'zabudow', 'buil']
        
        for i, layer in enumerate(layers):
            layer_name_lower = layer.name().lower()
            if any(keyword in layer_name_lower for keyword in dzialki_keywords):
                self.dzialki_combo.setCurrentIndex(i)
                break
        
        for i, layer in enumerate(layers):
            layer_name_lower = layer.name().lower()
            if any(keyword in layer_name_lower for keyword in budynki_keywords):
                self.budynki_combo.setCurrentIndex(i)
                break
    
    def validate_and_accept(self):
        """Waliduj wybór i zatwierdź"""
        if self.dzialki_combo.currentIndex() == -1:
            QMessageBox.warning(self, "Błąd", "Musisz wybrać warstwę działek!")
            return
        
        if self.budynki_combo.currentIndex() == -1:
            QMessageBox.warning(self, "Błąd", "Musisz wybrać warstwę budynków!")
            return
        
        self.selected_dzialki_layer = self.dzialki_combo.currentData()
        self.selected_budynki_layer = self.budynki_combo.currentData()
        
        if self.selected_dzialki_layer == self.selected_budynki_layer:
            reply = QMessageBox.question(
                self,
                "Ta sama warstwa",
                "Wybrałeś tę samą warstwę dla działek i budynków.\n\n"
                "Czy na pewno chcesz kontynuować?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        self.accept()
    
    def get_selected_layers(self):
        """Zwróć wybrane warstwy"""
        return self.selected_dzialki_layer, self.selected_budynki_layer


def copy_and_save_base_layers():
    """
    Funkcja główna - pokaż dialog wyboru i skopiuj warstwy
    
    Returns:
        tuple: (success: bool, message: str)
    """
    project_directory = get_project_directory()
    if not project_directory:
        return False, "Projekt musi być najpierw zapisany!"
    
    dialog = LayerSelectionDialog()
    result = dialog.exec()
    
    if result != QDialog.DialogCode.Accepted:
        return False, "Anulowano wybór warstw"
    
    dzialki_layer, budynki_layer = dialog.get_selected_layers()
    
    if not dzialki_layer or not budynki_layer:
        return False, "Nie wybrano warstw"
    
    try:
        print(f"Kopiuję warstwę działek: {dzialki_layer.name()}")
        dzialki_saved = zapisz_warstwe_do_gpkg(
            layer=dzialki_layer,
            output_directory=project_directory,
            layer_name="dzialki_EWGiB"
        )
        
        if not dzialki_saved:
            return False, "Nie udało się zapisać warstwy działek"
        
        print(f"Kopiuję warstwę budynków: {budynki_layer.name()}")
        budynki_saved = zapisz_warstwe_do_gpkg(
            layer=budynki_layer,
            output_directory=project_directory,
            layer_name="budynki_EWGiB"
        )
        
        if not budynki_saved:
            return False, "Nie udało się zapisać warstwy budynków"
        
        success_msg = (
            f"✅ Warstwy bazowe utworzone pomyślnie!\n\n"
            f"• dzialki_EWGiB.gpkg ({dzialki_saved.featureCount()} obiektów)\n"
            f"• budynki_EWGiB.gpkg ({budynki_saved.featureCount()} obiektów)\n\n"
            f"Zapisano w: {project_directory}"
        )
        
        QMessageBox.information(None, "Sukces", success_msg)
        
        return True, "Warstwy bazowe utworzone"
        
    except Exception as e:
        error_msg = f"Błąd podczas kopiowania warstw: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return False, error_msg


# ==================== DIALOG DANYCH DZIAŁKI V2 ====================

POLA_POG_DO_EKSPORTU = [
    'pog_dostepny', 'pog_strefa_symbol', 'pog_strefa_oznaczenie',
    'pog_strefa_nazwa', 'pog_strefa_nazwa_mian',
    'pog_profil_podstawowy', 'pog_profil_dodatkowy',
    'pog_maks_nadz_intens', 'pog_maks_nadz_intens_val',
    'pog_maks_udzial_pow_zab', 'pog_maks_udzial_pow_zab_val',
    'pog_maks_wysokosc', 'pog_maks_wysokosc_val',
    'pog_min_pbc', 'pog_min_pbc_val',
    'pog_ouz', 'pog_ouz_oznaczenie', 'pog_ozs', 'pog_ozs_oznaczenie',
    'pog_uwagi',
    'pog_zgodnosc_funkcji', 'podstawa_ustalen', 'wyb_par3', 'wyb_par7',
    'sr_wys_dz_sasiednie', 'sr_wys_dz_sasiednie_lista',
    'Lz_ustalona', 'Lz_sasiednie_lista', 'Lz_sasiednie_rowne',
]


class DaneDzialkiDialog(QDialog):
    """Dialog do wypełniania danych działki przedmiotowej - WERSJA 2"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dane działki przedmiotowej")
        self.setMinimumWidth(950)
        self.setMinimumHeight(800)
        
        self.data = {}
        self.building_params = []
        
        self.load_existing_data()
        
        self.init_ui()
        
        self.load_wskazniki_from_layer()
        
        # Odczyt ustaleń planu ogólnego dla terenu inwestycji
        self.odczytaj_plan_ogolny(auto=True)
        
        # Pierwsze przeliczenie wskaźników planowanych
        self.recalculate_planned_indicators()
    
    def init_ui(self):
            """Inicjalizacja interfejsu"""
            main_layout = QVBoxLayout()
            main_layout.setSpacing(15)
            
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll_widget = QWidget()
            scroll_layout = QVBoxLayout()
            
            # === SEKCJA 1: Dane podstawowe ===
            basic_group = QGroupBox("📋 Dane podstawowe wniosku")
            basic_layout = QFormLayout()
            basic_layout.setSpacing(10)
            
            self.znak_sprawy_edit = QLineEdit(self.data.get('znak_sprawy', ''))
            self.data_wniosku_edit = QLineEdit(self.data.get('data_wniosku', ''))
            self.data_wniosku_edit.setPlaceholderText("RRRR-MM-DD")
            self.adres_edit = QLineEdit(self.data.get('adres_dzialki', ''))
            self.identyfikator_edit = QLineEdit(self.data.get('identyfikator_dzialki', ''))
            self.nazwa_inwestycji_edit = QLineEdit(self.data.get('Nazwa_inwestycji', ''))
            self.rodzaj_zabudowy_edit = QLineEdit(self.data.get('Rodzaj_zabudowy', ''))
            
            # ⬅️ OBECNE ZAGOSPODAROWANIE - COMBO + POLE TEKSTOWE
            self.obecne_zagospodarowanie_combo = QComboBox()
            self.obecne_zagospodarowanie_combo.addItems([
                "niezabudowany",
                "zabudowany"
            ])
            current_zagospodarowanie = self.data.get('obecne_zagospodarowanie', 'niezabudowany')
            # Wyciągnij tylko pierwszą część (przed spacją)
            if ' ' in current_zagospodarowanie:
                combo_value = current_zagospodarowanie.split(' ')[0]
            else:
                combo_value = current_zagospodarowanie
            index = self.obecne_zagospodarowanie_combo.findText(combo_value)
            if index >= 0:
                self.obecne_zagospodarowanie_combo.setCurrentIndex(index)
            # Stan terenu decyduje, czy jest co sumowac - przelicz po zmianie
            self.obecne_zagospodarowanie_combo.currentTextChanged.connect(
                self.recalculate_planned_indicators)
            
            self.rodzaj_istniejacy_edit = QLineEdit(self.data.get('rodzaj_istniejacy', ''))
            self.rodzaj_istniejacy_edit.setPlaceholderText("np. zabudowa jednorodzinna")
            
            obecne_zagosp_layout = QHBoxLayout()
            obecne_zagosp_layout.addWidget(self.obecne_zagospodarowanie_combo)
            obecne_zagosp_layout.addWidget(QLabel("Rodzaj:"))
            obecne_zagosp_layout.addWidget(self.rodzaj_istniejacy_edit)
            
            self.powierzchnia_dzialki_edit = QLineEdit(str(self.data.get('powierzchnia_dzialki', '')))
            self.powierzchnia_dzialki_edit.textChanged.connect(self.recalculate_planned_indicators)
            self.powierzchnia_dzialki_edit.textChanged.connect(self.update_pbc_istniejaca)  # ⬅️ DODAJ TO
            self.powierzchnia_dzialki_edit.setPlaceholderText("np. 1234.56")
            
            # ⬅️ PLANOWANA PBC - MIN i MAX (przeniesione tutaj tymczasowo, potem do sekcji planowanej)
            self.powierzchnia_pbc_min_edit = QLineEdit(str(self.data.get('powierzchnia_biologicznie_czynna_min', '')))
            self.powierzchnia_pbc_min_edit.setPlaceholderText("Min")
            self.powierzchnia_pbc_min_edit.textChanged.connect(self.recalculate_planned_indicators)
            
            self.powierzchnia_pbc_max_edit = QLineEdit(str(self.data.get('powierzchnia_biologicznie_czynna_max', '')))
            self.powierzchnia_pbc_max_edit.setPlaceholderText("Max")
            self.powierzchnia_pbc_max_edit.textChanged.connect(self.recalculate_planned_indicators)
            
            basic_layout.addRow("Znak sprawy:", self.znak_sprawy_edit)
            basic_layout.addRow("Data wniosku:", self.data_wniosku_edit)
            basic_layout.addRow("Adres działki:", self.adres_edit)
            
            # Identyfikator - z informacją o auto-wypełnianiu
            id_layout = QVBoxLayout()
            id_layout.addWidget(self.identyfikator_edit)
            id_info = QLabel("<i style='color: #666; font-size: 10px;'>Auto-wypełniane z warstwy 'granica_terenu'</i>")
            id_layout.addWidget(id_info)
            basic_layout.addRow("Identyfikator działki:", id_layout)
            
            basic_layout.addRow("Nazwa inwestycji:", self.nazwa_inwestycji_edit)
            basic_layout.addRow("Rodzaj zabudowy:", self.rodzaj_zabudowy_edit)
            basic_layout.addRow("Obecne zagospodarowanie:", obecne_zagosp_layout)
            
            # Powierzchnia działki - z informacją o auto-wypełnianiu
            pow_layout = QVBoxLayout()
            pow_layout.addWidget(self.powierzchnia_dzialki_edit)
            pow_info = QLabel("<i style='color: #666; font-size: 10px;'>Auto-wypełniana z warstwy 'granica_terenu'</i>")
            pow_layout.addWidget(pow_info)
            basic_layout.addRow("<b>Powierzchnia działki [m²]:</b>", pow_layout)
            
                # ⬅️ OBSŁUGA KOMUNIKACYJNA
            self.obsluga_kom_combo = QComboBox()
            self.obsluga_kom_combo.addItems([
                "bezpośrednia",
                "pośrednia - droga wewnętrzna",
                "pośrednia - służebność"
            ])
            current_obsluga = self.data.get('obsluga_komunikacyjna', 'bezpośrednia')
            index_obs = self.obsluga_kom_combo.findText(current_obsluga)
            if index_obs >= 0:
                self.obsluga_kom_combo.setCurrentIndex(index_obs)
            self.obsluga_kom_combo.currentTextChanged.connect(self.on_obsluga_kom_changed)
            
            self.dzialka_dojazd_edit = QLineEdit(self.data.get('dzialka_dojazd', ''))
            self.dzialka_dojazd_edit.setPlaceholderText("np. 7/23 obręb 0023")
            self.dzialka_dojazd_label = QLabel("Działka dojazdu:")
            
            # Przypomnienie o numerze obrębu
            self.dzialka_dojazd_reminder = QLabel(
                "<b>⚠️</b> Podaj numer działki <b>wraz z numerem obrębu</b>! "
                "Np. <i>7/23 obręb 0023</i>"
            )
            self.dzialka_dojazd_reminder.setWordWrap(True)
            self.dzialka_dojazd_reminder.setStyleSheet(
                "padding: 4px 8px; background-color: #fff3cd; border-radius: 3px; "
                "color: #856404; font-size: 10px;"
            )
            
            # Ukryj pole działki dojazdu jeśli obsługa bezpośrednia
            if current_obsluga == "bezpośrednia":
                self.dzialka_dojazd_edit.hide()
                self.dzialka_dojazd_label.hide()
                self.dzialka_dojazd_reminder.hide()
            
            obsluga_layout = QVBoxLayout()
            obsluga_layout.addWidget(self.obsluga_kom_combo)
            dzialka_dojazd_layout = QHBoxLayout()
            dzialka_dojazd_layout.addWidget(self.dzialka_dojazd_label)
            dzialka_dojazd_layout.addWidget(self.dzialka_dojazd_edit)
            obsluga_layout.addLayout(dzialka_dojazd_layout)
            obsluga_layout.addWidget(self.dzialka_dojazd_reminder)
            
            basic_layout.addRow("Obsługa komunikacyjna:", obsluga_layout)
            
            basic_group.setLayout(basic_layout)
            scroll_layout.addWidget(basic_group)
            
            # === SEKCJA 1b: Linia zabudowy, parkowanie, promesy ===
            dodatkowe_group = QGroupBox("📐 Linia zabudowy, parkowanie i promesy")
            dodatkowe_layout = QFormLayout()
            dodatkowe_layout.setSpacing(10)
            
            # --- LINIA ZABUDOWY ---
            self.lz_w_edit = QLineEdit(str(self.data.get('Lz_w', 'nie dotyczy')))
            self.lz_w_edit.setPlaceholderText("Wnioskowana linia zabudowy [m] lub 'nie dotyczy'")
            dodatkowe_layout.addRow("Linia zabudowy wnioskowana (Lz_w):", self.lz_w_edit)
            
            self.rodzaj_lz_combo = QComboBox()
            self.rodzaj_lz_combo.addItems(["obowiązującą", "nieprzekraczalną"])
            current_rodzaj_lz = str(self.data.get('rodzaj_Lz', 'obowiązującą'))
            idx_lz = self.rodzaj_lz_combo.findText(current_rodzaj_lz)
            if idx_lz >= 0:
                self.rodzaj_lz_combo.setCurrentIndex(idx_lz)
            dodatkowe_layout.addRow("Rodzaj linii zabudowy:", self.rodzaj_lz_combo)
            
            # --- PARKOWANIE ---
            park_header = QLabel("<b>🅿️ Miejsca parkingowe</b>")
            dodatkowe_layout.addRow(park_header)
            
            self.w_l_park_min_edit = QLineEdit(str(self.data.get('w_l_park_min', '')))
            self.w_l_park_min_edit.setPlaceholderText("Minimalna liczba miejsc (wnioskowana)")
            dodatkowe_layout.addRow("Wnioskowana min. liczba miejsc:", self.w_l_park_min_edit)
            
            self.w_l_park_max_edit = QLineEdit(str(self.data.get('w_l_park_max', '')))
            self.w_l_park_max_edit.setPlaceholderText("Maksymalna liczba miejsc (wnioskowana)")
            self.w_l_park_max_edit.textChanged.connect(self._update_l_park_default)
            dodatkowe_layout.addRow("Wnioskowana max. liczba miejsc:", self.w_l_park_max_edit)
            
            self.l_park_edit = QLineEdit(str(self.data.get('l_park', '')))
            self.l_park_edit.setPlaceholderText("Domyślnie = wnioskowana max.")
            dodatkowe_layout.addRow("Ustalona liczba miejsc (l_park):", self.l_park_edit)
            
            # --- PROMESY ---
            promesy_header = QLabel("<b>📄 Promesy (warunki przyłączenia)</b>")
            dodatkowe_layout.addRow(promesy_header)
            
            wodkan_header = QLabel("<i>Wodociągi i kanalizacja:</i>")
            dodatkowe_layout.addRow(wodkan_header)
            self.wodkan_data_edit = QLineEdit(str(self.data.get('wodkan_data', '')))
            self.wodkan_data_edit.setPlaceholderText("Data promesy wod-kan (np. 2024-01-15)")
            dodatkowe_layout.addRow("Data:", self.wodkan_data_edit)
            self.wodkan_znak_edit = QLineEdit(str(self.data.get('wodkan_znak', '')))
            self.wodkan_znak_edit.setPlaceholderText("Numer/znak sprawy promesy wod-kan")
            dodatkowe_layout.addRow("Znak sprawy:", self.wodkan_znak_edit)
            
            energa_header = QLabel("<i>Energia elektryczna:</i>")
            dodatkowe_layout.addRow(energa_header)
            self.energa_data_edit = QLineEdit(str(self.data.get('energa_data', '')))
            self.energa_data_edit.setPlaceholderText("Data promesy energetycznej (np. 2024-02-20)")
            dodatkowe_layout.addRow("Data:", self.energa_data_edit)
            self.energa_znak_edit = QLineEdit(str(self.data.get('energa_znak', '')))
            self.energa_znak_edit.setPlaceholderText("Numer/znak sprawy promesy energetycznej")
            dodatkowe_layout.addRow("Znak sprawy:", self.energa_znak_edit)
            
            dodatkowe_group.setLayout(dodatkowe_layout)
            scroll_layout.addWidget(dodatkowe_group)
            
            # === SEKCJA 1c: Plan ogólny ===
            pog_group = QGroupBox("🗺️ Plan ogólny gminy")
            pog_layout = QVBoxLayout()
            
            self.pog_label = QLabel()
            self.pog_label.setWordWrap(True)
            self.pog_label.setTextFormat(Qt.TextFormat.RichText)
            self.pog_label.setStyleSheet("""
                QLabel {
                    background-color: white;
                    border: 1px solid #ccc;
                    padding: 10px;
                }
            """)
            pog_layout.addWidget(QLabel(
                "<b>Ustalenia dla strefy planistycznej obejmującej teren inwestycji:</b>"
            ))
            pog_layout.addWidget(self.pog_label)
            
            pog_btn = ModernButton("🔄 Odczytaj strefę z planu ogólnego", "secondary")
            pog_btn.clicked.connect(self.odczytaj_plan_ogolny)
            pog_layout.addWidget(pog_btn)
            
            pog_form = QFormLayout()
            pog_form.setSpacing(10)
            
            # --- zgodność funkcji z profilem strefy ---
            self.pog_zgodnosc_combo = QComboBox()
            self.pog_zgodnosc_combo.addItems(["mieści się", "nie mieści się"])
            idx = self.pog_zgodnosc_combo.findText(
                str(self.data.get('pog_zgodnosc_funkcji', 'mieści się'))
            )
            if idx >= 0:
                self.pog_zgodnosc_combo.setCurrentIndex(idx)
            pog_form.addRow(
                "Planowana funkcja <b>…</b> w profilu strefy:", self.pog_zgodnosc_combo
            )
            
            # --- podstawa ustaleń: § 2 ust. 2 albo ust. 3 ---
            self.podstawa_ustalen_combo = QComboBox()
            self.podstawa_ustalen_combo.addItems([
                "§ 2 ust. 2 – zabudowa o takiej samej funkcji jak wnioskowana",
                "§ 2 ust. 3 – wszystkie działki zabudowane w obszarze analizowanym",
            ])
            if "ust. 3" in str(self.data.get('podstawa_ustalen', '')):
                self.podstawa_ustalen_combo.setCurrentIndex(1)
            pog_form.addRow("<b>Podstawa ustaleń (§ 2):</b>", self.podstawa_ustalen_combo)
            
            podstawa_info = QLabel(
                "<i style='color: #666; font-size: 10px;'>Ten wybór steruje brzmieniem "
                "wszystkich zdań „w obszarze analizowanym na terenach o takiej samej "
                "funkcji…” w całej analizie.</i>"
            )
            podstawa_info.setWordWrap(True)
            pog_form.addRow(podstawa_info)
            
            # --- § 3 (linia zabudowy) ---
            self.par3_combo = QComboBox()
            self.par3_combo.addItems(["1", "2", "3"])
            idx = self.par3_combo.findText(str(self.data.get('wyb_par3', '1')))
            if idx >= 0:
                self.par3_combo.setCurrentIndex(idx)
            pog_form.addRow("Linia zabudowy – § 3 ust.:", self.par3_combo)

            # Narzędzie: porównanie linii zabudowy z dwóch działek sąsiednich
            lz_row = QHBoxLayout()
            self.lz_ustalona_edit = QLineEdit(str(self.data.get('Lz_ustalona', '')))
            self.lz_ustalona_edit.setPlaceholderText(
                "zaznacz dwie linie na mapie i kliknij „Porównaj”"
            )
            lz_row.addWidget(self.lz_ustalona_edit, 1)
            lz_btn_zazn = ModernButton("Zaznacz na mapie", "secondary")
            lz_btn_zazn.setToolTip("Aktywuje warstwę 'linie_zabudowy' i narzędzie zaznaczania")
            lz_btn_zazn.clicked.connect(self.zaznacz_linie_zabudowy)
            lz_row.addWidget(lz_btn_zazn)
            lz_btn_licz = ModernButton("Porównaj", "secondary")
            lz_btn_licz.clicked.connect(self.porownaj_linie_zabudowy)
            lz_row.addWidget(lz_btn_licz)
            pog_form.addRow("Ustalona linia zabudowy:", lz_row)

            self.lz_info_label = QLabel(
                "<i style='color: #666; font-size: 10px;'>Zaznacz linie zabudowy budynków "
                "na przylegających działkach sąsiednich dostępnych z tej samej drogi "
                "publicznej. Równe odległości → § 3 ust. 1, różne → § 3 ust. 2; "
                "jako ustaloną przyjmowana jest większa.</i>"
            )
            self.lz_info_label.setWordWrap(True)
            pog_form.addRow(self.lz_info_label)
            
            # --- § 7 (wysokość zabudowy) ---
            self.par7_combo = QComboBox()
            # ust. 1  – wysokość ustalona jako średnia z działek sąsiednich
            # ust. 2  – wysokość podwyższona względem średniej
            # ust. 1-2 – oba ustępy powoływane łącznie
            # ust. 3  – brak zabudowy odniesienia
            self.par7_combo.addItems(["1", "2", "1-2", "3"])
            idx = self.par7_combo.findText(str(self.data.get('wyb_par7', '1-2')))
            if idx >= 0:
                self.par7_combo.setCurrentIndex(idx)
            pog_form.addRow("Wysokość zabudowy – § 7 ust.:", self.par7_combo)

            # Narzędzie: średnia wysokość zabudowy na działkach sąsiednich.
            # Liczona ZAWSZE, niezależnie od wybranego ustępu § 7 — jest
            # podstawą ustalenia maksymalnej wysokości nowej zabudowy.
            wys_row = QHBoxLayout()
            self.sr_wys_sasiednie_edit = QLineEdit(
                str(self.data.get('sr_wys_dz_sasiednie', ''))
            )
            self.sr_wys_sasiednie_edit.setPlaceholderText(
                "zaznacz budynki na mapie i kliknij „Policz średnią”"
            )
            wys_row.addWidget(self.sr_wys_sasiednie_edit, 1)
            wys_btn_zazn = ModernButton("Zaznacz na mapie", "secondary")
            wys_btn_zazn.setToolTip("Aktywuje warstwę 'budynki_parametry' i narzędzie zaznaczania")
            wys_btn_zazn.clicked.connect(self.zaznacz_budynki_sasiednie)
            wys_row.addWidget(wys_btn_zazn)
            wys_btn_licz = ModernButton("Policz średnią", "secondary")
            wys_btn_licz.clicked.connect(self.policz_srednia_wysokosc_sasiadow)
            wys_row.addWidget(wys_btn_licz)
            pog_form.addRow("Śr. wysokość na działkach sąsiednich:", wys_row)

            self.wys_info_label = QLabel(
                "<i style='color: #666; font-size: 10px;'>Zaznacz budynki na przylegających "
                "działkach sąsiednich dostępnych z tej samej drogi publicznej. Ta średnia "
                "trafia do analizy jako maksymalna ustalona wysokość nowej zabudowy; "
                "gdy jej nie policzysz, użyta zostanie średnia z całego obszaru "
                "analizowanego.</i>"
            )
            self.wys_info_label.setWordWrap(True)
            pog_form.addRow(self.wys_info_label)
            
            pog_layout.addLayout(pog_form)
            pog_group.setLayout(pog_layout)
            scroll_layout.addWidget(pog_group)
            
            # === SEKCJA 2: Wskaźniki istniejącej zabudowy ===
            wskazniki_group = QGroupBox("📊 Wskaźniki ISTNIEJĄCEJ zabudowy")
            wskazniki_layout = QVBoxLayout()
            
            self.wskazniki_label = QLabel()
            self.wskazniki_label.setWordWrap(True)
            self.wskazniki_label.setTextFormat(Qt.TextFormat.RichText)
            self.wskazniki_label.setStyleSheet("""
                QLabel {
                    background-color: white;
                    border: 1px solid #ccc;
                    padding: 10px;
                }
            """)
            
            wskazniki_layout.addWidget(QLabel("<b>Dane pobrane z warstwy 'granica_terenu_wskazniki':</b>"))
            wskazniki_layout.addWidget(self.wskazniki_label)
            
            wskazniki_group.setLayout(wskazniki_layout)
            scroll_layout.addWidget(wskazniki_group)
            
            # === SEKCJA 3: Parametry planowanej zabudowy ===
            params_group = QGroupBox("🏗️ Parametry PLANOWANEJ zabudowy")
            params_layout = QVBoxLayout()
            
            # WYŚWIETLANIE PBC ISTNIEJĄCEJ
            pbc_ist_layout = QHBoxLayout()
            pbc_ist_layout.addWidget(QLabel("<b>Pow. biol. czynna - ISTNIEJĄCA [m²]:</b>"))
            self.pbc_istniejaca_label = QLabel("0.00")
            self.pbc_istniejaca_label.setStyleSheet(
                "font-weight: bold; color: #1976D2; padding: 5px; "
                "background-color: #e3f2fd; border-radius: 3px;"
            )
            pbc_ist_layout.addWidget(self.pbc_istniejaca_label)
            pbc_ist_layout.addStretch()
            params_layout.addLayout(pbc_ist_layout)
                        
            # ⬅️ PLANOWANA PBC - MIN/MAX
            pbc_plan_layout = QHBoxLayout()
            pbc_plan_layout.addWidget(QLabel("<b>Powierzchnia biol. czynna - planowana [m²]:</b>"))
            pbc_plan_layout.addWidget(QLabel("Min:"))
            pbc_plan_layout.addWidget(self.powierzchnia_pbc_min_edit)
            pbc_plan_layout.addWidget(QLabel("Max:"))
            pbc_plan_layout.addWidget(self.powierzchnia_pbc_max_edit)
            params_layout.addLayout(pbc_plan_layout)
            
            # ⬅️ TRYB PLANOWANEJ ZABUDOWY (zastępuje/uzupełnia)
            self.tryb_zabudowy_combo = QComboBox()
            self.tryb_zabudowy_combo.addItems([
                "uzupełnia istniejącą zabudowę",
                "zastępuje istniejącą zabudowę"
            ])
            current_tryb = self.data.get('tryb_planowanej_zabudowy', 'uzupełnia istniejącą zabudowę')
            index_tryb = self.tryb_zabudowy_combo.findText(current_tryb)
            if index_tryb >= 0:
                self.tryb_zabudowy_combo.setCurrentIndex(index_tryb)
            self.tryb_zabudowy_combo.currentTextChanged.connect(self.recalculate_planned_indicators)
            
            tryb_layout = QHBoxLayout()
            tryb_layout.addWidget(QLabel("<b>Planowana zabudowa:</b>"))
            tryb_layout.addWidget(self.tryb_zabudowy_combo)
            params_layout.addLayout(tryb_layout)
        
            self.buildings_container = QWidget()
            self.buildings_layout = QVBoxLayout()
            self.buildings_container.setLayout(self.buildings_layout)
            
            params_layout.addWidget(self.buildings_container)
            
            buttons_layout = QHBoxLayout()
            add_building_btn = ModernButton("➕ Dodaj typ budynku", "success")
            add_building_btn.clicked.connect(self.add_building_params)
            buttons_layout.addWidget(add_building_btn)
            
            # Przycisk przelicz
            recalc_btn = ModernButton("🔄 Przelicz wskaźniki", "secondary")
            recalc_btn.clicked.connect(self.recalculate_planned_indicators)
            buttons_layout.addWidget(recalc_btn)
            
            params_layout.addLayout(buttons_layout)
            params_group.setLayout(params_layout)
            scroll_layout.addWidget(params_group)
            
            if self.building_params:
                for params in self.building_params:
                    self.add_building_params(params)
            else:
                self.add_building_params()
            
            # === SEKCJA 4: Wskaźniki PLANOWANEJ zabudowy ===
            wskazniki_plan_group = QGroupBox("📈 Wskaźniki PLANOWANEJ zabudowy (obliczone automatycznie)")
            wskazniki_plan_layout = QVBoxLayout()
            
            self.wskazniki_plan_label = QLabel()
            self.wskazniki_plan_label.setWordWrap(True)
            self.wskazniki_plan_label.setTextFormat(Qt.TextFormat.RichText)
            self.wskazniki_plan_label.setStyleSheet("""
                QLabel {
                    background-color: #e8f5e9;
                    border: 2px solid #4CAF50;
                    padding: 10px;
                    font-size: 13px;
                }
            """)
            
            wskazniki_plan_layout.addWidget(self.wskazniki_plan_label)
            
            wskazniki_plan_group.setLayout(wskazniki_plan_layout)
            scroll_layout.addWidget(wskazniki_plan_group)
            
            scroll_widget.setLayout(scroll_layout)
            scroll.setWidget(scroll_widget)
            main_layout.addWidget(scroll)
            
            # === PRZYCISKI DIALOGU ===
            button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            button_box.accepted.connect(self.save_and_accept)
            button_box.rejected.connect(self.reject)
            
            ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
            ok_button.setText("💾 Zapisz i kontynuuj")
            ok_button.setMinimumHeight(40)
            
            main_layout.addWidget(button_box)
            
            self.setLayout(main_layout)    
            
            
    def load_wskazniki_from_layer(self):
        """
        Wczytaj wskaźniki ISTNIEJĄCEJ zabudowy z warstwy
        Próbuje 'granica_terenu_wskazniki', potem 'granica_terenu'
        NIE NADPISUJE danych jeśli były wczytane z pliku!
        """
        # Sprawdź czy dane już są wczytane z pliku
        data_from_file = bool(self.data.get('znak_sprawy'))
        
        # Próbuj obie warstwy
        layer = None
        layer_name = None
        
        for name in ['granica_terenu_wskazniki', 'granica_terenu']:
            layers = QgsProject.instance().mapLayersByName(name)
            if layers:
                layer = layers[0]
                layer_name = name
                break
        
        if not layer:
            self.wskazniki_label.setText(
                "<span style='color: red;'>❌ Nie znaleziono warstwy 'granica_terenu_wskazniki' ani 'granica_terenu'</span>"
            )
            return
        
        features = list(layer.getFeatures())
        
        if not features:
            self.wskazniki_label.setText(
                f"<span style='color: orange;'>⚠️ Warstwa '{layer_name}' jest pusta</span>"
            )
            return
        
        feature = features[0]
        field_names = [f.name() for f in layer.fields()]
        
        # ===== POBIERZ IDENTYFIKATOR DZIAŁKI =====
        identyfikator_fields = [
            'identyfikator', 'iddzialki', 'id_dzialki', 'numer', 
            'teryt', 'nr_dzialki', 'numerdz', 'id'
        ]
        
        identyfikator_value = None
        if not data_from_file or not self.data.get('identyfikator_dzialki'):
            for field_name in identyfikator_fields:
                matching_field = next((f for f in field_names if f.lower() == field_name.lower()), None)
                if matching_field:
                    identyfikator_value = feature[matching_field]
                    if identyfikator_value:
                        print(f"✅ Pobrano identyfikator z pola '{matching_field}': {identyfikator_value}")
                        self.identyfikator_edit.setText(str(identyfikator_value))
                        self.data['identyfikator_dzialki'] = str(identyfikator_value)
                        break
            
            if not identyfikator_value:
                print(f"⚠️ Nie znaleziono pola identyfikatora w warstwie '{layer_name}'")
        else:
            print(f"ℹ️ Identyfikator wczytany z pliku: {self.data.get('identyfikator_dzialki')}")
        
        # ===== POBIERZ POWIERZCHNIĘ DZIAŁKI =====
        powierzchnia_fields = [
            'POLE_EWIDENCYJNE',  # ⬅️ DODAJ TO NA POCZĄTEK!
            'powierzchnia', 'pole', 'area', 'pow_m2', 'pole_m2', 
            'pow_ha', 'powierzchnia_m2', 'pow', 'area_m2'
        ]
        
        powierzchnia_value = None
        if not data_from_file or not self.data.get('powierzchnia_dzialki'):
            for field_name in powierzchnia_fields:
                matching_field = next((f for f in field_names if f.lower() == field_name.lower()), None)
                if matching_field:
                    powierzchnia_value = feature[matching_field]
                    if powierzchnia_value:
                        if 'ha' in matching_field.lower():
                            powierzchnia_value = float(powierzchnia_value) * 10000
                        
                        print(f"✅ Pobrano powierzchnię z pola '{matching_field}': {powierzchnia_value} m²")
                        self.powierzchnia_dzialki_edit.setText(str(powierzchnia_value))
                        self.data['powierzchnia_dzialki'] = str(powierzchnia_value)
                        break
            
            if not powierzchnia_value:
                print(f"⚠️ Nie znaleziono pola powierzchni w warstwie '{layer_name}'")
        else:
            print(f"ℹ️ Powierzchnia wczytana z pliku: {self.data.get('powierzchnia_dzialki')} m²")
            
            
            # ===== POBIERZ NAZWĘ GMINY =====
        nazwa_gminy_fields = [
            'gmina', 'GMINA', 'NAZWA_GMINY', 'nazwa_gminy', 
            'gmina_nazwa', 'GMINA_NAZWA', 'miejscowosc'
        ]
        
        nazwa_gminy_value = None
        if not data_from_file or not self.data.get('nazwa_gminy'):
            for field_name in nazwa_gminy_fields:
                matching_field = next((f for f in field_names if f.lower() == field_name.lower()), None)
                if matching_field:
                    nazwa_gminy_value = feature[matching_field]
                    if nazwa_gminy_value:
                        print(f"✅ Pobrano nazwę gminy z pola '{matching_field}': {nazwa_gminy_value}")
                        self.data['nazwa_gminy'] = str(nazwa_gminy_value)
                        break
            
            if not nazwa_gminy_value:
                print(f"⚠️ Nie znaleziono pola nazwy gminy w warstwie '{layer_name}'")
        else:
            print(f"ℹ️ Nazwa gminy wczytana z pliku: {self.data.get('nazwa_gminy')}")
        
        # ===== POBIERZ WSKAŹNIKI ISTNIEJĄCEJ ZABUDOWY (POJEDYNCZE WARTOŚCI!) =====
        wskazniki = {}
        
        # ⬅️ SZUKAJ PÓL BEZ MIN/MAX - TO SĄ WARTOŚCI FAKTYCZNE!
        wskaznik_fields = {
            'WPZ': ['WPZ', 'wpz', 'wpz_float', 'wskaznik_powierzchni_zabudowy'],
            'WIZ': ['WIZ', 'wiz', 'wskaznik_intensywnosci'],
            'WNIZ': ['WNIZ', 'wniz'],
            'WPBC': ['WPBC', 'wpbc', 'wpbc_float']
        }
        
        wskazniki_found = False
        for wskaznik_name, possible_names in wskaznik_fields.items():
            # Tylko jeśli NIE wczytano z pliku LUB wartość == 0
            if not data_from_file or self.data.get(wskaznik_name, 0) == 0:
                # Szukaj pola - NAJPIERW sprawdź wersję _float!
                found_field = None
                
                # Próbuj najpierw pola z _float (np. wpz_float)
                float_field_name = f"{wskaznik_name.lower()}_float"
                matching_float = [f for f in field_names if f.lower() == float_field_name]
                if matching_float:
                    found_field = matching_float[0]
                else:
                    # Jeśli nie ma _float, szukaj normalnie
                    for possible_name in possible_names:
                        matching = [f for f in field_names if f.lower() == possible_name.lower()]
                        if matching:
                            found_field = matching[0]
                            break
                
                if found_field:
                    value = feature[found_field]
                    if value is not None:
                        try:
                            # ⬅️ OBSŁUŻ WARTOŚCI ZE ZNAKIEM %
                            if isinstance(value, str):
                                # Usuń znak % jeśli jest
                                value = value.replace('%', '').replace(',', '.').strip()
                            
                            float_value = float(value)
                            
                            # Jeśli to pole _float (wartość 0-1), zamień na procent
                            if '_float' in found_field.lower() and float_value <= 1:
                                float_value = float_value * 100
                            
                            wskazniki[wskaznik_name] = float_value
                            self.data[wskaznik_name] = float_value
                            wskazniki_found = True
                            print(f"✅ Pobrano {wskaznik_name} = {float_value:.2f}% z pola '{found_field}'")
                        except (ValueError, TypeError) as e:
                            print(f"⚠️ Nie udało się przekonwertować {wskaznik_name} z pola '{found_field}': {value} - {e}")
            else:
                # Użyj danych z pliku
                wskazniki[wskaznik_name] = self.data.get(wskaznik_name, 0)
                wskazniki_found = True
        
        
        # Wyświetl tabelę
        source_info = "z pliku" if data_from_file else f"z warstwy: {layer_name}"
        
        if wskazniki_found:
            html = f"""
            <p style='color: #4CAF50; font-weight: bold;'>✅ Dane pobrane {source_info}</p>
            <table style='border-collapse: collapse; width: 100%;'>
                <thead>
                    <tr style='background-color: #e3f2fd;'>
                        <th style='border: 1px solid #ccc; padding: 8px;'>Wskaźnik</th>
                        <th style='border: 1px solid #ccc; padding: 8px;'>Wartość istniejąca</th>
                    </tr>
                </thead>
                <tbody>
            """
            
            for wskaznik_name in ['WPZ', 'WPBC']:
                value = wskazniki.get(wskaznik_name, 0)
                # WPZ/WPBC bywaja juz gotowym tekstem z "%" (pole QVariant.String),
                # a czasem liczba. Format .0f dziala tylko na liczbie -> rzutuj bezpiecznie.
                value_str = value if isinstance(value, str) else f"{float(value):.0f}%"
                html += f"""
                    <tr>
                        <td style='border: 1px solid #ccc; padding: 8px; font-weight: bold;'>{wskaznik_name}</td>
                        <td style='border: 1px solid #ccc; padding: 8px; text-align: right;'>{value_str}</td>
                    </tr>
                """
            for wskaznik_name in ['WIZ', 'WNIZ',]:
                value = wskazniki.get(wskaznik_name, 0)
                try:
                    value_str = f"{float(value):.2f}"
                except (ValueError, TypeError):
                    value_str = str(value)
                html += f"""
                    <tr>
                        <td style='border: 1px solid #ccc; padding: 8px; font-weight: bold;'>{wskaznik_name}</td>
                        <td style='border: 1px solid #ccc; padding: 8px; text-align: right;'>{value_str}</td>
                    </tr>
                """
            
            html += """
                </tbody>
            </table>
            <p style='color: #666; font-size: 11px; margin-top: 10px;'>
            <i>To są wartości ISTNIEJĄCEJ zabudowy (stan faktyczny)</i>
            </p>
            """
        else:
            html = f"""
            <p style='color: #FF9800; font-weight: bold;'>⚠️ Dane pobrane {source_info}</p>
            <p style='color: #666;'>Warstwa nie zawiera wskaźników zabudowy.<br>
            To normalne dla warstwy 'granica_terenu' przed krokiem 10.</p>
            <p style='color: #666; font-size: 11px;'>
            Identyfikator: {self.data.get('identyfikator_dzialki', 'nie znaleziono')}<br>
            Powierzchnia: {self.data.get('powierzchnia_dzialki', 'nie znaleziono')} m²
            </p>
            """
        
        self.wskazniki_label.setText(html)    
        
        # Oblicz PBC istniejącą w m²
        try:
            wpbc_ist = self.data.get('WPBC', 0)
            pow_dzialki_str = self.data.get('powierzchnia_dzialki', '0')
            pow_dzialki = float(pow_dzialki_str) if pow_dzialki_str else 0
            
            pbc_ist_m2 = (wpbc_ist / 100) * pow_dzialki
            self.pbc_istniejaca_label.setText(f"{pbc_ist_m2:.2f}")
        except Exception as e:
            print(f"⚠️ Nie udało się obliczyć PBC istniejącej: {e}")
            self.pbc_istniejaca_label.setText("0.00")
        
        
    # ══════════════════════════════════════════════════════════════════
    # NARZĘDZIA LICZĄCE Z ZAZNACZENIA NA MAPIE
    # ══════════════════════════════════════════════════════════════════

    def _aktywuj_zaznaczanie(self, nazwa_warstwy):
        """Wspólna obsługa przycisków „Zaznacz na mapie”."""
        try:
            nw = _narzedzia_wyboru()
        except Exception as e:
            QMessageBox.critical(self, "Brak modułu",
                                 f"Nie znaleziono narzedzia_wyboru.py:\n{e}")
            return
        ok, komunikat = nw.aktywuj_zaznaczanie(nazwa_warstwy)
        if ok:
            print(f"🖱️ {komunikat}")
        else:
            QMessageBox.warning(self, "Zaznaczanie", komunikat)

    def zaznacz_budynki_sasiednie(self):
        try:
            nw = _narzedzia_wyboru()
            self._aktywuj_zaznaczanie(nw.WARSTWA_BUDYNKI)
        except Exception as e:
            QMessageBox.critical(self, "Błąd", str(e))

    def zaznacz_linie_zabudowy(self):
        try:
            nw = _narzedzia_wyboru()
            self._aktywuj_zaznaczanie(nw.WARSTWA_LINIE)
        except Exception as e:
            QMessageBox.critical(self, "Błąd", str(e))

    def policz_srednia_wysokosc_sasiadow(self):
        """Średnia wysokość zaznaczonych budynków na działkach sąsiednich."""
        try:
            nw = _narzedzia_wyboru()
        except Exception as e:
            QMessageBox.critical(self, "Brak modułu",
                                 f"Nie znaleziono narzedzia_wyboru.py:\n{e}")
            return

        ok, dane, komunikat = nw.srednia_wysokosc_sasiadow()
        if not ok:
            QMessageBox.warning(self, "Średnia wysokość", komunikat)
            return

        self.sr_wys_sasiednie_edit.setText(nw.formatuj_metry(dane["srednia"]))
        self.data['sr_wys_dz_sasiednie_lista'] = "; ".join(
            nw.formatuj_metry(w) for w in dane["wartosci"]
        )
        self.wys_info_label.setText(
            f"<span style='color: #2E7D32; font-size: 10px;'>✅ {komunikat}</span>"
        )
        print(f"📏 {komunikat}")

    def porownaj_linie_zabudowy(self):
        """Porównanie linii zabudowy z dwóch działek sąsiednich (§ 3 ust. 1 / 2)."""
        try:
            nw = _narzedzia_wyboru()
        except Exception as e:
            QMessageBox.critical(self, "Brak modułu",
                                 f"Nie znaleziono narzedzia_wyboru.py:\n{e}")
            return

        ok, dane, komunikat = nw.linia_zabudowy_z_zaznaczenia()
        if not ok:
            QMessageBox.warning(self, "Linia zabudowy", komunikat)
            return

        self.lz_ustalona_edit.setText(nw.formatuj_metry(dane["ustalona"]))
        idx = self.par3_combo.findText(dane["ustep"])
        if idx >= 0:
            self.par3_combo.setCurrentIndex(idx)
        self.data['Lz_sasiednie_lista'] = "; ".join(
            nw.formatuj_metry(d) for d in dane["odleglosci"]
        )
        self.data['Lz_sasiednie_rowne'] = "tak" if dane["rowne"] else "nie"

        kolor = "#2E7D32" if dane["rowne"] else "#EF6C00"
        self.lz_info_label.setText(
            f"<span style='color: {kolor}; font-size: 10px;'>✅ {komunikat}</span>"
        )
        print(f"📐 {komunikat}")

    def odczytaj_plan_ogolny(self, auto=False):
        """
        Odczytuje ustalenia planu ogólnego dla terenu inwestycji.

        auto=True (wywołanie przy otwarciu okna) — jeśli dane zostały już
        wcześniej zapisane w pliku, tylko je wyświetla, bez ponownego
        przecinania warstw.
        """
        if auto and str(self.data.get('pog_dostepny', '')) == 'tak':
            self.pog_label.setText(self._pog_html(self.data, zrodlo="z pliku"))
            return

        try:
            pog = _plan_ogolny()
        except Exception as e:
            self.pog_label.setText(
                f"<span style='color: red;'>❌ Brak modułu plan_ogolny.py ({e})</span>"
            )
            return

        try:
            dane = pog.zbierz_dane_pog()
        except Exception as e:
            print(f"⚠️ Błąd odczytu planu ogólnego: {e}")
            import traceback
            traceback.print_exc()
            self.pog_label.setText(
                f"<span style='color: red;'>❌ Błąd odczytu planu ogólnego: {e}</span>"
            )
            return

        self.data.update(dane)
        self.pog_label.setText(self._pog_html(dane, zrodlo="z warstw projektu"))

        if dane.get('pog_dostepny') != 'tak':
            print("⚠️ Plan ogólny: " + str(dane.get('pog_uwagi', '')))

    @staticmethod
    def _pog_html(dane, zrodlo=""):
        """Tabelka z ustaleniami strefy planistycznej."""
        if str(dane.get('pog_dostepny', 'nie')) != 'tak':
            uwagi = dane.get('pog_uwagi', '') or "nie znaleziono warstw planu ogólnego"
            return (
                "<p style='color: #FF9800; font-weight: bold;'>⚠️ Nie odczytano strefy "
                "planistycznej</p>"
                f"<p style='color: #666;'>{uwagi}</p>"
                "<p style='color: #666; font-size: 11px;'>Wczytaj definicję warstw planu "
                "ogólnego (POG.qlr) i upewnij się, że istnieje warstwa "
                "<i>granica_terenu</i>.</p>"
            )

        wiersze = [
            ("Strefa planistyczna",
             f"{dane.get('pog_strefa_oznaczenie', '')} – "
             f"{dane.get('pog_strefa_nazwa_mian', dane.get('pog_strefa_nazwa', ''))}"),
            ("Profil podstawowy", dane.get('pog_profil_podstawowy', '')),
            ("Profil dodatkowy", dane.get('pog_profil_dodatkowy', '')),
            ("Maks. nadziemna intensywność", dane.get('pog_maks_nadz_intens', '')),
            ("Maks. udział pow. zabudowy", dane.get('pog_maks_udzial_pow_zab', '')),
            ("Maks. wysokość zabudowy", dane.get('pog_maks_wysokosc', '')),
            ("Min. udział pow. biol. czynnej", dane.get('pog_min_pbc', '')),
            ("Obszar uzupełnienia zabudowy",
             ("TAK – " + str(dane.get('pog_ouz_oznaczenie', '')))
             if str(dane.get('pog_ouz', 'nie')) == 'tak' else "nie"),
            ("Obszar zabudowy śródmiejskiej",
             "TAK" if str(dane.get('pog_ozs', 'nie')) == 'tak' else "nie"),
        ]

        html = (
            f"<p style='color: #4CAF50; font-weight: bold;'>✅ Ustalenia odczytane "
            f"{zrodlo}</p>"
            "<table style='border-collapse: collapse; width: 100%;'>"
        )
        for etykieta, wartosc in wiersze:
            html += (
                "<tr>"
                "<td style='border: 1px solid #ccc; padding: 6px; font-weight: bold; "
                f"width: 45%;'>{etykieta}</td>"
                f"<td style='border: 1px solid #ccc; padding: 6px;'>{wartosc}</td>"
                "</tr>"
            )
        html += "</table>"

        uwagi = dane.get('pog_uwagi', '')
        if uwagi:
            html += (
                f"<p style='color: #FF9800; font-size: 11px; margin-top: 8px;'>"
                f"⚠️ {uwagi}</p>"
            )
        return html

    def add_building_params(self, existing_params=None):
            """Dodaj formularz parametrów budynku - Z MIN/MAX i AUTO-OBLICZANIEM"""
            building_num = self.buildings_layout.count() + 1
            suffix = chr(ord('x') + self.buildings_layout.count())
            
            group = QGroupBox(f"Typ budynku #{building_num} (suffix: {suffix})")
            group.setStyleSheet("QGroupBox { font-weight: bold; color: #007bff; }")
            layout = QFormLayout()
            
            fields = {}
            
            # funkcja budynku
            funkcja_budynku = QLineEdit(str(existing_params.get('funkcja_budynku', '')) if existing_params else '')
            funkcja_budynku.setPlaceholderText("np. mieszkalny, gospodarczy, usługowy")
            layout.addRow("<b>Funkcja budynku:</b>", funkcja_budynku)
            fields['funkcja_budynku'] = funkcja_budynku
            
            # Liczba budynków
            liczba_budynkow = QLineEdit(str(existing_params.get('liczba_budynkow', '1')) if existing_params else '1')
            liczba_budynkow.textChanged.connect(self.recalculate_planned_indicators)
            layout.addRow("Liczba budynków:", liczba_budynkow)
            fields['liczba_budynkow'] = liczba_budynkow
            
            # ⬅️ POWIERZCHNIA ZABUDOWY - MIN/MAX
            pow_zab_min = QLineEdit(str(existing_params.get('powierzchnia_zabudowy_min', '')) if existing_params else '')
            pow_zab_max = QLineEdit(str(existing_params.get('powierzchnia_zabudowy_max', '')) if existing_params else '')
            pow_zab_min.textChanged.connect(lambda: self.auto_calculate_kondygnacje(fields))
            pow_zab_max.textChanged.connect(lambda: self.auto_calculate_kondygnacje(fields))
            pow_zab_layout = QHBoxLayout()
            pow_zab_layout.addWidget(QLabel("Min:"))
            pow_zab_layout.addWidget(pow_zab_min)
            pow_zab_layout.addWidget(QLabel("Max:"))
            pow_zab_layout.addWidget(pow_zab_max)
            layout.addRow("<b>Powierzchnia zabudowy [m²]:</b>", pow_zab_layout)
            fields['powierzchnia_zabudowy_min'] = pow_zab_min
            fields['powierzchnia_zabudowy_max'] = pow_zab_max
            
            # ⬅️ LICZBA KONDYGNACJI PODZIEMNYCH - MIN/MAX
            liczba_kond_podz_min = QLineEdit(str(existing_params.get('liczba_kond_podziemnych_min', '0')) if existing_params else '0')
            liczba_kond_podz_max = QLineEdit(str(existing_params.get('liczba_kond_podziemnych_max', '0')) if existing_params else '0')
            liczba_kond_podz_min.textChanged.connect(lambda: self.auto_calculate_kondygnacje(fields))
            liczba_kond_podz_max.textChanged.connect(lambda: self.auto_calculate_kondygnacje(fields))
            liczba_kond_podz_layout = QHBoxLayout()
            liczba_kond_podz_layout.addWidget(QLabel("Min:"))
            liczba_kond_podz_layout.addWidget(liczba_kond_podz_min)
            liczba_kond_podz_layout.addWidget(QLabel("Max:"))
            liczba_kond_podz_layout.addWidget(liczba_kond_podz_max)
            layout.addRow("Liczba kond. PODZIEMNYCH:", liczba_kond_podz_layout)
            fields['liczba_kond_podziemnych_min'] = liczba_kond_podz_min
            fields['liczba_kond_podziemnych_max'] = liczba_kond_podz_max
            
            # ⬅️ LICZBA KONDYGNACJI NADZIEMNYCH - MIN/MAX
            liczba_kond_nadz_min = QLineEdit(str(existing_params.get('liczba_kond_nadziemnych_min', '1')) if existing_params else '1')
            liczba_kond_nadz_max = QLineEdit(str(existing_params.get('liczba_kond_nadziemnych_max', '1')) if existing_params else '1')
            liczba_kond_nadz_min.textChanged.connect(lambda: self.auto_calculate_kondygnacje(fields))
            liczba_kond_nadz_max.textChanged.connect(lambda: self.auto_calculate_kondygnacje(fields))
            liczba_kond_nadz_layout = QHBoxLayout()
            liczba_kond_nadz_layout.addWidget(QLabel("Min:"))
            liczba_kond_nadz_layout.addWidget(liczba_kond_nadz_min)
            liczba_kond_nadz_layout.addWidget(QLabel("Max:"))
            liczba_kond_nadz_layout.addWidget(liczba_kond_nadz_max)
            layout.addRow("Liczba kond. NADZIEMNYCH:", liczba_kond_nadz_layout)
            fields['liczba_kond_nadziemnych_min'] = liczba_kond_nadz_min
            fields['liczba_kond_nadziemnych_max'] = liczba_kond_nadz_max
            
            # ⬅️ SUMA POWIERZCHNI KONDYGNACJI PODZIEMNYCH - MIN/MAX (auto-obliczane, ale edytowalne)
            pow_podz_min = QLineEdit(str(existing_params.get('powierzchnia_kond_podziemnych_min', '')) if existing_params else '')
            pow_podz_max = QLineEdit(str(existing_params.get('powierzchnia_kond_podziemnych_max', '')) if existing_params else '')
            pow_podz_min.setPlaceholderText("Auto lub ręcznie")
            pow_podz_max.setPlaceholderText("Auto lub ręcznie")
            pow_podz_min.textChanged.connect(self.recalculate_planned_indicators)
            pow_podz_max.textChanged.connect(self.recalculate_planned_indicators)
            pow_podz_layout = QHBoxLayout()
            pow_podz_layout.addWidget(QLabel("Min:"))
            pow_podz_layout.addWidget(pow_podz_min)
            pow_podz_layout.addWidget(QLabel("Max:"))
            pow_podz_layout.addWidget(pow_podz_max)
            layout.addRow("<b>Suma pow. kond. PODZ. [m²]:</b>", pow_podz_layout)
            fields['powierzchnia_kond_podziemnych_min'] = pow_podz_min
            fields['powierzchnia_kond_podziemnych_max'] = pow_podz_max
            
            # ⬅️ SUMA POWIERZCHNI KONDYGNACJI NADZIEMNYCH - MIN/MAX (auto-obliczane, ale edytowalne)
            pow_nadz_min = QLineEdit(str(existing_params.get('powierzchnia_kond_nadziemnych_min', '')) if existing_params else '')
            pow_nadz_max = QLineEdit(str(existing_params.get('powierzchnia_kond_nadziemnych_max', '')) if existing_params else '')
            pow_nadz_min.setPlaceholderText("Auto lub ręcznie")
            pow_nadz_max.setPlaceholderText("Auto lub ręcznie")
            pow_nadz_min.textChanged.connect(self.recalculate_planned_indicators)
            pow_nadz_max.textChanged.connect(self.recalculate_planned_indicators)
            pow_nadz_layout = QHBoxLayout()
            pow_nadz_layout.addWidget(QLabel("Min:"))
            pow_nadz_layout.addWidget(pow_nadz_min)
            pow_nadz_layout.addWidget(QLabel("Max:"))
            pow_nadz_layout.addWidget(pow_nadz_max)
            layout.addRow("<b>Suma pow. kond. NADZ. [m²]:</b>", pow_nadz_layout)
            fields['powierzchnia_kond_nadziemnych_min'] = pow_nadz_min
            fields['powierzchnia_kond_nadziemnych_max'] = pow_nadz_max
            
            # Szerokość frontu
            szer_front_min = QLineEdit(str(existing_params.get('WszerFrontmin', '')) if existing_params else '')
            szer_front_max = QLineEdit(str(existing_params.get('WszerFrontmax', '')) if existing_params else '')
            szer_layout = QHBoxLayout()
            szer_layout.addWidget(QLabel("Min:"))
            szer_layout.addWidget(szer_front_min)
            szer_layout.addWidget(QLabel("Max:"))
            szer_layout.addWidget(szer_front_max)
            layout.addRow("Szerokość frontu [m]:", szer_layout)
            fields['WszerFrontmin'] = szer_front_min
            fields['WszerFrontmax'] = szer_front_max
            
            # Wysokość
            wys_min = QLineEdit(str(existing_params.get('w_wys_min', '')) if existing_params else '')
            wys_max = QLineEdit(str(existing_params.get('w_wys_max', '')) if existing_params else '')
            wys_layout = QHBoxLayout()
            wys_layout.addWidget(QLabel("Min:"))
            wys_layout.addWidget(wys_min)
            wys_layout.addWidget(QLabel("Max:"))
            wys_layout.addWidget(wys_max)
            layout.addRow("Wysokość [m]:", wys_layout)
            fields['w_wys_min'] = wys_min
            fields['w_wys_max'] = wys_max
            
            # ⬅️ DACH - WIELOKROTNY WYBÓR (QListWidget z checkboxami)
            dach_list = QListWidget()
            dach_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            dach_list.setMaximumHeight(100)
            dach_typy = [
                "płaski",
                "jednospadowy",
                "dwuspadowy",
                "czterospadowy",
                "wielospadowy",
                "inny"
            ]
            for typ in dach_typy:
                dach_list.addItem(typ)
            
            # Zaznacz wybrane typy jeśli istnieją
            if existing_params and 'dachProj' in existing_params:
                selected_types = existing_params['dachProj'].split(' lub ')
                for i in range(dach_list.count()):
                    item = dach_list.item(i)
                    if item.text() in selected_types:
                        item.setSelected(True)
            
            layout.addRow("Typ dachu (wielokrotny):", dach_list)
            fields['dachProj'] = dach_list
            
            # Kalenica
            kalenica_proj = QComboBox()
            kalenica_proj.addItems([
                "prostopadły", "równoległy", "prostopadły lub równoległy", "inny"
            ])
            if existing_params and 'kalenicaProj' in existing_params:
                index = kalenica_proj.findText(str(existing_params['kalenicaProj']))
                if index >= 0:
                    kalenica_proj.setCurrentIndex(index)
            layout.addRow("Układ głównej kalenicy względem frontu działki:", kalenica_proj)
            fields['kalenicaProj'] = kalenica_proj
            
            # Nachylenie dachu
            nachylenie_min = QLineEdit(str(existing_params.get('nachylenieProjMin', '')) if existing_params else '')
            nachylenie_max = QLineEdit(str(existing_params.get('nachylenieProjMax', '')) if existing_params else '')
            nachylenie_layout = QHBoxLayout()
            nachylenie_layout.addWidget(QLabel("Min:"))
            nachylenie_layout.addWidget(nachylenie_min)
            nachylenie_layout.addWidget(QLabel("Max:"))
            nachylenie_layout.addWidget(nachylenie_max)
            layout.addRow("Nachylenie dachu [°]:", nachylenie_layout)
            fields['nachylenieProjMin'] = nachylenie_min
            fields['nachylenieProjMax'] = nachylenie_max
            
            if self.buildings_layout.count() > 0:
                remove_btn = ModernButton("🗑️ Usuń ten typ", "danger")
                remove_btn.clicked.connect(lambda: self.remove_building_params(group))
                layout.addRow("", remove_btn)
            
            # Odtworz stan "auto / recznie" dla sum powierzchni kondygnacji,
            # inaczej po wczytaniu z pliku liczba kondygnacji nic by nie zmieniala.
            if existing_params:
                self.oznacz_kondygnacje_z_pliku(fields)

            group.setLayout(layout)
            group.fields = fields
            group.suffix = suffix
            
            self.buildings_layout.addWidget(group)            
            
            
    # Pola sum powierzchni kondygnacji i sposob ich wyliczania z liczby kondygnacji
    POLA_KONDYGNACJI = (
        ('powierzchnia_kond_podziemnych_min', 'powierzchnia_zabudowy_min', 'liczba_kond_podziemnych_min'),
        ('powierzchnia_kond_podziemnych_max', 'powierzchnia_zabudowy_max', 'liczba_kond_podziemnych_max'),
        ('powierzchnia_kond_nadziemnych_min', 'powierzchnia_zabudowy_min', 'liczba_kond_nadziemnych_min'),
        ('powierzchnia_kond_nadziemnych_max', 'powierzchnia_zabudowy_max', 'liczba_kond_nadziemnych_max'),
    )

    @staticmethod
    def _pole_jest_auto(pole):
        """
        Czy pole trzyma wartość wpisaną przez automat (a nie ręczną korektę)?

        Puste pole traktujemy jak automatyczne. Poza tym porównujemy treść
        z ostatnią wartością, którą automat sam wpisał — dzięki temu ręczna
        zmiana nie jest już nadpisywana przy kolejnym przeliczeniu.
        """
        tekst = pole.text().strip()
        if not tekst:
            return True
        zapamietana = pole.property('auto_value')
        return zapamietana is not None and tekst == str(zapamietana)

    @classmethod
    def _ustaw_auto(cls, pole, wartosc):
        """Wpisuje wartość automatu i zapamiętuje ją do późniejszego porównania."""
        tekst = str(wartosc)
        pole.setText(tekst)
        pole.setProperty('auto_value', tekst)

    @classmethod
    def oznacz_kondygnacje_z_pliku(cls, fields):
        """
        Odtwarza stan "auto / ręcznie" po wczytaniu danych z pliku.

        Bez tego wszystkie wczytane sumy wyglądały na ręczne i liczba
        kondygnacji przestawała cokolwiek zmieniać.
        """
        for pole_sumy, pole_pow, pole_liczby in cls.POLA_KONDYGNACJI:
            try:
                pow_zab = float(fields[pole_pow].text() or 0)
                liczba = int(float(fields[pole_liczby].text() or 0))
            except (ValueError, TypeError):
                continue
            oczekiwana = round(pow_zab * liczba, 2)
            biezaca = fields[pole_sumy].text().strip()
            if not biezaca:
                continue
            try:
                if abs(float(biezaca.replace(',', '.')) - oczekiwana) < 0.01:
                    fields[pole_sumy].setProperty('auto_value', biezaca)
            except (ValueError, TypeError):
                continue

    def auto_calculate_kondygnacje(self, fields):
        """
        Przelicza sumy powierzchni kondygnacji z powierzchni zabudowy
        i liczby kondygnacji. Pola zmienione ręcznie zostawia w spokoju.
        """
        try:
            wartosci = {}
            for pole_sumy, pole_pow, pole_liczby in self.POLA_KONDYGNACJI:
                pow_zab = float(fields[pole_pow].text() or 0)
                liczba = int(float(fields[pole_liczby].text() or 0))
                wartosci[pole_sumy] = round(pow_zab * liczba, 2)
        except (ValueError, TypeError):
            return  # niepełne dane w formularzu - nic nie ruszamy

        for pole_sumy, _, _ in self.POLA_KONDYGNACJI:
            pole = fields[pole_sumy]
            if not self._pole_jest_auto(pole):
                continue  # użytkownik wpisał swoją wartość
            pole.blockSignals(True)
            self._ustaw_auto(pole, wartosci[pole_sumy])
            pole.blockSignals(False)

        self.recalculate_planned_indicators()

    def on_obsluga_kom_changed(self, text):
        """Pokaż/ukryj pole działki dojazdu w zależności od typu obsługi"""
        if text == "bezpośrednia":
            self.dzialka_dojazd_edit.hide()
            self.dzialka_dojazd_label.hide()
            self.dzialka_dojazd_reminder.hide()
        else:
            self.dzialka_dojazd_edit.show()
            self.dzialka_dojazd_label.show()
            self.dzialka_dojazd_reminder.show()
    
    def _update_l_park_default(self, text):
        """Jeśli l_park jest puste lub równe poprzedniej wartości max, zaktualizuj."""
        current_l_park = self.l_park_edit.text().strip()
        old_max = str(self.data.get('w_l_park_max', ''))
        if not current_l_park or current_l_park == old_max:
            self.l_park_edit.setText(text)        
    
    def remove_building_params(self, group_widget):
        """Usuń parametry budynku"""
        reply = QMessageBox.question(
            self,
            "Potwierdzenie",
            "Czy na pewno usunąć ten typ budynku?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.buildings_layout.removeWidget(group_widget)
            group_widget.deleteLater()
            
            for i in range(self.buildings_layout.count()):
                widget = self.buildings_layout.itemAt(i).widget()
                if isinstance(widget, QGroupBox):
                    new_num = i + 1
                    new_suffix = chr(ord('x') + i)
                    widget.setTitle(f"Typ budynku #{new_num} (suffix: {new_suffix})")
                    widget.suffix = new_suffix
            
            self.recalculate_planned_indicators()
    
    
    
    
    def recalculate_planned_indicators(self):
            """
            OBLICZANIE WSKAŹNIKÓW PLANOWANEJ ZABUDOWY - MIN i MAX
            Na podstawie danych z formularza budynków
            """
            try:
                # Pobierz powierzchnię działki
                pow_dzialki_str = self.powierzchnia_dzialki_edit.text()
                if not pow_dzialki_str:
                    self.wskazniki_plan_label.setText("<i>Wprowadź powierzchnię działki aby obliczyć wskaźniki</i>")
                    return
                
                pow_dzialki = float(pow_dzialki_str)
                if pow_dzialki <= 0:
                    self.wskazniki_plan_label.setText("<i>Powierzchnia działki musi być > 0</i>")
                    return
                
                # ⬅️ POBIERZ PBC PLANOWANĄ - MIN i MAX
                pow_pbc_min_str = self.powierzchnia_pbc_min_edit.text()
                pow_pbc_max_str = self.powierzchnia_pbc_max_edit.text()
                pow_pbc_min = float(pow_pbc_min_str) if pow_pbc_min_str else 0
                pow_pbc_max = float(pow_pbc_max_str) if pow_pbc_max_str else 0
                
                # ⬅️ ZBIERZ DANE Z PLANOWANYCH BUDYNKÓW - MIN i MAX
                suma_pow_zabudowy_min = 0
                suma_pow_zabudowy_max = 0
                suma_pow_kond_podziemne_min = 0
                suma_pow_kond_podziemne_max = 0
                suma_pow_kond_nadziemne_min = 0
                suma_pow_kond_nadziemne_max = 0
                
                for i in range(self.buildings_layout.count()):
                    widget = self.buildings_layout.itemAt(i).widget()
                    if isinstance(widget, QGroupBox):
                        fields = widget.fields
                        
                        liczba = int(fields['liczba_budynkow'].text() or 0)
                        
                        pow_zab_min = float(fields['powierzchnia_zabudowy_min'].text() or 0)
                        pow_zab_max = float(fields['powierzchnia_zabudowy_max'].text() or 0)
                        pow_podz_min = float(fields['powierzchnia_kond_podziemnych_min'].text() or 0)
                        pow_podz_max = float(fields['powierzchnia_kond_podziemnych_max'].text() or 0)
                        pow_nadz_min = float(fields['powierzchnia_kond_nadziemnych_min'].text() or 0)
                        pow_nadz_max = float(fields['powierzchnia_kond_nadziemnych_max'].text() or 0)
                        
                        suma_pow_zabudowy_min += pow_zab_min * liczba
                        suma_pow_zabudowy_max += pow_zab_max * liczba
                        suma_pow_kond_podziemne_min += pow_podz_min * liczba
                        suma_pow_kond_podziemne_max += pow_podz_max * liczba
                        suma_pow_kond_nadziemne_min += pow_nadz_min * liczba
                        suma_pow_kond_nadziemne_max += pow_nadz_max * liczba
                
                # ===== POBIERZ WSKAŹNIKI ISTNIEJĄCEJ ZABUDOWY =====
                wpz_ist = self.data.get('WPZ', 0)
                wiz_ist = self.data.get('WIZ', 0)
                wniz_ist = self.data.get('WNIZ', 0)
                wpbc_ist = self.data.get('WPBC', 0)
                
                # Sprawdź czy teren zabudowany
                teren_zabudowany = self.obecne_zagospodarowanie_combo.currentText() != "niezabudowany"
                
                # ===== POBIERZ TRYB PLANOWANEJ ZABUDOWY =====
                tryb_zabudowy = self.tryb_zabudowy_combo.currentText()
                # Na terenie niezabudowanym nie ma czego sumowac - tryb
                # "uzupelnia" nie moze doliczac nieistniejacej zabudowy,
                # nawet jesli warstwa niesie niezerowe wskazniki (np. sprzed
                # wyburzenia).
                uzupelnia = ("uzupełnia" in tryb_zabudowy) and teren_zabudowany
                
                # ===== OBLICZ WSKAŹNIKI PLANOWANE - MIN i MAX =====
                wpz_plan_min = (suma_pow_zabudowy_min / pow_dzialki * 100)
                wpz_plan_max = (suma_pow_zabudowy_max / pow_dzialki * 100)
                
                wiz_plan_min = ((suma_pow_kond_podziemne_min + suma_pow_kond_nadziemne_min) / pow_dzialki)
                wiz_plan_max = ((suma_pow_kond_podziemne_max + suma_pow_kond_nadziemne_max) / pow_dzialki)
                
                wniz_plan_min = (suma_pow_kond_nadziemne_min / pow_dzialki)
                wniz_plan_max = (suma_pow_kond_nadziemne_max / pow_dzialki)
                
                wpbc_plan_min = (pow_pbc_min / pow_dzialki * 100)
                wpbc_plan_max = (pow_pbc_max / pow_dzialki * 100)
                
                # ⬅️ JEŚLI UZUPEŁNIA - DODAJ WSKAŹNIKI ISTNIEJĄCE (oprócz WPBC!)
                if uzupelnia:
                    wpz_plan_min += wpz_ist
                    wpz_plan_max += wpz_ist
                    wiz_plan_min += wiz_ist
                    wiz_plan_max += wiz_ist
                    wniz_plan_min += wniz_ist
                    wniz_plan_max += wniz_ist
                    # WPBC NIE sumujemy - zostaje jak podał inwestor
                
                # Zapisz do self.data
                self.data['tryb_planowanej_zabudowy'] = tryb_zabudowy
                self.data['w_wpz_planowane_min'] = wpz_plan_min
                self.data['w_wpz_planowane_max'] = wpz_plan_max
                self.data['w_wiz_planowane_min'] = wiz_plan_min
                self.data['w_wiz_planowane_max'] = wiz_plan_max
                self.data['w_wniz_planowane_min'] = wniz_plan_min
                self.data['w_wniz_planowane_max'] = wniz_plan_max
                self.data['w_wpbc_planowane_min'] = wpbc_plan_min
                self.data['w_wpbc_planowane_max'] = wpbc_plan_max
                
                # ⬅️ WYŚWIETL TABELĘ Z 4 KOLUMNAMI
                if not teren_zabudowany:
                    tryb_info = ("teren NIEZABUDOWANY - wskaźniki wyłącznie z planowanej "
                                 "zabudowy (tryb nie ma zastosowania)")
                elif uzupelnia:
                    tryb_info = "SUMA z istniejącą"
                else:
                    tryb_info = "ZASTĘPUJE istniejącą"
            
                html = f"""
                <p style='color: #1976D2; font-weight: bold; margin-bottom: 10px;'>
                📌 Tryb: {tryb_info}
                </p>
                <table style='border-collapse: collapse; width: 100%;'>
                    <thead>
                        <tr style='background-color: #c8e6c9;'>
                            <th style='border: 1px solid #4CAF50; padding: 8px;'>Wskaźnik</th>
                            <th style='border: 1px solid #4CAF50; padding: 8px;'>Istniejący</th>
                            <th style='border: 1px solid #4CAF50; padding: 8px;'>Planowany MIN</th>
                            <th style='border: 1px solid #4CAF50; padding: 8px;'>Planowany MAX</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td style='border: 1px solid #4CAF50; padding: 8px; font-weight: bold;'>WPZ</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wpz_ist:.0f}%</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wpz_plan_min:.0f}%</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wpz_plan_max:.0f}%</td>
                        </tr>
                        <tr>
                            <td style='border: 1px solid #4CAF50; padding: 8px; font-weight: bold;'>WIZ</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wiz_ist:.2f}</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wiz_plan_min:.2f}</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wiz_plan_max:.2f}</td>
                        </tr>
                        <tr>
                            <td style='border: 1px solid #4CAF50; padding: 8px; font-weight: bold;'>WNIZ</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wniz_ist:.2f}</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wniz_plan_min:.2f}</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wniz_plan_max:.2f}</td>
                        </tr>
                        <tr>
                            <td style='border: 1px solid #4CAF50; padding: 8px; font-weight: bold;'>WPBC</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wpbc_ist:.0f}%</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wpbc_plan_min:.0f}%</td>
                            <td style='border: 1px solid #4CAF50; padding: 8px; text-align: right;'>{wpbc_plan_max:.0f}%</td>
                        </tr>
                    </tbody>
                </table>
                <br>
                <p style='color: #666; font-size: 11px;'>
                <b>Dane wejściowe:</b><br>
                - Pow. działki: {pow_dzialki:.2f} m²<br>
                - Pow. zabudowy (plan.): {suma_pow_zabudowy_min:.2f} - {suma_pow_zabudowy_max:.2f} m²<br>
                - Pow. kond. podziemne (plan.): {suma_pow_kond_podziemne_min:.2f} - {suma_pow_kond_podziemne_max:.2f} m²<br>
                - Pow. kond. nadziemne (plan.): {suma_pow_kond_nadziemne_min:.2f} - {suma_pow_kond_nadziemne_max:.2f} m²<br>
                - Pow. biol. czynna (plan.): {pow_pbc_min:.2f} - {pow_pbc_max:.2f} m²<br>
                - Teren: {'zabudowany' if teren_zabudowany else 'niezabudowany'}<br>
                <br>
                <i>WPBC nie jest sumowany ani pomniejszany w żadnym trybie - wchodzi
                dokładnie taki, jaki podał inwestor.</i>
                </p>
                """
                
                self.wskazniki_plan_label.setText(html)
                
            except ValueError:
                self.wskazniki_plan_label.setText("<span style='color: red;'>Błąd: Wprowadź poprawne liczby</span>")
            except Exception as e:
                self.wskazniki_plan_label.setText(f"<span style='color: red;'>Błąd obliczeń: {e}</span>")            
            
            
    def update_pbc_istniejaca(self):
        """Aktualizuj wartość PBC istniejącej w m²"""
        try:
            wpbc_ist = self.data.get('WPBC', 0)
            pow_dzialki_str = self.powierzchnia_dzialki_edit.text()
            pow_dzialki = float(pow_dzialki_str) if pow_dzialki_str else 0
            
            pbc_ist_m2 = (wpbc_ist / 100) * pow_dzialki
            self.pbc_istniejaca_label.setText(f"{pbc_ist_m2:.2f}")
        except (ValueError, TypeError):
            self.pbc_istniejaca_label.setText("0.00")
            
            
    def load_existing_data(self):
        """Wczytaj istniejące dane z pliku jeśli istnieje"""
        project_directory = get_project_directory()
        if not project_directory:
            return
        
        file_path = Path(project_directory) / "dane_dzialki_przedmiotowej.xlsx"
        
        if not file_path.exists():
            return
        
        try:
            _ensure_pandas()
            df_export = pd.read_excel(file_path, sheet_name='do_eksportu')
            
            for _, row in df_export.iterrows():
                nazwa_pola = row['nazwa_pola']
                wartosc = row['wartosc']
                self.data[nazwa_pola] = wartosc
            
            suffixes = set()
            for key in self.data.keys():
                if key.startswith('WszerFrontmin_'):
                    suffix = key.split('_')[-1]
                    suffixes.add(suffix)
            
            for suffix in sorted(suffixes):
                params = {
                'funkcja_budynku': self.data.get(f'funkcja_budynku_{suffix}', ''),
                'liczba_budynkow': self.data.get(f'liczba_budynkow_{suffix}', 1),
                'powierzchnia_zabudowy_min': self.data.get(f'powierzchnia_zabudowy_min_{suffix}', ''),
                'powierzchnia_zabudowy_max': self.data.get(f'powierzchnia_zabudowy_max_{suffix}', ''),
                'liczba_kond_podziemnych_min': self.data.get(f'liczba_kond_podziemnych_min_{suffix}', '0'),
                'liczba_kond_podziemnych_max': self.data.get(f'liczba_kond_podziemnych_max_{suffix}', '0'),
                'liczba_kond_nadziemnych_min': self.data.get(f'liczba_kond_nadziemnych_min_{suffix}', '1'),
                'liczba_kond_nadziemnych_max': self.data.get(f'liczba_kond_nadziemnych_max_{suffix}', '1'),
                'powierzchnia_kond_podziemnych_min': self.data.get(f'powierzchnia_kond_podziemnych_min_{suffix}', ''),
                'powierzchnia_kond_podziemnych_max': self.data.get(f'powierzchnia_kond_podziemnych_max_{suffix}', ''),
                'powierzchnia_kond_nadziemnych_min': self.data.get(f'powierzchnia_kond_nadziemnych_min_{suffix}', ''),
                'powierzchnia_kond_nadziemnych_max': self.data.get(f'powierzchnia_kond_nadziemnych_max_{suffix}', ''),
                'WszerFrontmin': self.data.get(f'WszerFrontmin_{suffix}', ''),
                'WszerFrontmax': self.data.get(f'WszerFrontmax_{suffix}', ''),
                'w_wys_min': self.data.get(f'w_wys_min_{suffix}', ''),
                'w_wys_max': self.data.get(f'w_wys_max_{suffix}', ''),
                'dachProj': self.data.get(f'dachProj{suffix.upper()}', ''),
                'kalenicaProj': self.data.get(f'kalenica{suffix.upper()}proj', ''),
                'nachylenieProjMin': self.data.get(f'nachylenieProjMin_{suffix}', ''),
                'nachylenieProjMax': self.data.get(f'nachylenieProjMax_{suffix}', '')
            }
                self.building_params.append(params)
            
            # ⬅️ KONWERTUJ WSZYSTKIE WARTOŚCI NA ODPOWIEDNIE TYPY
            for key, value in self.data.items():
                _ensure_pandas()
                if pd.isna(value):
                    self.data[key] = ''
                elif isinstance(value, float) and key not in ['WPZ', 'WIZ', 'WNIZ', 'WPBC', 
                                                               'w_wpz_planowane_min', 'w_wpz_planowane_max',
                                                               'w_wiz_planowane_min', 'w_wiz_planowane_max',
                                                               'w_wniz_planowane_min', 'w_wniz_planowane_max',
                                                               'w_wpbc_planowane_min', 'w_wpbc_planowane_max']:
                    # Jeśli to float ale nie wskaźnik, zamień na string
                    if value == int(value):
                        self.data[key] = str(int(value))
                    else:
                        self.data[key] = str(value)
            
            print(f"✅ Wczytano dane z pliku: {file_path}")
            
        except Exception as e:
            print(f"⚠️ Nie udało się wczytać danych z pliku: {e}")
    
    def save_and_accept(self):
            """Zapisz dane i zamknij dialog"""
            if not self.validate_data():
                return
            
            self.data['znak_sprawy'] = self.znak_sprawy_edit.text()
            self.data['data_wniosku'] = self.data_wniosku_edit.text()
            self.data['adres_dzialki'] = self.adres_edit.text()
            self.data['identyfikator_dzialki'] = self.identyfikator_edit.text()
            self.data['Nazwa_inwestycji'] = self.nazwa_inwestycji_edit.text()
            self.data['Rodzaj_zabudowy'] = self.rodzaj_zabudowy_edit.text()
            
            # ⬅️ POŁĄCZ COMBO + POLE TEKSTOWE
            obecne_zagosp_combo = self.obecne_zagospodarowanie_combo.currentText()
            rodzaj_istniejacy = self.rodzaj_istniejacy_edit.text().strip()
            if rodzaj_istniejacy:
                self.data['obecne_zagospodarowanie'] = f"{obecne_zagosp_combo} - {rodzaj_istniejacy}"
            else:
                self.data['obecne_zagospodarowanie'] = obecne_zagosp_combo
            self.data['rodzaj_istniejacy'] = rodzaj_istniejacy
            # ⬅️ OBSŁUGA KOMUNIKACYJNA
            self.data['obsluga_komunikacyjna'] = self.obsluga_kom_combo.currentText()
            self.data['dzialka_dojazd'] = self.dzialka_dojazd_edit.text()
            self.data['tryb_planowanej_zabudowy'] = self.tryb_zabudowy_combo.currentText()
            
            # ⬅️ PLAN OGÓLNY – wybory sterujące wariantami w szablonie
            self.data['pog_zgodnosc_funkcji'] = self.pog_zgodnosc_combo.currentText()
            self.data['podstawa_ustalen'] = (
                "§ 2 ust. 3" if self.podstawa_ustalen_combo.currentIndex() == 1
                else "§ 2 ust. 2"
            )
            self.data['wyb_par3'] = self.par3_combo.currentText()
            self.data['wyb_par7'] = self.par7_combo.currentText()
            self.data['sr_wys_dz_sasiednie'] = self.sr_wys_sasiednie_edit.text().strip()
            self.data['Lz_ustalona'] = self.lz_ustalona_edit.text().strip()
            
            # ⬅️ LINIA ZABUDOWY
            lz_w = self.lz_w_edit.text().strip()
            if not lz_w or lz_w == '0':
                lz_w = "nie dotyczy"
            self.data['Lz_w'] = lz_w
            self.data['rodzaj_Lz'] = self.rodzaj_lz_combo.currentText()
            
            # ⬅️ PARKOWANIE
            self.data['w_l_park_min'] = self.w_l_park_min_edit.text().strip()
            self.data['w_l_park_max'] = self.w_l_park_max_edit.text().strip()
            l_park = self.l_park_edit.text().strip()
            if not l_park and self.data['w_l_park_max']:
                l_park = self.data['w_l_park_max']
            self.data['l_park'] = l_park
            
            # ⬅️ PROMESY
            self.data['wodkan_data'] = self.wodkan_data_edit.text().strip()
            self.data['wodkan_znak'] = self.wodkan_znak_edit.text().strip()
            self.data['energa_data'] = self.energa_data_edit.text().strip()
            self.data['energa_znak'] = self.energa_znak_edit.text().strip()
            
            self.data['powierzchnia_dzialki'] = self.powierzchnia_dzialki_edit.text()
            self.data['powierzchnia_biologicznie_czynna_min'] = self.powierzchnia_pbc_min_edit.text()
            self.data['powierzchnia_biologicznie_czynna_max'] = self.powierzchnia_pbc_max_edit.text()
            
            building_data = []
            for i in range(self.buildings_layout.count()):
                widget = self.buildings_layout.itemAt(i).widget()
                if isinstance(widget, QGroupBox):
                    fields = widget.fields
                    suffix = widget.suffix
                    
                    dach_list = fields['dachProj']
                    selected_dach = []
                    for i in range(dach_list.count()):
                        if dach_list.item(i).isSelected():
                            selected_dach.append(dach_list.item(i).text())
                    dach_proj_str = ' lub '.join(selected_dach) if selected_dach else 'brak'
                
                    
                    params = {
                    'suffix': suffix,
                    'funkcja_budynku': fields['funkcja_budynku'].text() or '',
                    'liczba_budynkow': fields['liczba_budynkow'].text() or '1',
                    'powierzchnia_zabudowy_min': fields['powierzchnia_zabudowy_min'].text() or '0',
                    'powierzchnia_zabudowy_max': fields['powierzchnia_zabudowy_max'].text() or '0',
                    'liczba_kond_podziemnych_min': fields['liczba_kond_podziemnych_min'].text() or '0',
                    'liczba_kond_podziemnych_max': fields['liczba_kond_podziemnych_max'].text() or '0',
                    'liczba_kond_nadziemnych_min': fields['liczba_kond_nadziemnych_min'].text() or '1',
                    'liczba_kond_nadziemnych_max': fields['liczba_kond_nadziemnych_max'].text() or '1',
                    'powierzchnia_kond_podziemnych_min': fields['powierzchnia_kond_podziemnych_min'].text() or '0',
                    'powierzchnia_kond_podziemnych_max': fields['powierzchnia_kond_podziemnych_max'].text() or '0',
                    'powierzchnia_kond_nadziemnych_min': fields['powierzchnia_kond_nadziemnych_min'].text() or '0',
                    'powierzchnia_kond_nadziemnych_max': fields['powierzchnia_kond_nadziemnych_max'].text() or '0',
                    'WszerFrontmin': fields['WszerFrontmin'].text() or '0',
                    'WszerFrontmax': fields['WszerFrontmax'].text() or '0',
                    'w_wys_min': fields['w_wys_min'].text() or '0',
                    'w_wys_max': fields['w_wys_max'].text() or '0',
                    'dachProj': dach_proj_str,
                    'kalenicaProj': fields['kalenicaProj'].currentText(),
                    'nachylenieProjMin': fields['nachylenieProjMin'].text() or '0',
                    'nachylenieProjMax': fields['nachylenieProjMax'].text() or '0'
                    }
                    building_data.append(params)
            
            if self.save_to_excel(building_data):
                QMessageBox.information(
                    self,
                    "Sukces",
                    "✅ Dane działki zapisane pomyślnie!\n\n"
                    "Plik: dane_dzialki_przedmiotowej.xlsx"
                )
                self.accept()
            else:
                QMessageBox.warning(
                    self,
                    "Błąd",
                    "❌ Nie udało się zapisać danych"
                )    
    
    def validate_data(self):
        """Walidacja danych"""
        if not self.znak_sprawy_edit.text():
            QMessageBox.warning(self, "Błąd", "Pole 'Znak sprawy' jest wymagane!")
            return False
        
        if not self.nazwa_inwestycji_edit.text():
            QMessageBox.warning(self, "Błąd", "Pole 'Nazwa inwestycji' jest wymagane!")
            return False
        
        if not self.powierzchnia_dzialki_edit.text():
            QMessageBox.warning(self, "Błąd", "Pole 'Powierzchnia działki' jest wymagane!")
            return False
        
        try:
            pow = float(self.powierzchnia_dzialki_edit.text())
            if pow <= 0:
                raise ValueError()
        except:
            QMessageBox.warning(self, "Błąd", "Powierzchnia działki musi być liczbą > 0!")
            return False
        
        if self.buildings_layout.count() == 0:
            QMessageBox.warning(self, "Błąd", "Dodaj przynajmniej jeden typ budynku!")
            return False
        
        return True
    
    def save_to_excel(self, building_data):
            """Zapisz dane do pliku Excel z dwoma arkuszami - Z MIN/MAX"""
            project_directory = get_project_directory()
            if not project_directory:
                print("❌ Projekt nie jest zapisany!")
                return False
            
            file_path = Path(project_directory) / "dane_dzialki_przedmiotowej.xlsx"
            
            try:
                # === ARKUSZ 1: dane_dzialki ===
                dane_arkusz = []
                
                dane_arkusz.append(['Dane działki przedmiotowej', '', '', '', '', '', ''])
                dane_arkusz.append(['znak sprawy', self.data.get('znak_sprawy', ''), '', '', '', '', ''])
                dane_arkusz.append(['z dnia', self.data.get('data_wniosku', ''), '', '', '', '', ''])
                dane_arkusz.append(['Adres', self.data.get('adres_dzialki', ''), '', '', '', '', ''])
                dane_arkusz.append(['identyfikator działki', self.data.get('identyfikator_dzialki', ''), '', '', '', '', ''])
                dane_arkusz.append(['gmina', self.data.get('nazwa_gminy', ''), '', '', '', '', ''])
                dane_arkusz.append(['Nazwa inwestycji', self.data.get('Nazwa_inwestycji', ''), '', '', '', '', ''])
                dane_arkusz.append(['Rodzaj zabudowy', self.data.get('Rodzaj_zabudowy', ''), '', '', '', '', ''])
                dane_arkusz.append(['teren obecnie:', self.data.get('obecne_zagospodarowanie', ''), '', '', '', '', ''])
                dane_arkusz.append(['powierzchnia działki [m2]', self.data.get('powierzchnia_dzialki', ''), '', '', '', '', ''])
                dane_arkusz.append(['powierzchnia biologicznie czynna - planowana [m2]', 
                                   self.data.get('powierzchnia_biologicznie_czynna_min', ''),
                                   self.data.get('powierzchnia_biologicznie_czynna_max', ''), '', '', '', ''])
                dane_arkusz.append(['obsługa komunikacyjna', self.data.get('obsluga_komunikacyjna', ''), '', '', '', '', ''])
                if self.data.get('dzialka_dojazd'):
                    dane_arkusz.append(['działka dojazdu', self.data.get('dzialka_dojazd', ''), '', '', '', '', ''])
                dane_arkusz.append(['linia zabudowy wnioskowana', self.data.get('Lz_w', 'nie dotyczy'), '', '', '', '', ''])
                dane_arkusz.append(['rodzaj linii zabudowy', self.data.get('rodzaj_Lz', ''), '', '', '', '', ''])
                dane_arkusz.append(['wnioskowane miejsca parkingowe', 
                                   f"min: {self.data.get('w_l_park_min', '')}", 
                                   f"max: {self.data.get('w_l_park_max', '')}", '', '', '', ''])
                dane_arkusz.append(['ustalona liczba miejsc parkingowych', self.data.get('l_park', ''), '', '', '', '', ''])
                dane_arkusz.append(['promesa wod-kan', self.data.get('wodkan_data', ''), self.data.get('wodkan_znak', ''), '', '', '', ''])
                dane_arkusz.append(['promesa energetyczna', self.data.get('energa_data', ''), self.data.get('energa_znak', ''), '', '', '', ''])
                dane_arkusz.append(['tryb planowanej zabudowy', self.data.get('tryb_planowanej_zabudowy', ''), '', '', '', '', ''])    
                dane_arkusz.append(['', '', '', '', '', '', ''])
                
                # ⬅️ USTALENIA PLANU OGÓLNEGO
                dane_arkusz.append(['Plan ogólny - strefa planistyczna', '', '', '', '', '', ''])
                dane_arkusz.append(['strefa', self.data.get('pog_strefa_oznaczenie', ''),
                                   self.data.get('pog_strefa_nazwa_mian', ''), '', '', '', ''])
                dane_arkusz.append(['profil podstawowy', self.data.get('pog_profil_podstawowy', ''), '', '', '', '', ''])
                dane_arkusz.append(['profil dodatkowy', self.data.get('pog_profil_dodatkowy', ''), '', '', '', '', ''])
                dane_arkusz.append(['maks. nadziemna intensywność zabudowy', self.data.get('pog_maks_nadz_intens', ''), '', '', '', '', ''])
                dane_arkusz.append(['maks. udział powierzchni zabudowy', self.data.get('pog_maks_udzial_pow_zab', ''), '', '', '', '', ''])
                dane_arkusz.append(['maks. wysokość zabudowy', self.data.get('pog_maks_wysokosc', ''), '', '', '', '', ''])
                dane_arkusz.append(['min. udział pow. biologicznie czynnej', self.data.get('pog_min_pbc', ''), '', '', '', '', ''])
                dane_arkusz.append(['obszar uzupełnienia zabudowy', self.data.get('pog_ouz', ''),
                                   self.data.get('pog_ouz_oznaczenie', ''), '', '', '', ''])
                dane_arkusz.append(['obszar zabudowy śródmiejskiej', self.data.get('pog_ozs', ''), '', '', '', '', ''])
                dane_arkusz.append(['podstawa ustaleń (rozporządzenie)', self.data.get('podstawa_ustalen', ''), '', '', '', '', ''])
                dane_arkusz.append(['śr. wysokość na działkach sąsiednich', self.data.get('sr_wys_dz_sasiednie', ''),
                                   self.data.get('sr_wys_dz_sasiednie_lista', ''), '', '', '', ''])
                dane_arkusz.append(['ustalona linia zabudowy', self.data.get('Lz_ustalona', ''),
                                   self.data.get('Lz_sasiednie_lista', ''), '', '', '', ''])
                dane_arkusz.append(['', '', '', '', '', '', ''])
                
                # ⬅️ NOWA STRUKTURA - ISTNIEJĄCE vs PLANOWANE MIN/MAX
                dane_arkusz.append(['Wskaźniki zabudowy', 'Istniejące', 'Planowane MIN', 'Planowane MAX', '', '', ''])
                dane_arkusz.append(['WPZ [%]', 
                                   f"{self.data.get('WPZ', 0):.0f}%",
                                   f"{self.data.get('w_wpz_planowane_min', 0):.0f}%",
                                   f"{self.data.get('w_wpz_planowane_max', 0):.0f}%", '', '', ''])
                dane_arkusz.append(['WIZ',
                                   f"{self.data.get('WIZ', 0):.2f}",
                                   f"{self.data.get('w_wiz_planowane_min', 0):.2f}",
                                   f"{self.data.get('w_wiz_planowane_max', 0):.2f}", '', '', ''])
                dane_arkusz.append(['WNIZ',
                                   f"{self.data.get('WNIZ', 0):.2f}",
                                   f"{self.data.get('w_wniz_planowane_min', 0):.2f}",
                                   f"{self.data.get('w_wniz_planowane_max', 0):.2f}", '', '', ''])
                dane_arkusz.append(['WPBC [%]',
                                   f"{self.data.get('WPBC', 0):.0f}%",
                                   f"{self.data.get('w_wpbc_planowane_min', 0):.0f}%",
                                   f"{self.data.get('w_wpbc_planowane_max', 0):.0f}%", '', '', ''])
                dane_arkusz.append(['', '', '', '', '', '', ''])
                
                dane_arkusz.append(['planowana zabudowa - parametry', '', '', '', '', '', ''])
                
                for i, building in enumerate(building_data, 1):
                    suffix = building['suffix']
                    dane_arkusz.append([f'Typ budynku #{i} (suffix: {suffix})', 'min', 'max', '', '', '', ''])
                    dane_arkusz.append(['Liczba budynków', building['liczba_budynkow'], '', '', '', '', ''])
                    dane_arkusz.append(['powierzchnia zabudowy [m2]', 
                                       building['powierzchnia_zabudowy_min'], 
                                       building['powierzchnia_zabudowy_max'], '', '', '', ''])
                    dane_arkusz.append(['pow. kond. podziemnych [m2]', 
                                       building['powierzchnia_kond_podziemnych_min'],
                                       building['powierzchnia_kond_podziemnych_max'], '', '', '', ''])
                    dane_arkusz.append(['pow. kond. nadziemnych [m2]', 
                                       building['powierzchnia_kond_nadziemnych_min'],
                                       building['powierzchnia_kond_nadziemnych_max'], '', '', '', ''])
                    dane_arkusz.append(['szerokość elewacji frontowej [m]', 
                                       building['WszerFrontmin'], building['WszerFrontmax'], '', '', '', ''])
                    dane_arkusz.append(['wysokość [m]', 
                                       building['w_wys_min'], building['w_wys_max'], '', '', '', ''])
                    dane_arkusz.append(['typ dachu', building['dachProj'], '', '', '', '', ''])
                    dane_arkusz.append(['kalenica', building['kalenicaProj'], '', '', '', '', ''])
                    dane_arkusz.append(['nachylenie dachu [°]', 
                                       building['nachylenieProjMin'], building['nachylenieProjMax'], '', '', '', ''])
                    dane_arkusz.append(['liczba kond. podziemnych', 
                                       building['liczba_kond_podziemnych_min'], 
                                       building['liczba_kond_podziemnych_max'], '', '', '', ''])
                    dane_arkusz.append(['liczba kond. nadziemnych', 
                                       building['liczba_kond_nadziemnych_min'], 
                                       building['liczba_kond_nadziemnych_max'], '', '', '', ''])
                    dane_arkusz.append(['', '', '', '', '', '', ''])
                
                _ensure_pandas()
                df_dane = pd.DataFrame(dane_arkusz)
                
                # === ARKUSZ 2: do_eksportu ===
                eksport_data = []
                
                eksport_data.append(['znak_sprawy', self.data.get('znak_sprawy', '')])
                eksport_data.append(['data_wniosku', self.data.get('data_wniosku', '')])
                eksport_data.append(['adres_dzialki', self.data.get('adres_dzialki', '')])
                eksport_data.append(['identyfikator_dzialki', self.data.get('identyfikator_dzialki', '')])
                eksport_data.append(['nazwa_gminy', self.data.get('nazwa_gminy', '')])
                eksport_data.append(['Nazwa_inwestycji', self.data.get('Nazwa_inwestycji', '')])
                eksport_data.append(['Rodzaj_zabudowy', self.data.get('Rodzaj_zabudowy', '')])
                eksport_data.append(['obecne_zagospodarowanie', self.data.get('obecne_zagospodarowanie', '')])
                eksport_data.append(['rodzaj_istniejacy', self.data.get('rodzaj_istniejacy', '')])
                eksport_data.append(['powierzchnia_dzialki', self.data.get('powierzchnia_dzialki', '')])
                eksport_data.append(['powierzchnia_biologicznie_czynna_min', self.data.get('powierzchnia_biologicznie_czynna_min', '')])
                eksport_data.append(['powierzchnia_biologicznie_czynna_max', self.data.get('powierzchnia_biologicznie_czynna_max', '')])
                
                # ⬅️ WSKAŹNIKI ISTNIEJĄCE (pojedyncze wartości)
                eksport_data.append(['WPZ', self.data.get('WPZ', 0)])
                eksport_data.append(['WIZ', self.data.get('WIZ', 0)])
                eksport_data.append(['WNIZ', self.data.get('WNIZ', 0)])
                eksport_data.append(['WPBC', self.data.get('WPBC', 0)])
                
                # ⬅️ WSKAŹNIKI PLANOWANE - MIN i MAX (Z ZAOKRĄGLENIEM!)
                # WPZ i WPBC - do liczby całkowitej
                # WIZ i WNIZ - do 2 miejsc po przecinku
                eksport_data.append(['w_wpz_planowane_min', int(round(self.data.get('w_wpz_planowane_min', 0)))])
                eksport_data.append(['w_wpz_planowane_max', int(round(self.data.get('w_wpz_planowane_max', 0)))])
                eksport_data.append(['w_wiz_planowane_min', round(self.data.get('w_wiz_planowane_min', 0), 2)])
                eksport_data.append(['w_wiz_planowane_max', round(self.data.get('w_wiz_planowane_max', 0), 2)])
                eksport_data.append(['w_wniz_planowane_min', round(self.data.get('w_wniz_planowane_min', 0), 2)])
                eksport_data.append(['w_wniz_planowane_max', round(self.data.get('w_wniz_planowane_max', 0), 2)])
                eksport_data.append(['w_wpbc_planowane_min', int(round(self.data.get('w_wpbc_planowane_min', 0)))])
                eksport_data.append(['w_wpbc_planowane_max', int(round(self.data.get('w_wpbc_planowane_max', 0)))])
                
                # ⬅️ OBSŁUGA KOMUNIKACYJNA
                eksport_data.append(['obsluga_komunikacyjna', self.data.get('obsluga_komunikacyjna', '')])
                eksport_data.append(['dzialka_dojazd', self.data.get('dzialka_dojazd', '')])
                
                # ⬅️ LINIA ZABUDOWY
                eksport_data.append(['Lz_w', self.data.get('Lz_w', 'nie dotyczy')])
                eksport_data.append(['rodzaj_Lz', self.data.get('rodzaj_Lz', 'obowiązującą')])
                
                # ⬅️ PARKOWANIE
                eksport_data.append(['w_l_park_min', self.data.get('w_l_park_min', '')])
                eksport_data.append(['w_l_park_max', self.data.get('w_l_park_max', '')])
                eksport_data.append(['l_park', self.data.get('l_park', '')])
                
                # ⬅️ PROMESY
                eksport_data.append(['wodkan_data', self.data.get('wodkan_data', '')])
                eksport_data.append(['wodkan_znak', self.data.get('wodkan_znak', '')])
                eksport_data.append(['energa_data', self.data.get('energa_data', '')])
                eksport_data.append(['energa_znak', self.data.get('energa_znak', '')])
                
                eksport_data.append(['tryb_planowanej_zabudowy', self.data.get('tryb_planowanej_zabudowy', '')])
                
                # ⬅️ PLAN OGÓLNY
                for _pole_pog in POLA_POG_DO_EKSPORTU:
                    eksport_data.append([_pole_pog, self.data.get(_pole_pog, '')])
                
                for building in building_data:
                    suffix = building['suffix']
                    
                    eksport_data.append([f'funkcja_budynku_{suffix}', building['funkcja_budynku']])  # ⬅️ DODAJ TO
                    eksport_data.append([f'liczba_budynkow_{suffix}', building['liczba_budynkow']])
                    eksport_data.append([f'powierzchnia_zabudowy_min_{suffix}', building['powierzchnia_zabudowy_min']])
                    eksport_data.append([f'powierzchnia_zabudowy_max_{suffix}', building['powierzchnia_zabudowy_max']])
                    eksport_data.append([f'powierzchnia_kond_podziemnych_min_{suffix}', building['powierzchnia_kond_podziemnych_min']])
                    eksport_data.append([f'powierzchnia_kond_podziemnych_max_{suffix}', building['powierzchnia_kond_podziemnych_max']])
                    eksport_data.append([f'powierzchnia_kond_nadziemnych_min_{suffix}', building['powierzchnia_kond_nadziemnych_min']])
                    eksport_data.append([f'powierzchnia_kond_nadziemnych_max_{suffix}', building['powierzchnia_kond_nadziemnych_max']])
                    eksport_data.append([f'WszerFrontmin_{suffix}', building['WszerFrontmin']])
                    eksport_data.append([f'WszerFrontmax_{suffix}', building['WszerFrontmax']])
                    eksport_data.append([f'w_wys_min_{suffix}', building['w_wys_min']])
                    eksport_data.append([f'w_wys_max_{suffix}', building['w_wys_max']])
                    eksport_data.append([f'dachProj{suffix.upper()}', building['dachProj']])
                    eksport_data.append([f'kalenica{suffix.upper()}proj', building['kalenicaProj']])
                    eksport_data.append([f'nachylenieProjMin_{suffix}', building['nachylenieProjMin']])
                    eksport_data.append([f'nachylenieProjMax_{suffix}', building['nachylenieProjMax']])
                    eksport_data.append([f'liczba_kond_podziemnych_min_{suffix}', building['liczba_kond_podziemnych_min']])
                    eksport_data.append([f'liczba_kond_podziemnych_max_{suffix}', building['liczba_kond_podziemnych_max']])
                    eksport_data.append([f'liczba_kond_nadziemnych_min_{suffix}', building['liczba_kond_nadziemnych_min']])
                    eksport_data.append([f'liczba_kond_nadziemnych_max_{suffix}', building['liczba_kond_nadziemnych_max']])
                    
                _ensure_pandas()
                df_eksport = pd.DataFrame(eksport_data, columns=['nazwa_pola', 'wartosc'])
                
                _ensure_pandas()
                with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                    df_dane.to_excel(writer, sheet_name='dane_dzialki', index=False, header=False)
                    df_eksport.to_excel(writer, sheet_name='do_eksportu', index=False)
                
                print(f"✅ Zapisano dane do: {file_path}")
                return True
                
            except Exception as e:
                print(f"❌ Błąd podczas zapisu: {e}")
                import traceback
                traceback.print_exc()
                return False

# ==================== KROK 1: GRANICA TERENU - NOWY SYSTEM ====================

class SelectFeatureDockWidget(QDockWidget):
    """Niemodalny dock widget do wyboru obiektu - nie blokuje QGIS"""
    
    # Sygnał emitowany po potwierdzeniu wyboru
    feature_selected = None  # Będziemy używać callback zamiast sygnału
    
    def __init__(self, callback_function, parent=None):
        super().__init__("Wybór terenu przedmiotowego", parent)
        self.setObjectName("SelectFeatureDockWidget")
        
        self.callback_function = callback_function
        self.selected_layer = None
        self.selected_feature_id = None
        
        # Ustaw właściwości dock widget
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable | 
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        
        self.init_ui()
        self.populate_layers()
    
    def init_ui(self):
        """Inicjalizacja interfejsu"""
        main_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        # Header
        header_label = QLabel(
            "🗺️ <b>Wybór terenu przedmiotowego</b>\n\n"
            "To okno możesz przesunąć lub zminimalizować.\n"
            "Wybierz warstwę i zaznacz obiekt na mapie."
        )
        header_label.setWordWrap(True)
        header_label.setStyleSheet(
            "padding: 10px; background-color: #e3f2fd; "
            "border-radius: 5px; border: 1px solid #2196F3;"
        )
        layout.addWidget(header_label)
        
        # Wybór warstwy
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        self.layer_combo = QComboBox()
        self.layer_combo.setMinimumHeight(35)
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)
        form_layout.addRow("📋 Wybierz warstwę:", self.layer_combo)
        
        layout.addLayout(form_layout)
        
        # Instrukcje
        instructions_group = QGroupBox("📝 Instrukcje")
        instructions_layout = QVBoxLayout()
        
        instructions_text = QLabel(
            "<ol>"
            "<li><b>Wybierz warstwę</b> z listy powyżej</li>"
            "<li><b>Zaznacz obiekt</b> na mapie (pojedynczy!)</li>"
            "<li><b>Kliknij 'Potwierdź'</b> poniżej</li>"
            "</ol>"
            "<p style='color: #666; font-size: 11px;'>"
            "<i>💡 Wskazówka: Użyj narzędzia 'Zaznacz obiekty' <img src=':/images/themes/default/mActionSelectRectangle.svg' width='16'></i>"
            "</p>"
        )
        instructions_text.setWordWrap(True)
        instructions_layout.addWidget(instructions_text)
        instructions_group.setLayout(instructions_layout)
        layout.addWidget(instructions_group)
        
        # Status - automatycznie aktualizowany
        status_frame = QFrame()
        status_frame.setFrameShape(QFrame.Shape.StyledPanel)
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel("⏸️ Oczekiwanie na wybór warstwy...")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "padding: 8px; background-color: #fff3cd; "
            "border-radius: 4px; font-weight: bold;"
        )
        status_layout.addWidget(self.status_label)
        
        status_frame.setLayout(status_layout)
        layout.addWidget(status_frame)
        
        # Przyciski
        buttons_layout = QHBoxLayout()
        
        self.confirm_button = ModernButton("✓ Potwierdź wybór", "success")
        self.confirm_button.clicked.connect(self.confirm_selection)
        self.confirm_button.setEnabled(False)  # Wyłączony dopóki nie zaznaczono
        buttons_layout.addWidget(self.confirm_button)
        
        cancel_button = ModernButton("✗ Anuluj", "secondary")
        cancel_button.clicked.connect(self.cancel_selection)
        buttons_layout.addWidget(cancel_button)
        
        layout.addLayout(buttons_layout)
        
        # Spacer
        layout.addStretch()
        
        main_widget.setLayout(layout)
        self.setWidget(main_widget)
    
    def populate_layers(self):
        """Wypełnij listę warstw poligonowych"""
        from qgis.core import QgsWkbTypes
        
        polygon_layers = []
        
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):  # warstwa wektorowa (dziala w QGIS 3 i 4)
                if layer.geometryType() == QgsWkbTypes.GeometryType.PolygonGeometry:
                    polygon_layers.append(layer)
        
        if not polygon_layers:
            self.status_label.setText("⚠️ Nie znaleziono warstw poligonowych!")
            self.status_label.setStyleSheet(
                "padding: 8px; background-color: #ffcdd2; "
                "border-radius: 4px; font-weight: bold; color: #c62828;"
            )
            return
        
        for layer in polygon_layers:
            layer_name = layer.name()
            feature_count = layer.featureCount()
            display_text = f"{layer_name} ({feature_count} obiektów)"
            self.layer_combo.addItem(display_text, layer)
        
        # Spróbuj ustawić domyślnie działki
        for i, layer in enumerate(polygon_layers):
            if 'dzialk' in layer.name().lower():
                self.layer_combo.setCurrentIndex(i)
                break
    
    def on_layer_changed(self, index):
        """Obsłuż zmianę warstwy"""
        if index < 0:
            return
        
        # Odłącz stary sygnał jeśli był
        try:
            if hasattr(self, 'selected_layer') and self.selected_layer is not None:
                if not sip.isdeleted(self.selected_layer):
                    try:
                        self.selected_layer.selectionChanged.disconnect(self.update_selection_status)
                    except Exception:
                        # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
                        pass  # nosec B110
        except (RuntimeError, AttributeError):
            # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
            pass  # nosec B110
        
        layer = self.layer_combo.currentData()
        if not layer:
            return
        
        self.selected_layer = layer
        
        # Ustaw jako aktywną
        iface.setActiveLayer(layer)
        
        # Podłącz sygnał zmiany zaznaczenia
        layer.selectionChanged.connect(self.update_selection_status)
        
        # Wyczyść zaznaczenie
        layer.removeSelection()
        
        # Zaktualizuj status
        self.update_selection_status()
    
    def update_selection_status(self):
        """Aktualizuj status na podstawie zaznaczenia - wywoływane automatycznie!"""
        if not self.selected_layer:
            self.status_label.setText("⏸️ Wybierz warstwę z listy")
            self.status_label.setStyleSheet(
                "padding: 8px; background-color: #fff3cd; "
                "border-radius: 4px; font-weight: bold;"
            )
            self.confirm_button.setEnabled(False)
            return
        
        selected_count = self.selected_layer.selectedFeatureCount()
        
        if selected_count == 0:
            self.status_label.setText(
                f"⏸️ Warstwa: <b>{self.selected_layer.name()}</b><br>"
                f"Zaznacz obiekt na mapie używając narzędzia zaznaczania"
            )
            self.status_label.setStyleSheet(
                "padding: 8px; background-color: #fff3cd; "
                "border-radius: 4px; font-weight: bold;"
            )
            self.confirm_button.setEnabled(False)
            
        elif selected_count == 1:
            selected_features = self.selected_layer.selectedFeatures()
            feature = selected_features[0]
            
            # Pokaż dodatkowe info o obiekcie
            info_text = f"✅ Zaznaczono obiekt w warstwie: <b>{self.selected_layer.name()}</b>"
            
            # Spróbuj pokazać identyfikator jeśli istnieje
            field_names = [f.name() for f in self.selected_layer.fields()]
            id_fields = ['id', 'identyfikator', 'teryt', 'iddzialki', 'numer']
            
            for id_field in id_fields:
                matching = [f for f in field_names if id_field in f.lower()]
                if matching:
                    value = feature[matching[0]]
                    if value:
                        info_text += f"<br>ID: <i>{value}</i>"
                        break
            
            self.status_label.setText(info_text)
            self.status_label.setStyleSheet(
                "padding: 8px; background-color: #c8e6c9; "
                "border-radius: 4px; font-weight: bold; color: #2e7d32;"
            )
            self.confirm_button.setEnabled(True)
            
        else:
            self.status_label.setText(
                f"⚠️ Zaznaczono <b>{selected_count}</b> obiektów<br>"
                f"Wybierz tylko <b>JEDEN</b> obiekt!"
            )
            self.status_label.setStyleSheet(
                "padding: 8px; background-color: #ffcdd2; "
                "border-radius: 4px; font-weight: bold; color: #c62828;"
            )
            self.confirm_button.setEnabled(False)
    
    def confirm_selection(self):
        """Potwierdź wybór"""
        if not self.selected_layer:
            QMessageBox.warning(
                self, "Błąd", 
                "Musisz wybrać warstwę!"
            )
            return
        
        selected_features = self.selected_layer.selectedFeatures()
        
        if len(selected_features) != 1:
            QMessageBox.warning(
                self, "Błąd",
                f"Zaznaczono {len(selected_features)} obiektów!\n\n"
                "Wybierz tylko JEDEN obiekt."
            )
            return
        
        # Zapisz ID wybranego obiektu
        self.selected_feature_id = selected_features[0].id()
        
        # Odłącz sygnały
        try:
            if hasattr(self, 'selected_layer') and self.selected_layer is not None:
                if not sip.isdeleted(self.selected_layer):
                    try:
                        self.selected_layer.selectionChanged.disconnect(self.update_selection_status)
                    except Exception:
                        # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
                        pass  # nosec B110
        except (RuntimeError, AttributeError):
            # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
            pass  # nosec B110
        
        # Wywołaj callback
        if self.callback_function:
            self.callback_function(self.selected_layer, self.selected_feature_id)
        
        # Zamknij widget
        self.close()
    
    def cancel_selection(self):
        """Anuluj wybór"""
        # Odłącz sygnały
        try:
            if hasattr(self, 'selected_layer') and self.selected_layer is not None:
                if not sip.isdeleted(self.selected_layer):
                    try:
                        self.selected_layer.selectionChanged.disconnect(self.update_selection_status)
                    except Exception:
                        # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
                        pass  # nosec B110
        except (RuntimeError, AttributeError):
            # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
            pass  # nosec B110
        
        # Wywołaj callback z None
        if self.callback_function:
            self.callback_function(None, None)
        
        # Zamknij widget
        self.close()
    
    def closeEvent(self, event):
        """Obsłuż zamknięcie okna"""
        # Odłącz sygnały
        try:
            if hasattr(self, 'selected_layer') and self.selected_layer is not None:
                if not sip.isdeleted(self.selected_layer):
                    try:
                        self.selected_layer.selectionChanged.disconnect(self.update_selection_status)
                    except Exception:
                        # celowo ignorowane: operacja best-effort (np. odlaczenie sygnalu, ktory moze nie byc podlaczony)
                        pass  # nosec B110
        except (RuntimeError, AttributeError):
            # Obiekt został już usunięty przez QGIS
            pass
        
        event.accept()

def validate_and_create_uldk_layer(source_layer, feature_id, project_directory):
    """
    Walidacja i utworzenie warstwy 'Wyniki wyszukiwania ULDK' z pojedynczego obiektu
    WERSJA 2.1 - z REPROJEKCJĄ do CRS projektu
    
    Args:
        source_layer: Warstwa źródłowa
        feature_id: ID wybranego obiektu
        project_directory: Katalog projektu
    
    Returns:
        tuple: (success: bool, message: str)
    """
    from qgis.core import (QgsVectorLayer, QgsFeature, QgsField, QgsVectorFileWriter, 
                          QgsCoordinateTransformContext, QgsCoordinateTransform)
    from qgis.PyQt.QtCore import QVariant
    from pathlib import Path
    
    # Te same wymagane pola co dla działek
    required_fields = {
        'ID_DZIALKI': QVariant.String,
        'NUMER_DZIALKI': QVariant.String,
        'NUMER_OBREBU': QVariant.String,
        'POLE_EWIDENCYJNE': QVariant.Double
    }
    
    print(f"\n{'='*60}")
    print("WALIDACJA I UTWORZENIE WARSTWY ULDK")
    print(f"{'='*60}")
    print(f"Warstwa źródłowa: {source_layer.name()}")
    print(f"Feature ID: {feature_id}")
    
    # === POBIERZ CRS PROJEKTU ===
    project_crs = QgsProject.instance().crs()
    source_crs = source_layer.crs()
    
    print(f"  📍 CRS warstwy źródłowej: {source_crs.authid()}")
    print(f"  📍 CRS projektu: {project_crs.authid()}")
    
    # Czy potrzebna reprojekcja?
    needs_transform = (source_crs.authid() != project_crs.authid())
    if needs_transform:
        print(f"  🔄 Wymagana reprojekcja: {source_crs.authid()} → {project_crs.authid()}")
        transform = QgsCoordinateTransform(source_crs, project_crs, QgsProject.instance())
    else:
        print("  ✓ CRS zgodny - brak reprojekcji")
        transform = None
    
    # Pobierz wybrany obiekt
    feature = source_layer.getFeature(feature_id)
    if not feature or not feature.hasGeometry():
        return False, "Nie udało się pobrać wybranego obiektu"
    
    # Sprawdź istniejące pola
    existing_fields = {field.name(): field for field in source_layer.fields()}
    missing_fields = []
    
    for req_field in required_fields.keys():
        if req_field not in existing_fields:
            missing_fields.append(req_field)
    
    # Jeśli brakuje pól - pokaż dialog mapowania
    field_mapping = {}
    if missing_fields:
        print(f"⚠️ Brakujące pola: {', '.join(missing_fields)}")
        
        dialog = FieldMappingDialog(
            layer=source_layer,
            required_fields=list(required_fields.keys()),
            layer_type="terenu przedmiotowego"
        )
        
        result = dialog.exec()
        if result != QDialog.DialogCode.Accepted:
            return False, "Anulowano mapowanie pól"
        
        field_mapping = dialog.get_field_mapping()
        print(f"✓ Mapowanie pól: {field_mapping}")
    else:
        print("✓ Wszystkie wymagane pola istnieją")
        for req_field in required_fields.keys():
            field_mapping[req_field] = req_field
    
    # === Stwórz warstwę memory Z CRS PROJEKTU ===
    print("  📋 Tworzę warstwę roboczą...")
    
    # ⬅️ UŻYWAJ CRS PROJEKTU!
    memory_layer = QgsVectorLayer(
        f"Polygon?crs={project_crs.authid()}", 
        "temp_uldk", 
        "memory"
    )
    memory_provider = memory_layer.dataProvider()
    
    # Dodaj wymagane pola
    fields_to_add = []
    for req_field, field_type in required_fields.items():
        new_field = QgsField(req_field, field_type)
        if req_field == 'POLE_EWIDENCYJNE':
            new_field.setLength(10)
            new_field.setPrecision(2)
        fields_to_add.append(new_field)
    
    memory_provider.addAttributes(fields_to_add)
    memory_layer.updateFields()
    print("  ✓ Utworzono pola w warstwie roboczej")
    
    # === Przepisz dane z mapowaniem I REPROJEKCJĄ ===
    print("  📝 Przepisuję dane...")
    
    new_feature = QgsFeature(memory_layer.fields())
    
    # ⬅️ REPROJEKCJA GEOMETRII
    geometry = feature.geometry()
    if transform:
        geometry.transform(transform)
        print("  🔄 Reprojektowano geometrię")
    
    new_feature.setGeometry(geometry)
    
    # Przepisz dane według mapowania
    for req_field, source_field in field_mapping.items():
        field_idx = memory_layer.fields().indexFromName(req_field)
        
        if req_field == 'POLE_EWIDENCYJNE':
            # ⬅️ OBLICZ POWIERZCHNIĘ PO REPROJEKCJI!
            area = round(geometry.area(), 2)
            new_feature.setAttribute(field_idx, area)
        elif source_field and source_field in existing_fields:
            # Skopiuj wartość
            value = feature[source_field]
            new_feature.setAttribute(field_idx, value)
        # else: pozostaw NULL
    
    memory_provider.addFeature(new_feature)
    memory_layer.updateExtents()
    
    print("  ✓ Przepisano obiekt")
    
    # === Zapisz do gpkg ===
    output_path = str(Path(project_directory) / "Wyniki wyszukiwania ULDK.gpkg")
    
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.fileEncoding = 'UTF-8'
    options.layerName = "Wyniki wyszukiwania ULDK"
    options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        memory_layer, 
        output_path, 
        QgsCoordinateTransformContext(), 
        options
    )
    
    if result[0] == QgsVectorFileWriter.WriterError.NoError:
        print(f"  ✅ Zapisano do: {output_path}")
        
        # Wczytaj zapisaną warstwę do projektu
        saved_layer = QgsVectorLayer(
            f"{output_path}|layername=Wyniki wyszukiwania ULDK", 
            "Wyniki wyszukiwania ULDK", 
            "ogr"
        )
        if saved_layer.isValid():
            QgsProject.instance().addMapLayer(saved_layer)
            print("✅ Warstwa 'Wyniki wyszukiwania ULDK' utworzona pomyślnie")
            print(f"  📍 CRS warstwy wynikowej: {saved_layer.crs().authid()}")
            return True, "Warstwa terenu przedmiotowego utworzona"
        else:
            return False, "Nie udało się wczytać zapisanej warstwy"
    else:
        print(f"❌ Błąd podczas zapisywania: {result[1]}")
        return False, f"Nie udało się zapisać warstwy: {result[1]}"

def handle_granica_terenu_step():
    """
    Główna funkcja obsługująca krok 1 - Granica terenu
    WERSJA Z NIEMODALNYM DIALOGIEM
    
    Returns:
        tuple: (success: bool, message: str, use_gis_support: bool, show_dock: bool)
    """
    project_directory = get_project_directory()
    if not project_directory:
        return False, "Projekt musi być zapisany!", False, False
    
    # Sprawdź czy jest już warstwa ULDK
    existing_uldk = QgsProject.instance().mapLayersByName("Wyniki wyszukiwania ULDK")
    
    if existing_uldk:
        reply = QMessageBox.question(
            None,
            "Warstwa już istnieje",
            "Warstwa 'Wyniki wyszukiwania ULDK' już istnieje w projekcie.\n\n"
            "Czy chcesz:\n"
            "• TAK - użyć istniejącej warstwy\n"
            "• NIE - utworzyć nową (nadpisze istniejącą)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            return True, "Używam istniejącej warstwy ULDK", False, False
    
    # Pokaż dialog wyboru metody
    msg_box = QMessageBox()
    msg_box.setWindowTitle("Wybór metody pozyskania terenu")
    msg_box.setText(
        "Wybierz sposób pozyskania terenu przedmiotowego:\n\n"
        "🔌 GIS Support - użyj wtyczki do wyszukania działki w ULDK\n"
        "📍 Wskaż ręcznie - wybierz obiekt z istniejącej warstwy"
    )
    msg_box.setIcon(QMessageBox.Icon.Question)
    
    gis_support_btn = msg_box.addButton("🔌 GIS Support", QMessageBox.ButtonRole.YesRole)
    manual_btn = msg_box.addButton("📍 Wskaż ręcznie", QMessageBox.ButtonRole.NoRole)
    cancel_btn = msg_box.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)
    
    msg_box.exec()
    clicked_button = msg_box.clickedButton()
    
    if clicked_button == cancel_btn:
        return False, "Anulowano wybór metody", False, False
    
    if clicked_button == gis_support_btn:
        # Użytkownik chce użyć GIS Support
        QMessageBox.information(
            None,
            "GIS Support",
            "Użyj wtyczki GIS Support do wyszukania działki.\n\n"
            "Warstwa zostanie zapisana jako 'Wyniki wyszukiwania ULDK'.\n\n"
            "Po zakończeniu kliknij 'Gotowe' w workflow."
        )
        return True, "Oczekiwanie na wtyczkę GIS Support", True, False
    
    if clicked_button == manual_btn:  # jawne sprawdzenie
        return True, "Otwórz dock widget wyboru obiektu", False, True

   # Fallback (nie powinno się zdarzyć)
    return False, "Nieznana opcja", False, False


# ==================== RESZTA KLASY WORKFLOW (BEZ ZMIAN) ====================
# [Cała reszta kodu workflow jak w poprzedniej wersji - WZWorkflowDockWidget etc.]
# Dla oszczędności miejsca - kopiuję z poprzedniej wersji

class WZWorkflowDockWidget(QDockWidget):
    
    WORKFLOW_STEPS = {
        0: {
        'name': 'Wybór warstw bazowych',
        'required_layers': ['dzialki_EWGiB', 'budynki_EWGiB'],
        'custom_function': 'copy_and_save_base_layers_v2',
        'description': 'Wybór i przygotowanie warstw działek i budynków'
        },
        1: {
        'name': 'Granica terenu',
        'required_layers': ['Wyniki wyszukiwania ULDK'],  # ⬅️ ZMIENIONA NAZWA!
        'custom_function': 'handle_granica_terenu_step',   # ⬅️ NOWA FUNKCJA!
        'script': 'granica_terenu_zapis_wynikowULDK.py',   # ⬅️ Wykonywany PO utworzeniu warstwy
        'description': 'Wybór terenu: GIS Support lub ręczne wskazanie'
        },
        2: {
            'name': 'Bufor obszaru',
            'required_layers': ['granica_obszaru_analizowanego'],
            'script': 'front_dzialki_buffer.py',
            'description': 'Tworzenie bufora obszaru analizowanego'
        },
        3: {
            'name': 'Wymiary',
            'required_layers': ['wymiary'],
            'script': 'wymiary.py',
            'description': 'Rysowanie wymiarów'
        },
        4: {
            'name': 'Zapis wymiarów',
            'required_layers': [],
            'script': 'zapis_wymiarow.py',
            'description': 'Zapisywanie wymiarów'
        },
        5: {
            'name': 'Działki i budynki',
            'required_layers': ['dzialki_w_obszarze'],
            'script': 'wyznacz_dzialki_i_budynki.py',
            'description': 'Wyznaczanie działek i budynków'
        },
        6: {
            'name': 'Elewacje',
            'required_layers': ['budynki_z_szer_elew_front'],
            'script': 'qgis_elewacja_drawing_more_safe.py',
            'description': 'Pomiar elewacji frontowych'
        },
        7: {
            'name': 'Chmura punktów',
            'required_layers': ['Classification_2'],
            'script': 'pointcloud_processing_script.py',
            'description': 'Przetwarzanie chmury punktów',
            'pre_action': lambda: utworz_folder(f"{Path(get_project_directory())}/chmura")
        },
        8: {
            'name': 'Klasyfikacja PBC',
            'required_layers': ['punkty_pbc_wyniki_predykcji'],
            'script': 'fixed_qgis_hex_predictor.py',
            'description': 'Klasyfikacja PBC - CZASOCHŁONNE'
        },
        9: {
            'name': 'Weryfikacja PBC',
            'required_layers': ['punkty_pbc_wyniki_predykcji'],
            'manual': True,
            'description': 'Weryfikacja punktów PBC'
        },
        10: {
            'name': 'Wskaźniki działek',
            'required_layers': ['działki_ze_wskaznikami'],
            'script': 'oblicz_wskazniki_dzialek.py',
            'description': 'Obliczanie wskaźników - CZASOCHŁONNE'
        },
        11: {
            'name': 'Parametry budynków',
            'required_layers': ['budynki_parametry'],
            'scripts': ['oblicz_parametry_budynkow.py', 'przygotuj_dachy_do_klasyfikacji.py', 'roof_classification.py'],
            'description': 'Obliczanie parametrów budynków',
        },
        12: {
            'name': 'Linie zabudowy',
            'required_layers': ['linie_zabudowy'],
            'manual': True,
            'custom_ui': 'line_measurement',
            'description': 'Wyznaczanie linii zabudowy'
        },
        13: {
            'name': 'Dane działki',
            'required_layers': [],
            'manual': True,
            'custom_ui': 'data_sheet_dialog',
            'description': 'Wypełnienie danych działki inwestora'
        },
        14: {
            'name': 'Wyniki końcowe',
            'required_layers': [],
            'scripts': ['output_and_results_unified.py', 'generator_analiz_opisowych.py'],
            'description': 'Generowanie wyników końcowych'
        }
    }
    
    def __init__(self):
        super().__init__("Analiza WZ - Workflow")
        self.setObjectName("WZWorkflowDockWidget")
        self.current_step = 0
        self.liczba_budynkow = 0
        self.rozne_funkcje = False
        self.selection_dock = None  # ⬅️ DODAJ TO!
        
        self.setStyleSheet(MODERN_STYLE)
        
        self.init_ui()
        self.detect_current_step()
        self.show_main_menu()
        
    def init_ui(self):
        """Inicjalizacja interfejsu użytkownika"""
        main_widget = QWidget()
        scroll_area = QScrollArea()
        scroll_area.setWidget(main_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        status_group = QGroupBox("Status Workflow")
        status_layout = QVBoxLayout()
        
        self.current_step_label = QLabel("Krok: 0")
        self.current_step_label.setProperty("class", "subtitle")
        
        self.step_description_label = QLabel("")
        self.step_description_label.setWordWrap(True)
        
        self.status_indicator = StatusIndicator("Oczekiwanie na rozpoczęcie", "info")
        
        status_layout.addWidget(self.current_step_label)
        status_layout.addWidget(self.step_description_label)
        status_layout.addWidget(self.status_indicator)
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
        separator1 = QFrame()
        separator1.setProperty("class", "separator")
        separator1.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(separator1)
        
        navigation_group = QGroupBox("Nawigacja")
        navigation_layout = QVBoxLayout()
        
        nav_label = QLabel("Przejdź do kroku:")
        navigation_layout.addWidget(nav_label)
        
        self.step_selector = QComboBox()
        self.update_step_selector()
        self.step_selector.currentIndexChanged.connect(self.on_step_selected)
        navigation_layout.addWidget(self.step_selector)
        
        navigation_group.setLayout(navigation_layout)
        main_layout.addWidget(navigation_group)
        
        separator_nav = QFrame()
        separator_nav.setProperty("class", "separator")
        separator_nav.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(separator_nav)
        
        messages_group = QGroupBox("Komunikaty systemowe")
        messages_layout = QVBoxLayout()
        
        self.message_area = QTextEdit()
        self.message_area.setMaximumHeight(120)
        self.message_area.setMinimumHeight(80)
        self.message_area.setReadOnly(True)
        
        messages_layout.addWidget(self.message_area)
        messages_group.setLayout(messages_layout)
        main_layout.addWidget(messages_group)
        
        separator2 = QFrame()
        separator2.setProperty("class", "separator")
        separator2.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(separator2)
        
        actions_group = QGroupBox("Akcje")
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(10)
        
        self.button_container = QWidget()
        self.button_layout = QVBoxLayout()
        self.button_layout.setSpacing(8)
        self.button_container.setLayout(self.button_layout)
        
        actions_layout.addWidget(self.button_container)
        
        spacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        actions_layout.addItem(spacer)
        
        actions_group.setLayout(actions_layout)
        main_layout.addWidget(actions_group)
        
        control_group = QGroupBox("Kontrola Workflow")
        control_layout = QVBoxLayout()
        control_layout.setSpacing(8)
        
        control_buttons_layout = QHBoxLayout()
        
        back_btn = ModernButton("◄ Poprzedni", "secondary")
        back_btn.clicked.connect(self.go_previous_step)
        
        next_btn = ModernButton("Następny ►", "success")
        next_btn.clicked.connect(self.go_next_step)
        
        reset_btn = ModernButton("🔄 Reset", "danger")
        reset_btn.clicked.connect(self.reset_workflow)
        
        control_buttons_layout.addWidget(back_btn)
        control_buttons_layout.addWidget(next_btn)
        control_buttons_layout.addWidget(reset_btn)
        
        control_layout.addLayout(control_buttons_layout)
        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)
        
        main_widget.setLayout(main_layout)
        self.setWidget(scroll_area)
        
        self.setMinimumWidth(350)
    
    def update_step_selector(self):
        """Aktualizuj selector kroków"""
        self.step_selector.blockSignals(True)
        self.step_selector.clear()
        self.step_selector.addItem("0: Menu główne", 0)
        
        for step_num, step_info in self.WORKFLOW_STEPS.items():
            completed = self.is_step_completed(step_num)
            status_icon = "✅" if completed else "⏸️"
            
            display_text = f"{status_icon} {step_num}: {step_info['name']}"
            self.step_selector.addItem(display_text, step_num)
        self.step_selector.blockSignals(False)
    
    def on_step_selected(self, index):
        """Obsłuż wybór kroku z selectora"""
        if index < 0:
            return
        
        selected_step = self.step_selector.itemData(index)
        if selected_step is None:
            return
        
        if selected_step == 0:
            self.current_step = 0
            self.show_main_menu()
        else:
            if selected_step > self.current_step + 1:
                reply = QMessageBox.question(
                    None,
                    "Potwierdzenie",
                    f"Czy na pewno chcesz przeskoczyć do kroku {selected_step}?\n"
                    f"Aktualny krok: {self.current_step}\n\n"
                    "To może spowodować problemy jeśli poprzednie kroki nie zostały ukończone.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    self.step_selector.setCurrentIndex(self.current_step)
                    return
            
            self.current_step = selected_step
            self.update_step_display()
            self.save_checkpoint(f'manual_jump_to_{selected_step}')
            self.continue_workflow()
    
    def go_previous_step(self):
        """Cofnij się o jeden krok"""
        if self.current_step > 0:
            self.current_step -= 1
            self.add_message(f"Cofnięto do kroku {self.current_step}", "info")
            self.update_step_display()
            self.save_checkpoint(f'back_to_{self.current_step}')
            
            if self.current_step == 0:
                self.show_main_menu()
            else:
                self.continue_workflow()
        else:
            self.add_message("Jesteś już na początku workflow", "warning")
    
    def go_next_step(self):
        """Przejdź do następnego kroku"""
        max_step = max(self.WORKFLOW_STEPS.keys())
        
        if self.current_step < max_step:
            self.current_step += 1
            self.add_message(f"Przejście do kroku {self.current_step}", "info")
            self.update_step_display()
            self.save_checkpoint(f'forward_to_{self.current_step}')
            self.continue_workflow()
        else:
            self.add_message("To już ostatni krok workflow", "warning")
            self.show_completion()
    
    def is_step_completed(self, step_num):
        """Sprawdź czy krok został ukończony"""
        if step_num not in self.WORKFLOW_STEPS:
            return False
        
        step_info = self.WORKFLOW_STEPS[step_num]
        required_layers = step_info.get('required_layers', [])
        
        if not required_layers:
            return False
        
        for layer_name in required_layers:
            if not self.check_layer_exists(layer_name):
                return False
        
        return True
    
    def detect_current_step(self):
        """Wykryj aktualny krok"""
        detected_step = 0
        
        for step_num in sorted(self.WORKFLOW_STEPS.keys(), reverse=True):
            if self.is_step_completed(step_num):
                detected_step = step_num
                break
        
        self.current_step = detected_step
        self.update_step_display()
        
        if self.current_step > 0:
            step_name = self.WORKFLOW_STEPS[self.current_step]['name']
            self.add_message(f"✅ Wykryto ukończony krok {self.current_step}: {step_name}", "success")
    
    def add_message(self, message, message_type="info"):
        """Dodaj wiadomość"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        icons = {
            "info": "ℹ️",
            "success": "✅", 
            "warning": "⚠️",
            "error": "❌"
        }
        
        icon = icons.get(message_type, "ℹ️")
        formatted_message = f"[{timestamp}] {icon} {message}"
        
        self.message_area.append(formatted_message)
        
        scrollbar = self.message_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_buttons(self):
        """Wyczyść przyciski"""
        for i in reversed(range(self.button_layout.count())): 
            child = self.button_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
    
    def update_step_display(self):
        """Aktualizuj wyświetlanie"""
        self.current_step_label.setText(f"Krok: {self.current_step}")
        
        if self.current_step > 0 and self.current_step in self.WORKFLOW_STEPS:
            step_info = self.WORKFLOW_STEPS[self.current_step]
            self.step_description_label.setText(step_info['description'])
        else:
            self.step_description_label.setText("")
        
        self.step_selector.blockSignals(True)
        self.step_selector.setCurrentIndex(self.current_step)
        self.step_selector.blockSignals(False)
        
        self.update_step_selector()
    
    def show_main_menu(self):
        """Pokaż menu główne"""
        self.clear_buttons()
        
        self.status_indicator.setText("Wybór typu analizy")
        self.status_indicator.set_status("info")
        
        analiza_btn = ModernButton("📊 Analiza do WZ", "primary")
        analiza_btn.clicked.connect(self.wybierz_analize)
        self.button_layout.addWidget(analiza_btn)
        
        mapa_btn = ModernButton("🗺️ Mapa do WZ", "secondary")
        mapa_btn.clicked.connect(self.wybierz_mape)
        self.button_layout.addWidget(mapa_btn)
    
    def wybierz_analize(self):
        """Menu analizy"""
        self.clear_buttons()
        
        if self.current_step > 0:
            continue_btn = ModernButton(f"🔄 Kontynuuj od kroku {self.current_step + 1}", "success")
            continue_btn.clicked.connect(self.potwierdz_kontynuacje)
            self.button_layout.addWidget(continue_btn)
        
        standard_btn = ModernButton("🏠 Nowa standardowa analiza", "primary")
        standard_btn.clicked.connect(self.nowa_standardowa_analiza)
        self.button_layout.addWidget(standard_btn)
        
        funkcje_btn = ModernButton("🔧 Użyj dostępnych funkcji", "secondary")
        funkcje_btn.clicked.connect(self.pokaz_funkcje)
        self.button_layout.addWidget(funkcje_btn)
    
    def wybierz_mape(self):
        self.execute_script("wierzcholki_z_zapisem.py")
        self.execute_script("olz_i_wymiarowanie_2_0.py")
    
    def potwierdz_kontynuacje(self):
        """Potwierdź kontynuację"""
        self.clear_buttons()
        
        tak_btn = ModernButton("✅ Tak, kontynuuj", "success") 
        tak_btn.clicked.connect(self.resume_from_detected_step)
        self.button_layout.addWidget(tak_btn)
        
        nie_btn = ModernButton("❌ Nie, wróć do menu", "secondary")
        nie_btn.clicked.connect(self.show_main_menu)
        self.button_layout.addWidget(nie_btn)
    
    def nowa_standardowa_analiza(self):
        """Nowa analiza"""
        self.current_step = 0
        self.save_checkpoint('nowa_standardowa_analiza')
        
        if not self.sprawdz_warstwy_i_projekt():
            return
        
        self.add_message("Rozpoczynam nową analizę standardową", "success")
        self.update_step_display()
        self.continue_workflow()
    
    def resume_from_detected_step(self):
        """Wznów workflow"""
        self.current_step += 1
        self.update_step_display()
        self.continue_workflow()
    
    def pokaz_funkcje(self):
        """Pokaż funkcje"""
        self.clear_buttons()
        
        self.funkcje_map = {
            "Zapisz warstwę tymczasową": self.save_memory_layer,
            "Dodaj pola: WIZ, WNIZ, WPZ, WPBC": self.add_fields_script,
            "Generuj analizę opisową": self.generator_analiz_opisowych,
            "Scal działki i aktualizuj warstwę": self.scalanie_dzialek,
            "Usuń warstwy tymczasowe": self.remove_memories,
        }
        
        funkcje_list = QListWidget()
        
        for opis in self.funkcje_map.keys():
            funkcje_list.addItem(opis)
        
        funkcje_list.itemClicked.connect(self.on_funkcja_clicked)
        
        self.button_layout.addWidget(funkcje_list)

    def on_funkcja_clicked(self, item):
        """Obsłuż funkcję"""
        opis_funkcji = item.text()
        if opis_funkcji in self.funkcje_map:
            funkcja = self.funkcje_map[opis_funkcji]
            if callable(funkcja):
                funkcja()
    
    def sprawdz_warstwy_i_projekt(self):
        """Sprawdź projekt"""
        project = QgsProject.instance()
        
        if not project.fileName():
            QMessageBox.warning(None, "Błąd", "Projekt musi być najpierw zapisany!")
            return False
        
        return True
    
    def continue_workflow(self):
        """Kontynuuj workflow"""
        self.clear_buttons()
        
        if self.current_step not in self.WORKFLOW_STEPS:
            self.show_completion()
            return
        
            # ⬅️ DODAJ TEN BLOK NA POCZĄTKU!
        # === SPECJALNA OBSŁUGA DLA KROKU 1 (Granica terenu) ===
        if self.current_step == 1:
            self.handle_step_1_granica_terenu()
            return
        # === KONIEC SPECJALNEJ OBSŁUGI ===
        
        if self.current_step == 0:
            if self.is_step_completed(0):
                self.show_skip_or_redo_options(self.WORKFLOW_STEPS[0])
                return
            else:
                self.show_layer_selection_step()
                return
        
        step_info = self.WORKFLOW_STEPS[self.current_step]
        
        if self.is_step_completed(self.current_step):
            self.show_skip_or_redo_options(step_info)
            return
        
        if 'pre_action' in step_info:
            step_info['pre_action']()
        
        if step_info.get('custom_ui'):
            self.handle_custom_ui_step(step_info)
        elif step_info.get('manual'):
            self.handle_manual_step(step_info)
        elif 'scripts' in step_info:
            self.show_execute_multiple_scripts_button(step_info['scripts'])
        elif 'script' in step_info:
            self.show_execute_script_button(step_info['script'])
    
    def show_skip_or_redo_options(self, step_info):
        """Opcje pomijania"""
        skip_btn = ModernButton("⏭️ Pomiń (krok ukończony)", "success")
        skip_btn.clicked.connect(lambda: self.skip_to_next_step())
        self.button_layout.addWidget(skip_btn)
        
        redo_btn = ModernButton("🔄 Wykonaj ponownie", "secondary")
        redo_btn.clicked.connect(lambda: self.redo_current_step(step_info))
        self.button_layout.addWidget(redo_btn)
    
    def skip_to_next_step(self):
        """Pomiń krok"""
        self.current_step += 1
        self.update_step_display()
        self.continue_workflow()
    
    def redo_current_step(self, step_info):
        """Wykonaj ponownie"""
        self.clear_buttons()
        
        if step_info.get('manual'):
            self.handle_manual_step(step_info)
        elif step_info.get('custom_ui'):
            self.handle_custom_ui_step(step_info)
        elif 'scripts' in step_info:
            self.show_execute_multiple_scripts_button(step_info['scripts'])
        elif 'script' in step_info:
            self.show_execute_script_button(step_info['script'])
    
    def handle_manual_step(self, step_info):
        """Krok manualny"""
        if 'script' in step_info:
            dalej_btn = ModernButton("✅ Gotowe, wykonaj skrypt", "primary")
            dalej_btn.clicked.connect(lambda: self.execute_and_continue(step_info['script']))
            self.button_layout.addWidget(dalej_btn)
        else:
            dalej_btn = ModernButton("✅ Gotowe", "primary")
            dalej_btn.clicked.connect(self.step_completed)
            self.button_layout.addWidget(dalej_btn)
    
    def handle_custom_ui_step(self, step_info):
        """Krok custom UI"""
        custom_ui = step_info['custom_ui']
        
        if custom_ui == 'line_measurement':
            self.show_line_measurement_controls()
        elif custom_ui == 'data_sheet_dialog':
            self.show_data_sheet_dialog()
    
    def show_execute_script_button(self, script_name):
        """Przycisk skryptu"""
        execute_btn = ModernButton(f"▶️ Wykonaj: {script_name}", "primary")
        execute_btn.clicked.connect(lambda: self.execute_and_continue(script_name))
        self.button_layout.addWidget(execute_btn)
    
    def show_execute_multiple_scripts_button(self, scripts):
        """Przyciski wielu skryptów"""
        execute_btn = ModernButton(f"▶️ Wykonaj {len(scripts)} skryptów", "primary")
        execute_btn.clicked.connect(lambda: self.execute_multiple_scripts(scripts))
        self.button_layout.addWidget(execute_btn)
    
    def execute_and_continue(self, script_name):
        """Wykonaj i kontynuuj"""
        if self.execute_script(script_name):
            self.step_completed()
    
    def execute_multiple_scripts(self, scripts):
        """Wykonaj wiele skryptów"""
        for script in scripts:
            if not self.execute_script(script):
                return
        
        if self.current_step not in self.WORKFLOW_STEPS:
            self.show_completion()
            return
               
        self.step_completed()
    
    def step_completed(self):
        """Krok ukończony"""
        self.add_message(f"✅ Krok {self.current_step} ukończony", "success")
        self.current_step += 1
        self.update_step_display()
        self.save_checkpoint(f'completed_step_{self.current_step}')
        self.continue_workflow()
    
    def show_line_measurement_controls(self):
        """Kontrolki linii"""
        start_btn = ModernButton("🚀 Rozpocznij pomiar linii", "success")
        start_btn.clicked.connect(self.uruchom_pomiar_linii)
        self.button_layout.addWidget(start_btn)
        
        finish_btn = ModernButton("✅ Zakończ pomiar linii", "primary") 
        finish_btn.clicked.connect(self.zakoncz_pomiar_linii_step)
        self.button_layout.addWidget(finish_btn)
    
    def uruchom_pomiar_linii(self):
        """Uruchom pomiar"""
        global line_controller
        
        line_controller = LineMeasurementController()
        success = line_controller.start_measurement_process()
        
        if success:
            self.add_message("Uruchomiono tryb pomiaru linii", "success")
    
    def zakoncz_pomiar_linii_step(self):
        """Zakończ pomiar"""
        global line_controller
        
        if line_controller:
            line_controller.finish_measurement()
            line_controller = None
            
        layers = QgsProject.instance().mapLayersByName("linie_zabudowy")
        project_directory = get_project_directory()
        
        if layers:
            layer = layers[0]
            zapisz_warstwe_do_gpkg(layer=layer, output_directory=project_directory)
            remove_memory_layers()
            self.step_completed()
    
    def show_data_sheet_dialog(self):
        """Pokaż NIEMODALNY dialog danych - mapa pozostaje aktywna"""
        try:
            # parent=None + ref na self → dialog niezależny od dock widgetu, nie kasowany przez GC
            self.dane_dialog = DaneDzialkiDialog(parent=None)
            
            # Tryb niemodalny - QGIS, mapa i inne narzędzia pozostają aktywne
            self.dane_dialog.setModal(False)
            self.dane_dialog.setWindowModality(Qt.WindowModality.NonModal)
            self.dane_dialog.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.WindowMinimizeButtonHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )
            
            # Sygnały zamiast exec_() - asynchroniczna obsługa wyniku
            self.dane_dialog.accepted.connect(self._on_dane_dialog_accepted)
            self.dane_dialog.rejected.connect(self._on_dane_dialog_rejected)
            
            self.dane_dialog.show()
            self.dane_dialog.raise_()
            self.dane_dialog.activateWindow()
            
            self.add_message(
                "📋 Formularz otwarty - mapa i narzędzia QGIS pozostają aktywne. "
                "Możesz przesunąć okno, mierzyć, sprawdzać warstwy.",
                "info"
            )
            
        except Exception as e:
            error_msg = f"Błąd podczas otwierania dialogu: {str(e)}"
            self.add_message(f"❌ {error_msg}", "error")
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            self.clear_buttons()
            retry_btn = ModernButton("🔄 Spróbuj ponownie", "secondary")
            retry_btn.clicked.connect(self.show_data_sheet_dialog)
            self.button_layout.addWidget(retry_btn)
            
            skip_btn = ModernButton("⏭️ Pomiń ten krok", "danger")
            skip_btn.clicked.connect(self.step_completed)
            self.button_layout.addWidget(skip_btn)
    
    def _on_dane_dialog_accepted(self):
        """Wywoływane gdy użytkownik kliknął 'Zapisz i kontynuuj'"""
        self.add_message("✅ Dane działki zapisane", "success")
        self.dane_dialog = None
        self.step_completed()
    
    def _on_dane_dialog_rejected(self):
        """Wywoływane gdy użytkownik anulował lub zamknął okno X"""
        self.add_message("⚠️ Anulowano wprowadzanie danych", "warning")
        self.dane_dialog = None
    
    
    
    def show_completion(self):
        """Zakończenie"""
        self.clear_buttons()
        self.add_message("🎉 WORKFLOW ZAKOŃCZONY POMYŚLNIE! 🎉", "success")
        
        completion_label = QLabel("✅ Analiza zakończona!")
        completion_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.button_layout.addWidget(completion_label)
    
    def save_checkpoint(self, step_name):
        """Zapisz checkpoint"""
        checkpoint_data = {
            'step': self.current_step,
            'step_name': step_name,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(checkpoint_data, f, indent=2)
    
    
    def reset_workflow(self):
        """Reset"""
        reply = QMessageBox.question(
            None,
            "Potwierdzenie resetu",
            "Czy na pewno chcesz zresetować workflow?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if os.path.exists(CHECKPOINT_FILE):
                os.remove(CHECKPOINT_FILE)
            
            self.current_step = 0
            self.update_step_display()
            self.show_main_menu()
    
    def execute_script(self, script_name):
        """Wykonaj skrypt"""
        script_path = os.path.join(SCRIPTS_PATH, script_name)
        
        if not os.path.exists(script_path):
            self.add_message(f"Nie znaleziono skryptu: {script_name}", "error")
            return False
        
        try:
            # Uruchomienie skryptu kroku standardowym mechanizmem biblioteki
            # standardowej (runpy) zamiast exec(). runpy.run_path wykonuje plik
            # w SWIEZEJ przestrzeni nazw, zainicjowanej globalsami wtyczki —
            # skrypt widzi to samo co dotad, ale nie zasmieca globalsow wtyczki
            # i nie uzywa niebezpiecznej wbudowanej funkcji exec.
            runpy.run_path(script_path, init_globals=globals())

            self.add_message(f"✅ {script_name} wykonany", "success")
            return True
            
        except Exception as e:
            self.add_message(f"❌ Błąd w {script_name}: {str(e)}", "error")
            return False
    
    def check_layer_exists(self, layer_name):
        """Sprawdź warstwę"""
        layers = QgsProject.instance().mapLayersByName(layer_name)
        return len(layers) > 0
    
    def save_memory_layer(self):
        self.execute_script("zapisanie_warstwy_tymczasowej.py")
    
    def add_fields_script(self):
        self.execute_script("add_fields_script.py")
    
    def generator_analiz_opisowych(self):
        self.execute_script("generator_analiz_opisowych.py")

    def scalanie_dzialek(self):
        self.execute_script("scalanie_dzialek_z_aktualizacja_warstwy.py")
        
    def remove_memories(self):
        remove_memory_layers()

    def show_layer_selection_step(self):
        """Krok wyboru warstw"""
        select_btn = ModernButton("📋 Wybierz warstwy działek i budynków", "primary")
        select_btn.clicked.connect(self.execute_layer_selection)
        self.button_layout.addWidget(select_btn)
        
        if self.check_layer_exists('dzialki_EWGiB') or self.check_layer_exists('budynki_EWGiB'):
            skip_btn = ModernButton("⏭️ Pomiń (używam istniejących warstw)", "secondary")
            skip_btn.clicked.connect(lambda: self.skip_to_step(1))
            self.button_layout.addWidget(skip_btn)

    def execute_layer_selection(self):
        """Wykonaj wybór warstw"""
        success, message = copy_and_save_base_layers_v2()
        
        if success:
            self.step_completed()
    
    def skip_to_step(self, step_number):
        """Przeskocz do kroku"""
        self.current_step = step_number
        self.update_step_display()
        self.continue_workflow()

    def handle_step_1_granica_terenu(self):
        """Specjalna obsługa kroku 1 - Granica terenu"""
        
        # Sprawdź czy warstwa ULDK już istnieje
        uldk_exists = self.check_layer_exists('Wyniki wyszukiwania ULDK')
        
        if uldk_exists:
            # Warstwa istnieje - pokaż opcje skip/redo
            self.show_skip_or_redo_options(self.WORKFLOW_STEPS[1])
            return
        
        # Warstwa nie istnieje - pokaż przycisk wyboru metody
        self.clear_buttons()
        
        wybor_btn = ModernButton(
            "🗺️ Wybierz sposób pozyskania terenu", 
            "primary"
        )
        wybor_btn.clicked.connect(self.execute_granica_terenu_selection)
        self.button_layout.addWidget(wybor_btn)
    
    def execute_granica_terenu_selection(self):
        """Wykonaj wybór metody dla granicy terenu"""
        success, message, use_gis_support, show_dock = handle_granica_terenu_step()
        
        if not success:
            self.add_message(f"⚠️ {message}", "warning")
            return
        
        self.add_message(f"✅ {message}", "success")
        
        if use_gis_support:
            # Użytkownik wybrał GIS Support - pokaż przycisk "Gotowe"
            self.clear_buttons()
            
            info_label = QLabel(
                "⏸️ Oczekiwanie na wtyczkę GIS Support...\n\n"
                "Po wyszukaniu działki kliknij 'Gotowe' poniżej."
            )
            info_label.setWordWrap(True)
            info_label.setStyleSheet(
                "padding: 10px; background-color: #fff3cd; "
                "border-radius: 5px; font-weight: bold;"
            )
            self.button_layout.addWidget(info_label)
            
            gotowe_btn = ModernButton("✅ Gotowe - warstwa utworzona", "success")
            gotowe_btn.clicked.connect(self.finish_granica_terenu_step)
            self.button_layout.addWidget(gotowe_btn)
            
        elif show_dock:
            # Pokaż niemodalny dock widget
            self.show_selection_dock()
        else:
            # Warstwa już utworzona - wykonaj skrypt
            self.finish_granica_terenu_step()
    
    def show_selection_dock(self):
        """Pokaż niemodalny dock widget do wyboru obiektu"""
        # Zamknij poprzedni jeśli istnieje
        if self.selection_dock:
            self.selection_dock.close()
        
        # Utwórz nowy dock widget z callbackiem
        self.selection_dock = SelectFeatureDockWidget(
            callback_function=self.on_feature_selected_callback
        )
        
        # Dodaj do QGIS jako dock widget
        iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.selection_dock)
        self.selection_dock.show()
        
        self.add_message("📍 Wybierz obiekt na mapie", "info")
        
        # Zaktualizuj workflow UI
        self.clear_buttons()
        info_label = QLabel(
            "⏸️ Czekam na wybór obiektu...\n\n"
            "Użyj okna 'Wybór terenu przedmiotowego' →"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "padding: 10px; background-color: #e3f2fd; "
            "border-radius: 5px; font-weight: bold;"
        )
        self.button_layout.addWidget(info_label)
    
    
    def on_feature_selected_callback(self, source_layer, feature_id):
        """Callback wywoływany po wyborze obiektu w dock widget"""
        # Zamknij dock widget
        if self.selection_dock:
            try:
                self.selection_dock.close()
            except RuntimeError:
                # Dock już zamknięty
                pass
            self.selection_dock = None
        
        if source_layer is None or feature_id is None:
            self.add_message("⚠️ Anulowano wybór obiektu", "warning")
            self.clear_buttons()
            
            # Pokaż przycisk ponownego wyboru
            retry_btn = ModernButton("🔄 Wybierz ponownie", "secondary")
            retry_btn.clicked.connect(self.execute_granica_terenu_selection)
            self.button_layout.addWidget(retry_btn)
            return
        
        # Waliduj i utwórz warstwę ULDK
        project_directory = get_project_directory()
        
        try:
            success, message = validate_and_create_uldk_layer(
                source_layer, 
                feature_id, 
                project_directory
            )
            
            if success:
                self.add_message(f"✅ {message}", "success")
                QMessageBox.information(
                    None,
                    "Sukces",
                    f"✅ Warstwa 'Wyniki wyszukiwania ULDK' utworzona!\n\n"
                    f"Źródło: {source_layer.name()}\n"
                    f"Zapisano w: {project_directory}"
                )
                # Wykonaj skrypt przetwarzania
                self.finish_granica_terenu_step()
            else:
                self.add_message(f"❌ {message}", "error")
                QMessageBox.critical(None, "Błąd", f"Nie udało się utworzyć warstwy:\n{message}")
                
                # Pokaż przycisk ponownego wyboru
                self.clear_buttons()
                retry_btn = ModernButton("🔄 Spróbuj ponownie", "secondary")
                retry_btn.clicked.connect(self.execute_granica_terenu_selection)
                self.button_layout.addWidget(retry_btn)
                
        except Exception as e:
            error_msg = f"Błąd podczas tworzenia warstwy ULDK: {str(e)}"
            self.add_message(f"❌ {error_msg}", "error")
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            QMessageBox.critical(None, "Błąd krytyczny", error_msg)
            
        
    def finish_granica_terenu_step(self):
        """Zakończ krok 1 - wykonaj skrypt przetwarzania"""
        
        # Sprawdź czy warstwa faktycznie istnieje
        if not self.check_layer_exists('Wyniki wyszukiwania ULDK'):
            QMessageBox.warning(
                None,
                "Błąd",
                "Warstwa 'Wyniki wyszukiwania ULDK' nie istnieje!\n\n"
                "Upewnij się, że warstwa została utworzona."
            )
            return
        
        # Wykonaj skrypt granica_terenu_zapis_wynikowULDK.py
        step_info = self.WORKFLOW_STEPS[1]
        if self.execute_script(step_info['script']):
            self.step_completed()


def create_wz_workflow_dock():
    """Utwórz dock widget"""
    try:
        if not IFACE_AVAILABLE:
            raise Exception("iface nie jest dostępne")
        
        dock_widget = WZWorkflowDockWidget()
        iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_widget)
        dock_widget.show()
        
        print("✅ WZ Workflow dock widget utworzony")
        return dock_widget
        
    except Exception as e:
        print(f"❌ Błąd tworzenia dock widget: {e}")
        raise