#!/usr/bin/env python3
"""
Prepare site-ready data from scraped referendum results.

- Cleans and validates scraper output
- Computes aggregates (national + regional)
- Outputs JSON files for frontend
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

def load_data(csv_path: Path) -> pd.DataFrame:
    # low_memory=False prevents the DtypeWarning on import
    df = pd.read_csv(csv_path, low_memory=False)

    # 1. Fix the Italian decimal commas BEFORE grouping
    # This turns "17,21" into 17.21 so Python stops crashing
    for col in ["com4_perc", "com3_perc", "com2_perc", "com1_perc"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(',', '.').apply(pd.to_numeric, errors='coerce').fillna(0)

    # 2. Merge rows safely
    if "cm_code" in df.columns:
        # Sort so 'results' (if they exist) override 'affluence', avoiding .max() crashes
        if "data_type" in df.columns:
            df = df.sort_values("data_type", ascending=False)
        df = df.groupby("cm_code").first().reset_index()

    # 3. Map scraper's technical names to your site's variable names
    mapping = {
        "scr_voti_si": "yes", 
        "scr_voti_no": "no",
        "scr_scrut_t": "sections_reported", 
        "scr_scrut_p": "sections_total",
        "ele_t": "electors", 
        "regione_name": "region",
        "provincia_name": "province", 
        "comune_name": "comune"
    }
    df = df.rename(columns=mapping)

    # 4. Create the 'best_perc' field for app.js using the highest available turnout
    df["best_perc"] = 0.0
    for col in ["com4_perc", "com3_perc", "com2_perc", "com1_perc"]:
        if col in df.columns:
            df["best_perc"] = df[col]
            break

    # 5. Ensure final columns are safe numbers
    cols_to_check = ["yes", "no", "sections_reported", "sections_total", "electors"]
    for c in cols_to_check:
        if c in df.columns: 
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        else: 
            df[c] = 0

    return df


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    # Calculate progress percentages
    df["progress"] = (df["sections_reported"] / df["sections_total"]).fillna(0)

    # Calculate vote percentages for the individual municipality rows
    total_v = df["yes"] + df["no"]
    df["yes_pct"] = (df["yes"] / total_v * 100).fillna(0)
    df["no_pct"] = (df["no"] / total_v * 100).fillna(0)
    
    # Add status placeholder
    df["state"] = df["progress"].apply(lambda x: "final" if x >= 1 else "counting")

    return df


def filter_valid(df: pd.DataFrame) -> pd.DataFrame:
    # Keep all rows so we can show 0% progress, or filter to those with electors
    return df[df["electors"] > 0].copy()


def compute_totals(df: pd.DataFrame) -> dict:
    total_yes = df["yes"].sum()
    total_no = df["no"].sum()
    total_votes = total_yes + total_no
    
    # Calculate the average turnout (weighted by electors)
    avg_turnout = (df["best_perc"] * df["electors"]).sum() / df["electors"].sum() if df["electors"].sum() > 0 else 0

    return {
        "yes": int(total_yes),
        "no": int(total_no),
        "yes_pct": float(total_yes / total_votes * 100) if total_votes else 0.0,
        "no_pct": float(total_no / total_votes * 100) if total_votes else 0.0,
        "best_perc": float(avg_turnout), # <--- ADDED FOR APP.JS
        "sections_reported": int(df["sections_reported"].sum()),
        "sections_total": int(df["sections_total"].sum()),
        "progress": float(df["sections_reported"].sum() / df["sections_total"].sum()) if df["sections_total"].sum() > 0 else 0.0,
    }


def group_by_region(df: pd.DataFrame) -> list[dict]:
    grouped = []
    # Use 'region' column mapped from 'regione_name'
    for region_name, g in df.groupby("region"):
        totals = compute_totals(g)
        grouped.append({"region": region_name, **totals})
    return grouped


def group_by_province(df: pd.DataFrame) -> list[dict]:
    grouped = []
    for (region, province), g in df.groupby(["region", "province"]):
        totals = compute_totals(g)
        grouped.append({"region": region, "province": province, **totals})
    return grouped


def build_comuni(df: pd.DataFrame) -> list[dict]:
    cols = [
        "region",
        "province",
        "comune",
        "yes",
        "no",
        "yes_pct",
        "no_pct",
        "sections_reported",
        "sections_total",
        "progress",
        "state",
    ]
    # Filter to only existing columns to avoid errors
    existing_cols = [c for c in cols if c in df.columns]
    return df[existing_cols].to_dict(orient="records")


def main():
    parser = argparse.ArgumentParser(description="Prepare referendum results JSON")
    parser.add_argument("--csv", required=True, help="Path to scraper CSV")
    parser.add_argument("--output-dir", default="docs/data", help="Output directory")
    
    # --- FIX 3: ADD MISSING CI FLAGS ---
    parser.add_argument("--skip-boundaries", action="store_true", help="CI compatibility flag")
    parser.add_argument("--boundaries", help="CI compatibility flag")

    args = parser.parse_args()

    csv_path = Path(args.csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading {csv_path}...")
    df = load_data(csv_path)

    print("Processing results...")
    df = enrich(df)
    df_valid = filter_valid(df)

    if df_valid.empty:
        print("Warning: No valid data found in CSV.")
    
    print("Generating summaries...")
    national = compute_totals(df_valid)
    regions = group_by_region(df_valid)
    provinces = group_by_province(df_valid)
    comuni = build_comuni(df_valid)

    # Save outputs
    (output_dir / "national.json").write_text(json.dumps(national, indent=2))
    (output_dir / "regions.json").write_text(json.dumps(regions, indent=2))
    (output_dir / "provinces.json").write_text(json.dumps(provinces, indent=2))
    (output_dir / "comuni.json").write_text(json.dumps(comuni, indent=2))

    print(f"Done ✅ Files saved to {output_dir}/")


if __name__ == "__main__":
    main()