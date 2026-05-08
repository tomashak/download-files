#!/usr/bin/env python3
"""
Skript pro stahování souborů (např. PDF) z odkazů nalezených na webové stránce.

Použití:
    python download_files.py <URL> [--type <přípona>] [--output <složka>]

Příklady:
    python download_files.py https://www.rskey.org/CMS/the-library/?view=article&id=14
    python download_files.py https://example.com --type docx --output moje_soubory
"""

import argparse
import os
import sys

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


def download_files(url: str, file_extension: str = "pdf", output_dir: str = "downloads") -> None:
    """
    Stáhne všechny soubory dané přípony, na které vedou odkazy na zadané URL.

    Args:
        url:            URL stránky, která bude prohledána.
        file_extension: Přípona hledaných souborů (bez tečky), výchozí 'pdf'.
        output_dir:     Cílová složka pro uložení souborů.
    """
    os.makedirs(output_dir, exist_ok=True)

    ext = file_extension.lower().lstrip(".")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    print(f"Načítám stránku: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Chyba při načítání stránky: {e}", file=sys.stderr)
        sys.exit(1)

    soup = BeautifulSoup(response.text, "html.parser")

    # Najdi všechny <a href="..."> jejichž href končí požadovanou příponou
    file_urls: list[str] = []
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"].strip()
        # Porovnej příponu (ignoruj query string / fragment)
        path = urlparse(href).path
        if path.lower().endswith(f".{ext}"):
            full_url = urljoin(url, href)
            if full_url not in file_urls:
                file_urls.append(full_url)

    if not file_urls:
        print(f"Na stránce nebyly nalezeny žádné soubory s příponou .{ext}.")
        return

    print(f"Nalezeno {len(file_urls)} soubor(ů) .{ext}. Stahuji...\n")

    downloaded = 0
    failed = 0

    for file_url in file_urls:
        # Získej název souboru z URL (bez query stringu)
        filename = os.path.basename(urlparse(file_url).path)
        if not filename:
            filename = f"soubor_{downloaded + failed + 1}.{ext}"

        output_path = os.path.join(output_dir, filename)
        print(f"  [{downloaded + failed + 1}/{len(file_urls)}] {filename}", end="  ")

        try:
            file_response = requests.get(
                file_url, headers=headers, timeout=60, stream=True
            )
            file_response.raise_for_status()

            with open(output_path, "wb") as f:
                for chunk in file_response.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_kb = os.path.getsize(output_path) / 1024
            print(f"OK  ({size_kb:,.1f} KB)")
            downloaded += 1

        except requests.exceptions.RequestException as e:
            print(f"CHYBA  ({e})")
            failed += 1

    print(f"\nHotovo!  Staženo: {downloaded}  |  Neúspěšné: {failed}")
    print(f"Soubory jsou uloženy ve složce: {os.path.abspath(output_dir)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stáhne soubory (PDF a jiné) z odkazů nalezených na webové stránce.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Příklady:\n"
            "  python download_files.py https://example.com\n"
            "  python download_files.py https://example.com --type docx --output moje_soubory\n"
        ),
    )
    parser.add_argument(
        "url",
        help="URL stránky, která bude prohledána na výskyt souborů.",
    )
    parser.add_argument(
        "--type", "-t",
        default="pdf",
        dest="file_type",
        metavar="PŘÍPONA",
        help="Přípona hledaných souborů bez tečky (výchozí: pdf).",
    )
    parser.add_argument(
        "--output", "-o",
        default="downloads",
        dest="output_dir",
        metavar="SLOŽKA",
        help="Složka pro uložení stažených souborů (výchozí: downloads).",
    )

    args = parser.parse_args()
    download_files(args.url, args.file_type, args.output_dir)


if __name__ == "__main__":
    main()
