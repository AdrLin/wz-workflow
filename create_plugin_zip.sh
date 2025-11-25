#!/bin/bash
# ============================================
# Skrypt do pakowania wtyczki WZ Workflow
# dla QGIS Plugin Repository
# ============================================

# Kolory dla outputu
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Pakowanie wtyczki WZ Workflow ===${NC}\n"

# Sprawdź czy jesteśmy w katalogu wtyczki
if [ ! -f "metadata.txt" ]; then
    echo -e "${RED}Błąd: Nie znaleziono metadata.txt${NC}"
    echo "Uruchom skrypt z katalogu głównego wtyczki"
    exit 1
fi

# Pobierz wersję z metadata.txt
VERSION=$(grep "^version=" metadata.txt | cut -d'=' -f2)
if [ -z "$VERSION" ]; then
    echo -e "${RED}Błąd: Nie można odczytać wersji z metadata.txt${NC}"
    exit 1
fi

echo -e "Wersja: ${GREEN}$VERSION${NC}"

# Nazwa wtyczki (katalog)
PLUGIN_NAME="wz_workflow" 
OUTPUT_ZIP="${PLUGIN_NAME}-${VERSION}.zip"

# Przejdź do katalogu nadrzędnego
cd ..
echo -e "\n${YELLOW}Pakowanie...${NC}"

# Pakuj z wykluczeniem dużych plików i śmieci
zip -r "$OUTPUT_ZIP" "$PLUGIN_NAME/" \
    -x "*ultimate_building_classifier_svm*.pkl" \
    -x "symbology-style.db" \
    -x "*/__pycache__/*" \
    -x "*.pyc" \
    -x "*.pyo" \
    -x ".git/*" \
    -x ".gitignore" \
    -x ".vscode/*" \
    -x ".idea/*" \
    -x "ml_dataset/*" \
    -x "workflow_checkpoint.json" \
    -x "*.qgs~" \
    -x "*.qgz~" \
    -x "*.log" \
    -x "*.tmp" \
    -x ".DS_Store" \
    -x "*/\.*" \
    -x "create_plugin_zip.sh"

# Sprawdź sukces
if [ $? -eq 0 ]; then
    FILE_SIZE=$(du -h "$OUTPUT_ZIP" | cut -f1)
    echo -e "\n${GREEN}✓ Sukces!${NC}"
    echo -e "Plik: ${GREEN}$OUTPUT_ZIP${NC}"
    echo -e "Rozmiar: ${GREEN}$FILE_SIZE${NC}"
    
    # Ostrzeżenie jeśli > 10MB
    SIZE_BYTES=$(stat -f%z "$OUTPUT_ZIP" 2>/dev/null || stat -c%s "$OUTPUT_ZIP" 2>/dev/null)
    if [ "$SIZE_BYTES" -gt 10485760 ]; then
        echo -e "\n${YELLOW}⚠ UWAGA: Plik jest większy niż 10MB!${NC}"
        echo "QGIS Plugin Repository może odrzucić taki plik."
        echo "Sprawdź czy wszystkie duże pliki są wykluczone."
    fi
    
    # Lista zawartości
    echo -e "\n${YELLOW}Zawartość ZIP:${NC}"
    unzip -l "$OUTPUT_ZIP" | head -n 20
    echo "..."
    
    # Informacja o modelach
    echo -e "\n${YELLOW}Pamiętaj:${NC}"
    echo "1. Ten ZIP jest dla QGIS Plugin Repository (bez modeli ML)"
    echo "2. Modele ML umieść w GitHub Release jako osobne pliki"
    echo "3. Sprawdź URLe w model_downloader.py"
    
else
    echo -e "${RED}✗ Błąd podczas pakowania${NC}"
    exit 1
fi
