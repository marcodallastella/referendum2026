#!/usr/bin/env python3
"""
Prepare referendum results JSON files and update GeoJSON for the website.

Reads referendum_results.csv (province-level from scraper.py) and produces:
  - docs/data/national.json   — national aggregated results
  - docs/data/regions.json    — results grouped by region
  - docs/data/italy.geojson   — updated: province results propagated to each comune
"""

import argparse
import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Name normalisation for matching CSV provinces → GeoJSON
# ---------------------------------------------------------------------------

def normalize_name(s: str) -> str:
    """
    Normalise province names for matching between API (CSV) and GeoJSON.
    - Strip accents (ì → i, è → e, etc.)
    - Remove apostrophes (FORLI'-CESENA → FORLI-CESENA)
    - Take only first part of bilingual names (Bolzano/Bozen → BOLZANO)
    - Uppercase and strip whitespace
    """
    if not s:
        return ""
    # Take first part of bilingual names separated by "/"
    s = str(s).split("/")[0]
    # NFD → strip combining diacritics
    nfd = unicodedata.normalize("NFD", s)
    stripped = "".join(c for c in nfd if not unicodedata.combining(c))
    # Remove apostrophes
    stripped = stripped.replace("'", "").replace("\u2019", "")
    return stripped.upper().strip()


# Manual aliases: normalised GeoJSON name → normalised API name
# Used when normalisation alone isn't enough (e.g. Valle d'Aosta → AOSTA)
_PROVINCE_ALIASES: dict[str, str] = {
    "VALLE DAOSTA": "AOSTA",
    "VALLÉE DAOSTA": "AOSTA",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)

    num_cols = ["ele_t", "sz_tot", "sz_perv", "vot_t", "si", "no",
                "perc_si", "perc_no", "bianche", "nulle"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        else:
            df[c] = 0

    for c in ["desc_reg", "desc_prov", "quesito"]:
        if c not in df.columns:
            df[c] = "Sconosciuto"
        df[c] = df[c].fillna("Sconosciuto")

    return df


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def compute_totals(df: pd.DataFrame) -> dict:
    """
    Aggregate province-level results.
    Turnout uses quesito 01 (same voters for all quesiti).
    Si/No totals sum across all quesiti.
    """
    quesiti_available = df["quesito"].astype(str).unique().tolist()
    df_q01 = df[df["quesito"].astype(str) == "01"] if "01" in quesiti_available else df

    electors = int(df_q01["ele_t"].sum())
    voters = int(df_q01["vot_t"].sum())
    turnout = float(voters / electors * 100) if electors > 0 else 0.0

    sz_perv = int(df_q01["sz_perv"].sum())
    sz_tot = int(df_q01["sz_tot"].sum())

    # Sum si/no across all quesiti for the overall tendency
    total_si = int(df["si"].sum())
    total_no = int(df["no"].sum())
    total_valid = total_si + total_no

    fetched_at = df["fetched_at"].max() if "fetched_at" in df.columns else datetime.now().isoformat()

    return {
        "elettori": electors,
        "fetched_at": str(fetched_at),
        "has_results": bool(total_valid > 0),
        "affluenza": {
            "best_perc": round(turnout, 2),
            "best_votanti": voters,
            "snapshots": [],
        },
        "results": {
            "perc_si": round(float(total_si / total_valid * 100), 2) if total_valid else 0.0,
            "perc_no": round(float(total_no / total_valid * 100), 2) if total_valid else 0.0,
            "si": total_si,
            "no": total_no,
            "validi": total_valid,
            "sezioni_scrutinate": sz_perv,
            "sezioni_totali": sz_tot,
        },
    }


def group_by_region(df: pd.DataFrame) -> list[dict]:
    grouped = []
    for region_name, g in df.groupby("desc_reg"):
        totals = compute_totals(g)
        totals["regione"] = region_name
        grouped.append(totals)
    return sorted(grouped, key=lambda r: r["regione"])


# ---------------------------------------------------------------------------
# GeoJSON update: propagate province results to each comune
# ---------------------------------------------------------------------------

def build_province_lookup(df: pd.DataFrame) -> dict[str, dict]:
    """
    Build {normalized_province_name: {perc_si, perc_no, si, no, ...}}
    using quesito 01 for per-province display.
    """
    df_q01 = df[df["quesito"].astype(str) == "01"].copy()
    if df_q01.empty:
        df_q01 = df.copy()

    lookup = {}
    for _, row in df_q01.iterrows():
        norm_prov = normalize_name(row["desc_prov"])
        total_valid = row["si"] + row["no"]
        # Only propagate percentages — absolute counts are province totals
        # and would be misleading in per-comune popups
        entry = {
            "perc_si": round(float(row["si"] / total_valid * 100), 2) if total_valid > 0 else None,
            "perc_no": round(float(row["no"] / total_valid * 100), 2) if total_valid > 0 else None,
            "si": None,
            "no": None,
            "validi": None,
            "bianche": None,
            "nulle": None,
        }
        lookup[norm_prov] = entry
    return lookup


def update_geojson(df: pd.DataFrame, geojson_path: Path) -> int:
    """
    Update italy.geojson with results from province-level data.
    Each comune inherits its province's results.
    Returns number of matched features.
    """
    if not geojson_path.exists():
        print(f"Warning: {geojson_path} not found — skipping GeoJSON update", file=sys.stderr)
        return 0

    lookup = build_province_lookup(df)

    with open(geojson_path) as f:
        geojson = json.load(f)

    matched = 0
    unmatched_provs = set()

    for feature in geojson["features"]:
        props = feature["properties"]
        norm_prov = normalize_name(props.get("provincia", ""))
        # Try direct match first, then alias lookup
        result = lookup.get(norm_prov) or lookup.get(_PROVINCE_ALIASES.get(norm_prov, ""))
        if result:
            props.update(result)
            matched += 1
        else:
            unmatched_provs.add(props.get("provincia", "?"))

    if unmatched_provs:
        print(f"Warning: {len(unmatched_provs)} provinces unmatched in GeoJSON:", file=sys.stderr)
        for p in sorted(unmatched_provs):
            print(f"  - {p}", file=sys.stderr)

    with open(geojson_path, "w") as f:
        json.dump(geojson, f, ensure_ascii=False, separators=(",", ":"))

    return matched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Prepare referendum results for website")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output-dir", default="docs/data")
    parser.add_argument("--geojson", default="docs/data/italy.geojson")
    parser.add_argument("--skip-geojson", action="store_true",
                        help="Skip GeoJSON update (only rebuild JSON aggregates)")

    args = parser.parse_args()

    csv_path = Path(args.csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        print(f"Error: {csv_path} not found.", file=sys.stderr)
        sys.exit(1)

    df = load_data(csv_path)
    print(f"Loaded {len(df)} rows ({df['quesito'].nunique()} quesiti, "
          f"{df['desc_prov'].nunique()} provinces)")

    national = compute_totals(df)
    regions = group_by_region(df)

    (output_dir / "national.json").write_text(
        json.dumps(national, indent=2, ensure_ascii=False)
    )
    (output_dir / "regions.json").write_text(
        json.dumps(regions, indent=2, ensure_ascii=False)
    )
    print(f"Written national.json (perc_si={national['results']['perc_si']:.1f}%) "
          f"and regions.json ({len(regions)} regions)")

    if not args.skip_geojson:
        geojson_path = Path(args.geojson)
        matched = update_geojson(df, geojson_path)
        print(f"Updated GeoJSON: {matched} comuni matched to province results")

    print("Done.")


if __name__ == "__main__":
    main()
