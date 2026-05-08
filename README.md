# download-files

Jednoduchý Python skript pro stažení souborů z odkazů nalezených na webové stránce.

Skript načte HTML zadané URL, vyhledá odkazy podle přípony (výchozí je `pdf`) a všechny nalezené soubory uloží do zvolené složky.

## Požadavky

- Python 3.9+
- Balíčky:
	- `requests`
	- `beautifulsoup4`

## Instalace

V adresáři projektu spusť:

```bash
pip install requests beautifulsoup4
```

## Použití

```bash
python download_files.py <URL> [--type <pripona>] [--output <slozka>]
```

### Parametry

- `url` (povinný)  
	URL stránky, ze které se mají odkazy načíst.

- `--type`, `-t` (volitelný, výchozí: `pdf`)  
	Typ souboru podle přípony, například `pdf`, `docx`, `xlsx`.

- `--output`, `-o` (volitelný, výchozí: `downloads`)  
	Cílová složka pro uložení stažených souborů.

## Příklady

Stažení všech PDF (výchozí chování):

```bash
python download_files.py "https://www.rskey.org/CMS/the-library/?view=article&id=14"
```

Stažení souborů typu DOCX do vlastní složky:

```bash
python download_files.py "https://example.com" --type docx --output moje_soubory
```

Použití zkrácených přepínačů:

```bash
python download_files.py "https://example.com" -t xlsx -o excely
```

## Co skript dělá

1. Načte HTML obsah zadané stránky.
2. Najde všechny odkazy `<a href="...">` končící požadovanou příponou.
3. Převede relativní odkazy na absolutní URL.
4. Odstraní duplicity.
5. Soubory stáhne a uloží do cílové složky.
6. Vypíše průběh a závěrečný souhrn (staženo / neúspěšné).

## Poznámky

- Porovnání přípony není citlivé na velikost písmen.
- Pokud stránka neobsahuje žádný odpovídající odkaz, skript pouze vypíše informaci a skončí.
