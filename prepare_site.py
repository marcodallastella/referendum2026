#!/usr/bin/env python3
"""
Prepare data files for the 2026 constitutional referendum website.

Downloads ISTAT municipality boundaries, processes affluence/results data,
and generates optimized GeoJSON + JSON files for the web application.

Usage:
    python prepare_site.py                        # full pipeline
    python prepare_site.py --skip-boundaries      # skip map download (reuse existing)
    python prepare_site.py --boundaries path.shp  # use local shapefile

Requirements:
    pip install pandas geopandas requests openpyxl
"""

import io
import json
import math
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd
import requests

try:
    import geopandas as gpd
except ImportError:
    gpd = None  # Only needed for boundary generation, not --skip-boundaries

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CSV_PATH = Path("output/referendum_results.csv")
SITE_DATA_DIR = Path("docs/data")
SIMPLIFY_TOLERANCE = 0.002  # ~200m, good balance of detail vs file size
REGION_SIMPLIFY_TOLERANCE = 0.003  # coarser for region outlines (display only)
COORD_PRECISION = 4  # decimal places (~11m accuracy)

ISTAT_URLS = [
    "https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati/2025/Limiti01012025_g.zip",
    "https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati/2024/Limiti01012024_g.zip",
    "https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati/2023/Limiti01012023_g.zip",
]

# ISTAT region codes → names (standard mapping)
COD_REG_MAP = {
    1: "PIEMONTE", 2: "VALLE D'AOSTA", 3: "LOMBARDIA",
    4: "TRENTINO-ALTO ADIGE", 5: "VENETO", 6: "FRIULI-VENEZIA GIULIA",
    7: "LIGURIA", 8: "EMILIA-ROMAGNA", 9: "TOSCANA", 10: "UMBRIA",
    11: "MARCHE", 12: "LAZIO", 13: "ABRUZZO", 14: "MOLISE",
    15: "CAMPANIA", 16: "PUGLIA", 17: "BASILICATA", 18: "CALABRIA",
    19: "SICILIA", 20: "SARDEGNA",
}

# Time snapshot labels
SNAPSHOT_LABELS = {
    1: "12:00",
    2: "19:00",
    3: "23:00",
    4: "Finale",
}

# Manual overrides for bilingual ISTAT names that don't normalize cleanly
# ISTAT name → API/CSV name
ISTAT_NAME_OVERRIDES = {
    "Doberdò del Lago-Doberdob": "DOBERDO' DEL LAGO",
    "Duino Aurisina-Devin Nabrežina": "DUINO AURISINA",
    "Monrupino-Repentabor": "MONRUPINO",
    "San Floriano del Collio-Števerjan": "SAN FLORIANO DEL COLLIO",
    "Savogna d'Isonzo-Sovodnje ob Soči": "SAVOGNA D'ISONZO",
    "Sgonico-Zgonik": "SGONICO",
    "San Giovanni di Fassa-Sèn Jan": "SAN GIOVANNI DI FASSA",
    "Montescudo-Monte Colombo": "MONTESCUDO - MONTE COLOMBO",
    "Moio Alcantara": "MOJO ALCANTARA",
    "Murisengo": "MURISENGO MONFERRATO",
    "Lirio": "LIRIO",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Normalize a name for matching: uppercase, strip accents, remove punctuation."""
    if not isinstance(name, str):
        return ""
    name = name.upper().strip()
    # Remove accents
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    # For bilingual ISTAT names (e.g. "X/Y" or "X - Y"), keep only the first part
    # Don't split on bare "-" as many Italian names use hyphens legitimately
    for sep in [" / ", "/", " - "]:
        if sep in name:
            name = name.split(sep)[0].strip()
            break
    # Replace apostrophes, hyphens, and other separators with space
    name = name.replace("'", " ").replace("\u2019", " ").replace("-", " ").replace("?", " ")
    # Remove other non-alphanumeric (except space)
    name = re.sub(r"[^A-Z0-9 ]", "", name)
    # Collapse whitespace
    name = " ".join(name.split())
    return name


def round_coords(obj, precision=COORD_PRECISION):
    """Recursively round all floats in a nested structure."""
    if isinstance(obj, float):
        return round(obj, precision)
    if isinstance(obj, dict):
        return {k: round_coords(v, precision) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_coords(item, precision) for item in obj]
    return obj


def parse_italian_decimal(val) -> float:
    """Parse Italian decimal format ('36,12') to float. Returns 0.0 for unparseable values."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip().replace(",", ".")
        try:
            return float(val)
        except ValueError:
            return 0.0
    return 0.0


def safe_int(val) -> int:
    """Safely convert to int, returning 0 for NaN/None."""
    if pd.isna(val):
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def sanitize_nan(obj):
    """Replace NaN/Inf floats with None so json.dump produces valid JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_nan(item) for item in obj]
    return obj


def write_json(data, path: Path, round_floats=False):
    """Write JSON to file, optionally rounding coordinates."""
    if round_floats:
        data = round_coords(data)
    data = sanitize_nan(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"  Wrote {path} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Boundary download & processing (reused from original)
# ---------------------------------------------------------------------------

def download_istat_boundaries() -> "gpd.GeoDataFrame":
    """Download ISTAT generalised municipality boundaries."""
    for url in ISTAT_URLS:
        try:
            print(f"  Trying {url} ...")
            resp = requests.get(url, timeout=300)
            resp.raise_for_status()

            tmpdir = tempfile.mkdtemp()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                zf.extractall(tmpdir)

            # Find the municipality shapefile (Com*_WGS84.shp)
            shp = None
            for p in Path(tmpdir).rglob("Com*_WGS84.shp"):
                shp = p
                break
            if shp is None:
                for p in Path(tmpdir).rglob("Com*.shp"):
                    shp = p
                    break

            if shp is None:
                shutil.rmtree(tmpdir)
                print("    No municipality shapefile found in ZIP.")
                continue

            print(f"  Reading {shp.name} ...")
            gdf = gpd.read_file(shp, encoding="utf-8")
            shutil.rmtree(tmpdir)

            if gdf.crs and str(gdf.crs) != "EPSG:4326":
                print("  Reprojecting to WGS84 ...")
                gdf = gdf.to_crs("EPSG:4326")

            print(f"  Loaded {len(gdf)} municipalities.")
            return gdf

        except Exception as e:
            print(f"    Failed: {e}")
            continue

    print("\nERROR: Could not download ISTAT boundaries.")
    print("You can download manually from https://www.istat.it/ and use --boundaries flag.")
    sys.exit(1)


def prepare_boundaries(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":
    """Simplify geometries and prepare for web use."""
    print(f"  Simplifying ({len(gdf)} features, tolerance={SIMPLIFY_TOLERANCE}) ...")
    gdf = gdf.copy()
    gdf.geometry = gdf.geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)

    # Add normalised region name from COD_REG
    if "COD_REG" in gdf.columns:
        gdf["REGIONE"] = gdf["COD_REG"].map(COD_REG_MAP)
    elif "COD_REGIONE" in gdf.columns:
        gdf["REGIONE"] = gdf["COD_REGIONE"].map(COD_REG_MAP)

    # Apply manual overrides for bilingual names
    gdf["COMUNE_MATCH"] = gdf["COMUNE"].map(
        lambda x: ISTAT_NAME_OVERRIDES.get(x, x)
    )

    # Normalised comune name for matching
    gdf["MATCH_KEY"] = gdf.apply(
        lambda r: normalize_name(str(r.get("REGIONE", "")))
        + "|"
        + normalize_name(str(r.get("COMUNE_MATCH", ""))),
        axis=1,
    )

    return gdf


# ---------------------------------------------------------------------------
# Data loading & processing
# ---------------------------------------------------------------------------

def load_csv(csv_path: str) -> pd.DataFrame:
    """Load the referendum CSV and filter to quesito 1 only."""
    print(f"  Loading {csv_path} ...")
    df = pd.read_csv(csv_path, low_memory=False)

    # Use only quesito == 1 to avoid duplicates
    df = df[df["quesito"] == 1].copy()
    print(f"  Filtered to quesito 1: {len(df)} rows")

    # Parse Italian decimal percentages
    for col in ["com1_perc", "com2_perc", "com3_perc", "com4_perc"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_italian_decimal)

    # Ensure numeric columns are numeric
    for col in ["ele_t", "ele_m", "ele_f",
                 "com1_vot_t", "com2_vot_t", "com3_vot_t", "com4_vot_t",
                 "com1_vot_m", "com1_vot_f", "com2_vot_m", "com2_vot_f",
                 "com3_vot_m", "com3_vot_f", "com4_vot_m", "com4_vot_f"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df


def best_turnout(row) -> tuple[float, int]:
    """Return (best_perc, best_vot_t) using latest non-zero snapshot."""
    for i in [4, 3, 2, 1]:
        vot = safe_int(row.get(f"com{i}_vot_t", 0))
        if vot > 0:
            return (float(row.get(f"com{i}_perc", 0)), vot)
    return (0.0, 0)


def affluence_snapshots(row) -> list[dict]:
    """Extract the time-series affluence snapshots for a row."""
    snapshots = []
    for i in [1, 2, 3, 4]:
        vot = safe_int(row.get(f"com{i}_vot_t", 0))
        perc = float(row.get(f"com{i}_perc", 0))
        snapshots.append({
            "label": SNAPSHOT_LABELS[i],
            "votanti": vot,
            "perc": round(perc, 2),
        })
    return snapshots


def results_fields(row) -> dict:
    """Extract results fields if present (data_type == 'results' rows).
    For now, returns null placeholders since results aren't available yet."""
    # Future: when results data arrives, these columns will exist:
    # scr_vot_si, scr_vot_no, scr_sk_bianche, scr_sk_nulle, scr_vot_validi, etc.
    # The exact field names are TBD from the API scrutiniFI response.
    result = {
        "si": None,
        "no": None,
        "validi": None,
        "bianche": None,
        "nulle": None,
        "perc_si": None,
        "perc_no": None,
    }
    # Check for any results columns (prefixed with scr_)
    scr_cols = [c for c in row.index if str(c).startswith("scr_")]
    if scr_cols:
        # Try common field patterns from the scrutiniFI parser
        si = safe_int(row.get("scr_vot_si", 0))
        no = safe_int(row.get("scr_vot_no", 0))
        validi = safe_int(row.get("scr_vot_validi", 0))
        bianche = safe_int(row.get("scr_sk_bianche", 0))
        nulle = safe_int(row.get("scr_sk_nulle", 0))
        if validi > 0:
            result = {
                "si": si,
                "no": no,
                "validi": validi,
                "bianche": bianche,
                "nulle": nulle,
                "perc_si": round(si / validi * 100, 2),
                "perc_no": round(no / validi * 100, 2),
            }
    return result


# ---------------------------------------------------------------------------
# GeoJSON generation
# ---------------------------------------------------------------------------

def match_data_to_geojson(gdf: "gpd.GeoDataFrame", df: pd.DataFrame) -> dict:
    """Build a GeoJSON FeatureCollection with election data embedded in properties."""

    # Build lookup: MATCH_KEY → row data
    df = df.copy()
    df["MATCH_KEY"] = df.apply(
        lambda r: normalize_name(str(r["regione_name"])) + "|" + normalize_name(str(r["comune_name"])),
        axis=1,
    )

    csv_lookup = {}
    # Also build a comune-only lookup for fallback matching
    csv_comune_lookup = {}
    for _, row in df.iterrows():
        key = row["MATCH_KEY"]
        if key not in csv_lookup:
            csv_lookup[key] = row
        comune_key = key.split("|")[1]
        if comune_key not in csv_comune_lookup:
            csv_comune_lookup[comune_key] = row

    features = []
    matched = 0
    unmatched_geo = []

    for _, geo_row in gdf.iterrows():
        key = geo_row["MATCH_KEY"]
        geom = geo_row.geometry

        if geom is None or geom.is_empty:
            continue

        props = {
            "comune": str(geo_row.get("COMUNE", "")),
            "regione": str(geo_row.get("REGIONE", "")),
        }

        # Try exact match first, then fallback to comune-only match
        data_row = csv_lookup.get(key)
        if data_row is None:
            comune_key = key.split("|")[1]
            data_row = csv_comune_lookup.get(comune_key)

        if data_row is not None:
            matched += 1
            props["provincia"] = str(data_row.get("provincia_name", ""))
            props["elettori"] = safe_int(data_row["ele_t"])

            # Affluence snapshots
            perc, vot = best_turnout(data_row)
            props["affluenza_perc"] = round(perc, 2)
            props["affluenza_votanti"] = vot
            for i in [1, 2, 3, 4]:
                props[f"com{i}_perc"] = round(float(data_row.get(f"com{i}_perc", 0)), 2)
                props[f"com{i}_vot"] = safe_int(data_row.get(f"com{i}_vot_t", 0))

            # Results (placeholder)
            res = results_fields(data_row)
            props["si"] = res["si"]
            props["no"] = res["no"]
            props["validi"] = res["validi"]
            props["bianche"] = res["bianche"]
            props["nulle"] = res["nulle"]
            props["perc_si"] = res["perc_si"]
            props["perc_no"] = res["perc_no"]
        else:
            unmatched_geo.append(geo_row.get("COMUNE", "???"))

        feature = {
            "type": "Feature",
            "geometry": json.loads(gpd.GeoSeries([geom]).to_json())["features"][0]["geometry"],
            "properties": props,
        }
        features.append(feature)

    geojson = {"type": "FeatureCollection", "features": features}

    matched_keys = set(gdf["MATCH_KEY"])
    unmatched_csv = [
        csv_lookup[k]["comune_name"]
        for k in csv_lookup
        if k not in matched_keys
    ]

    print(f"  Matched: {matched}/{len(df)} comuni")
    if unmatched_geo:
        print(f"  Unmatched geometries: {len(unmatched_geo)} (no election data)")
        if len(unmatched_geo) <= 20:
            for name in sorted(unmatched_geo):
                print(f"    - {name}")
    if unmatched_csv:
        print(f"  Unmatched CSV rows: {len(unmatched_csv)} (no geometry)")
        if len(unmatched_csv) <= 20:
            for name in sorted(unmatched_csv):
                print(f"    - {name}")

    return geojson


# ---------------------------------------------------------------------------
# Aggregate computations
# ---------------------------------------------------------------------------

def compute_national_summary(df: pd.DataFrame) -> dict:
    """Compute national aggregate: affluence time series + results placeholder."""
    elettori = int(df["ele_t"].sum())
    # Use the most recent scrape timestamp from the data for UI display
    fetched_at = str(df["fetched_at"].max()) if "fetched_at" in df.columns else None
    n_comuni = len(df)

    snapshots = []
    for i in [1, 2, 3, 4]:
        vot_col = f"com{i}_vot_t"
        votanti = int(df[vot_col].sum())
        perc = round(votanti / elettori * 100, 2) if elettori else 0
        snapshots.append({
            "label": SNAPSHOT_LABELS[i],
            "votanti": votanti,
            "perc": perc,
        })

    # Best turnout (latest non-zero snapshot at national level)
    best_perc = 0.0
    best_vot = 0
    for s in reversed(snapshots):
        if s["votanti"] > 0:
            best_perc = s["perc"]
            best_vot = s["votanti"]
            break

    # Results: aggregate if any results columns exist
    has_results = False
    results = {
        "si": None, "no": None, "validi": None,
        "bianche": None, "nulle": None,
        "perc_si": None, "perc_no": None,
    }
    scr_cols = [c for c in df.columns if c.startswith("scr_")]
    if scr_cols and "scr_vot_si" in df.columns:
        si = int(df["scr_vot_si"].fillna(0).sum())
        no = int(df["scr_vot_no"].fillna(0).sum())
        validi = int(df["scr_vot_validi"].fillna(0).sum())
        if validi > 0:
            has_results = True
            results = {
                "si": si, "no": no, "validi": validi,
                "bianche": int(df["scr_sk_bianche"].fillna(0).sum()),
                "nulle": int(df["scr_sk_nulle"].fillna(0).sum()),
                "perc_si": round(si / validi * 100, 2),
                "perc_no": round(no / validi * 100, 2),
            }

    return {
        "title": "Referendum Costituzionale 2026",
        "subtitle": "Riforma della giustizia (Nordio)",
        "date": "22-23 marzo 2026",
        "fetched_at": fetched_at,
        "n_comuni": n_comuni,
        "elettori": elettori,
        "affluenza": {
            "snapshots": snapshots,
            "best_perc": best_perc,
            "best_votanti": best_vot,
        },
        "has_results": has_results,
        "results": results,
    }


def compute_regional_data(df: pd.DataFrame) -> list[dict]:
    """Compute per-region aggregates."""
    regions = []
    for regione, rdf in df.groupby("regione_name"):
        elettori = int(rdf["ele_t"].sum())
        n_comuni = len(rdf)

        snapshots = []
        for i in [1, 2, 3, 4]:
            votanti = int(rdf[f"com{i}_vot_t"].sum())
            perc = round(votanti / elettori * 100, 2) if elettori else 0
            snapshots.append({
                "label": SNAPSHOT_LABELS[i],
                "votanti": votanti,
                "perc": perc,
            })

        best_perc = 0.0
        best_vot = 0
        for s in reversed(snapshots):
            if s["votanti"] > 0:
                best_perc = s["perc"]
                best_vot = s["votanti"]
                break

        # Results placeholder
        results = {
            "si": None, "no": None, "validi": None,
            "perc_si": None, "perc_no": None,
        }
        if "scr_vot_si" in rdf.columns:
            si = int(rdf["scr_vot_si"].fillna(0).sum())
            no = int(rdf["scr_vot_no"].fillna(0).sum())
            validi = int(rdf["scr_vot_validi"].fillna(0).sum())
            if validi > 0:
                results = {
                    "si": si, "no": no, "validi": validi,
                    "perc_si": round(si / validi * 100, 2),
                    "perc_no": round(no / validi * 100, 2),
                }

        regions.append({
            "regione": regione,
            "elettori": elettori,
            "n_comuni": n_comuni,
            "affluenza": {
                "snapshots": snapshots,
                "best_perc": best_perc,
                "best_votanti": best_vot,
            },
            "results": results,
        })

    return sorted(regions, key=lambda x: x["regione"])


# ---------------------------------------------------------------------------
# Region boundary generation
# ---------------------------------------------------------------------------

def generate_region_boundaries(gdf: "gpd.GeoDataFrame", output_path: Path):
    """Dissolve municipality geometries by region and write a simplified GeoJSON."""
    print("  Dissolving municipalities into region boundaries ...")
    region_col = "REGIONE"
    if region_col not in gdf.columns:
        print("    WARNING: No REGIONE column found, skipping region boundaries.")
        return

    regions_gdf = gdf.dissolve(by=region_col).reset_index()
    print(f"  Simplifying {len(regions_gdf)} regions (tolerance={REGION_SIMPLIFY_TOLERANCE}) ...")
    regions_gdf.geometry = regions_gdf.geometry.simplify(
        REGION_SIMPLIFY_TOLERANCE, preserve_topology=True
    )

    # Build minimal GeoJSON with just region name
    features = []
    for _, row in regions_gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        feature = {
            "type": "Feature",
            "geometry": json.loads(gpd.GeoSeries([geom]).to_json())["features"][0]["geometry"],
            "properties": {"regione": str(row[region_col])},
        }
        features.append(feature)

    geojson = {"type": "FeatureCollection", "features": features}
    write_json(geojson, output_path, round_floats=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Prepare 2026 referendum website data")
    parser.add_argument("--skip-boundaries", action="store_true",
                        help="Skip boundary download, reuse existing GeoJSON")
    parser.add_argument("--boundaries", type=str, default=None,
                        help="Path to a local ISTAT municipality shapefile")
    parser.add_argument("--csv", type=str, default=str(CSV_PATH),
                        help="Path to referendum_results.csv")
    args = parser.parse_args()

    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    geojson_path = SITE_DATA_DIR / "italy.geojson"
    regions_geojson_path = SITE_DATA_DIR / "regions.geojson"

    # --- Step 1: Load election data ---
    print("\n[1/6] Loading election data ...")
    df = load_csv(args.csv)
    print(f"  {len(df)} rows, {len(df.columns)} columns")

    # --- Step 2: Prepare map boundaries ---
    if args.skip_boundaries and geojson_path.exists():
        print("\n[2/6] Skipping boundary download (--skip-boundaries)")
    else:
        if gpd is None:
            print("\nERROR: geopandas is required for boundary generation. "
                  "Install it with: pip install geopandas", file=sys.stderr)
            print("Use --skip-boundaries if the GeoJSON already exists.", file=sys.stderr)
            sys.exit(1)
        print("\n[2/6] Preparing map boundaries ...")
        if args.boundaries:
            print(f"  Reading local shapefile: {args.boundaries}")
            gdf = gpd.read_file(args.boundaries, encoding="utf-8")
            if gdf.crs and str(gdf.crs) != "EPSG:4326":
                gdf = gdf.to_crs("EPSG:4326")
        else:
            gdf = download_istat_boundaries()

        gdf = prepare_boundaries(gdf)

        print("  Matching election data to geometries ...")
        geojson = match_data_to_geojson(gdf, df)

        print("  Writing municipality GeoJSON ...")
        write_json(geojson, geojson_path, round_floats=True)

        print("  Generating region boundaries ...")
        generate_region_boundaries(gdf, regions_geojson_path)

    # --- Step 3: National summary ---
    print("\n[3/6] Computing national summary ...")
    national = compute_national_summary(df)
    write_json(national, SITE_DATA_DIR / "national.json")

    # --- Step 4: Regional data ---
    print("\n[4/6] Computing regional data ...")
    regions = compute_regional_data(df)
    write_json(regions, SITE_DATA_DIR / "regions.json")

    # --- Step 5: Copy raw CSV for download ---
    print("\n[5/6] Copying raw data for download ...")
    shutil.copy2(args.csv, SITE_DATA_DIR / "referendum_results.csv")
    print(f"  Copied {args.csv} → {SITE_DATA_DIR / 'referendum_results.csv'}")

    # [6/6] Summary
    print("\n--- Done ---")
    print(f"Site data directory: {SITE_DATA_DIR}/")
    for p in sorted(SITE_DATA_DIR.iterdir()):
        size = p.stat().st_size / 1024
        unit = "KB"
        if size > 1024:
            size /= 1024
            unit = "MB"
        print(f"  {p.name:30s} {size:6.1f} {unit}")


if __name__ == "__main__":
    main()
