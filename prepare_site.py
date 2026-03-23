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
    if not csv_path.exists():
        print(f"Error: {csv_path} not found.")
        sys.exit(1)

    df = pd.read_csv(csv_path)

    # --- FIX 1: MERGE ROWS ---
    # The scraper produces two rows per municipality (data_type='affluence' and 'results').
    # We group by the municipality code (cm_code) to combine them into one row.
    if "cm_code" in df.columns:
        df = df.groupby("cm_code").first().reset_index()

    # --- FIX 2: COLUMN MAPPING ---
    # Map the Ministry API keys from the scraper to the names used in this script.
    mapping = {
        "regione_name": "region",
        "provincia_name": "province",
        "comune_name": "comune",
        "ele_t": "electors",
        "scr_scrut_p": "sections_total",
        "scr_scrut_t": "sections_reported",
        "scr_voti_si": "yes",
        "scr_voti_no": "no",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})

    # Ensure numeric types and handle missing columns
    numeric_cols = [
        "electors",
        "sections_total",
        "sections_reported",
        "yes",
        "no",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0

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

    reported = df["sections_reported"].sum()
    total_sections = df["sections_total"].sum()

    return {
        "yes": int(total_yes),
        "no": int(total_no),
        "yes_pct": float(total_yes / total_votes * 100) if total_votes else 0.0,
        "no_pct": float(total_no / total_votes * 100) if total_votes else 0.0,
        "sections_reported": int(reported),
        "sections_total": int(total_sections),
        "progress": float(reported / total_sections) if total_sections > 0 else 0.0,
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