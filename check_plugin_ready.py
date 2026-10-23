#!/usr/bin/env python3
"""
Skrypt sprawdzający gotowość wtyczki QGIS do publikacji
Uruchom z katalogu głównego wtyczki
"""
import os
import sys
import re
from pathlib import Path
import zipfile


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_status(ok, message):
    """Wyświetla status z kolorową ikonką"""
    icon = f"{Colors.GREEN}✓{Colors.END}" if ok else f"{Colors.RED}✗{Colors.END}"
    print(f"{icon} {message}")
    return ok


def check_file_exists(filename, description):
    """Sprawdza czy plik istnieje"""
    exists = os.path.isfile(filename)
    return print_status(exists, f"{description}: {filename}")


def check_metadata():
    """Sprawdza poprawność metadata.txt"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}=== Sprawdzanie metadata.txt ==={Colors.END}")
    
    if not os.path.isfile('metadata.txt'):
        print_status(False, "Brak pliku metadata.txt")
        return False
    
    required_fields = {
        'name': 'Nazwa wtyczki',
        'qgisMinimumVersion': 'Minimalna wersja QGIS',
        'description': 'Opis',
        'version': 'Wersja',
        'author': 'Autor',
        'email': 'Email',
        'about': 'Szczegółowy opis',
        'tracker': 'URL tracker (GitHub issues)',
        'repository': 'URL repozytorium',
        'tags': 'Tagi',
        'category': 'Kategoria',
        'icon': 'Ikona'
    }
    
    found_fields = {}
    with open('metadata.txt', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key = line.split('=')[0].strip()
                value = line.split('=', 1)[1].strip()
                found_fields[key] = value
    
    all_ok = True
    for field, description in required_fields.items():
        if field in found_fields and found_fields[field]:
            print_status(True, f"{description}: {found_fields[field][:50]}...")
        else:
            print_status(False, f"Brak: {description} ({field})")
            all_ok = False
    
    # Sprawdź format wersji
    if 'version' in found_fields:
        version = found_fields['version']
        if re.match(r'^\d+\.\d+\.\d+$', version):
            print_status(True, f"Format wersji poprawny: {version}")
        else:
            print_status(False, f"Niepoprawny format wersji: {version} (powinno być X.Y.Z)")
            all_ok = False
    
    # Sprawdź URLe
    for url_field in ['tracker', 'repository']:
        if url_field in found_fields:
            url = found_fields[url_field]
            if url.startswith('http'):
                print_status(True, f"URL {url_field} poprawny")
            else:
                print_status(False, f"URL {url_field} niepoprawny: {url}")
                all_ok = False
    
    return all_ok


def check_structure():
    """Sprawdza strukturę katalogów wtyczki"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}=== Sprawdzanie struktury ==={Colors.END}")
    
    all_ok = True
    all_ok &= check_file_exists('__init__.py', 'Inicjalizacja wtyczki')
    all_ok &= check_file_exists('metadata.txt', 'Metadane')
    all_ok &= check_file_exists('icon.png', 'Ikona')
    
    # Sprawdź czy __init__.py ma classFactory
    if os.path.isfile('__init__.py'):
        with open('__init__.py', 'r') as f:
            content = f.read()
            if 'classFactory' in content:
                print_status(True, "Funkcja classFactory() znaleziona")
            else:
                print_status(False, "Brak funkcji classFactory() w __init__.py")
                all_ok = False
    
    return all_ok


def check_large_files():
    """Sprawdza duże pliki które nie powinny być w ZIP"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}=== Sprawdzanie dużych plików ==={Colors.END}")
    
    large_extensions = ['.pth', '.pkl', '.h5', '.model', '.weights']
    large_files = []
    
    for root, dirs, files in os.walk('.'):
        # Pomiń __pycache__ i .git
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', '.vscode', '.idea']]
        
        for file in files:
            if any(file.endswith(ext) for ext in large_extensions):
                filepath = os.path.join(root, file)
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                large_files.append((filepath, size_mb))
    
    if large_files:
        print(f"{Colors.YELLOW}⚠ Znaleziono duże pliki modeli:{Colors.END}")
        for filepath, size_mb in large_files:
            print(f"  • {filepath}: {size_mb:.1f} MB")
        print(f"\n{Colors.YELLOW}Te pliki NIE MOGĄ być w ZIP dla QGIS repo!{Colors.END}")
        print("Umieść je w GitHub Releases i użyj model_downloader.py")
        return False
    else:
        print_status(True, "Brak dużych plików modeli (dobrze!)")
        return True


def check_gitignore():
    """Sprawdza czy .gitignore wyklucza duże pliki"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}=== Sprawdzanie .gitignore ==={Colors.END}")
    
    if not os.path.isfile('.gitignore'):
        print_status(False, "Brak pliku .gitignore")
        return False
    
    with open('.gitignore', 'r') as f:
        content = f.read()
    
    required_ignores = ['*.pth', '*.pkl', '__pycache__']
    all_ok = True
    
    for pattern in required_ignores:
        if pattern in content:
            print_status(True, f"Wyklucza: {pattern}")
        else:
            print_status(False, f"Nie wyklucza: {pattern}")
            all_ok = False
    
    return all_ok


def check_model_downloader():
    """Sprawdza czy jest model_downloader.py"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}=== Sprawdzanie model_downloader.py ==={Colors.END}")
    
    if not os.path.isfile('model_downloader.py'):
        print_status(False, "Brak pliku model_downloader.py")
        print(f"{Colors.YELLOW}  Wtyczka wymaga automatycznego pobierania modeli!{Colors.END}")
        return False
    
    with open('model_downloader.py', 'r') as f:
        content = f.read()
    
    # Sprawdź czy ma URLe
    if 'GITHUB_RELEASE_URL' in content:
        print_status(True, "Znaleziono konfigurację URLi")
        
        # Sprawdź czy URL jest zaktualizowany
        if 'TwojeRepo' in content or 'username' in content.lower():
            print_status(False, "URL GitHub nie zaktualizowany! (zawiera 'TwojeRepo')")
            return False
        else:
            print_status(True, "URL GitHub wygląda na zaktualizowany")
    else:
        print_status(False, "Brak konfiguracji GITHUB_RELEASE_URL")
        return False
    
    return True


def estimate_zip_size():
    """Szacuje rozmiar ZIP (bez dużych plików)"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}=== Szacowanie rozmiaru ZIP ==={Colors.END}")
    
    total_size = 0
    exclude_patterns = ['.pth', '.pkl', '.pyc', '.git', '__pycache__']
    
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', '.vscode', '.idea', 'ml_dataset']]
        
        for file in files:
            if not any(pattern in file for pattern in exclude_patterns):
                filepath = os.path.join(root, file)
                total_size += os.path.getsize(filepath)
    
    size_mb = total_size / (1024 * 1024)
    print(f"Szacowany rozmiar ZIP: {size_mb:.2f} MB")
    
    if size_mb > 10:
        print_status(False, f"ZIP może być za duży (> 10 MB)")
        return False
    else:
        print_status(True, f"Rozmiar ZIP OK (< 10 MB)")
        return True


def print_summary(checks):
    """Wyświetla podsumowanie"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*50}{Colors.END}")
    print(f"{Colors.BOLD}PODSUMOWANIE{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*50}{Colors.END}\n")
    
    passed = sum(checks.values())
    total = len(checks)
    
    for check_name, result in checks.items():
        print_status(result, check_name)
    
    print(f"\n{Colors.BOLD}Wynik: {passed}/{total} testów zaliczonych{Colors.END}")
    
    if passed == total:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Wtyczka gotowa do publikacji!{Colors.END}")
        print("\nNastępne kroki:")
        print("1. Uruchom ./create_plugin_zip.sh aby stworzyć ZIP")
        print("2. Stwórz GitHub Release z modelami ML")
        print("3. Zaktualizuj URLe w model_downloader.py")
        print("4. Upload ZIP na plugins.qgis.org")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ Wtyczka wymaga poprawek{Colors.END}")
        print(f"\nNapraw błędy i uruchom skrypt ponownie.")
    
    return passed == total


def main():
    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("="*50)
    print("  Sprawdzanie gotowości wtyczki QGIS")
    print("="*50)
    print(f"{Colors.END}\n")
    
    if not os.path.isfile('metadata.txt'):
        print(f"{Colors.RED}Błąd: Uruchom skrypt z katalogu głównego wtyczki{Colors.END}")
        sys.exit(1)
    
    # Wszystkie testy
    checks = {
        'Metadata poprawne': check_metadata(),
        'Struktura poprawna': check_structure(),
        'Duże pliki wykluczone': check_large_files(),
        '.gitignore poprawny': check_gitignore(),
        'Model downloader skonfigurowany': check_model_downloader(),
        'Rozmiar ZIP OK': estimate_zip_size()
    }
    
    # Podsumowanie
    success = print_summary(checks)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
