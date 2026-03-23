# Referendum Costituzionale 2026

Risultati in tempo reale del referendum costituzionale italiano del 22-23 marzo 2026 sulla riforma della giustizia (riforma Nordio).

**Sito live:** https://marcodallastella.github.io/referendum2026/

## Come funziona

1. **Scraper** (`scraper.py`) — interroga l'API del Ministero dell'Interno ogni 5 minuti durante lo spoglio e salva i dati in `output/referendum_results.csv`
2. **Processore** (`prepare_site.py`) — genera i file JSON e GeoJSON ottimizzati per il sito web (`docs/data/`)
3. **Sito** (`docs/`) — frontend statico con mappa interattiva, tabella regionale e pannello riassuntivo
4. **Automazione** (`.github/workflows/update-data.yml`) — GitHub Actions esegue l'intero ciclo ad ogni aggiornamento programmato

## Uso locale

```bash
# Installa dipendenze
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Scarica dati affluenza
python scraper.py --mode affluence

# Scarica dati scrutinio (dopo la chiusura dei seggi)
python scraper.py --mode both

# Rigenera i file per il sito (riusa GeoJSON esistente)
python prepare_site.py --skip-boundaries

# Rigenera anche i confini geografici (richiede geopandas, lento)
pip install geopandas
python prepare_site.py
```

## Parametri scraper

| Parametro | Default | Descrizione |
|---|---|---|
| `--mode` | `affluence` | `affluence`, `results`, o `both` |
| `--date` | `20260322` | Data elezione YYYYMMDD |
| `--concurrency` | `5` | Richieste API parallele |
| `--delay` | `0.2` | Pausa tra richieste (secondi) |
| `--quesiti` | `01 02 03 04 05` | Quesiti da scaricare |
| `--verbose` | off | Log dettagliati |

## Sorgente dati

I dati provengono dall'API del Ministero dell'Interno che alimenta il portale ufficiale [elezioni.interno.gov.it](https://elezioni.interno.gov.it). L'API non è documentata pubblicamente; i parametri sono stati ricostruiti per reverse engineering.

I confini geografici dei comuni sono forniti dall'[ISTAT](https://www.istat.it/).

## Stack tecnico

- **Python** — httpx (async), pandas, openpyxl, geopandas
- **Frontend** — HTML/CSS/JS vanilla, MapLibre GL, Google Fonts
- **Infrastruttura** — GitHub Actions, GitHub Pages
- **Dati** — CSV + GeoJSON flat file (nessun database)

---

*Creato da [Marco Dalla Stella](https://github.com/marcodallastella)*
