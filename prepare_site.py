#!/usr/bin/env python3
"""
Prepare site-ready data from scraped referendum results.

- Cleans and validates scraper output
- Computes aggregates (national + regional)
- Outputs JSON files for frontend
"""

import argparse
import json
from pathlib import Path

import pandas as pd


def load_data(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    # Ensure numeric types
    numeric_cols = [
        "electors",
        "sections_total",
        "sections_reported",
        "yes",
        "no",
        "yes_pct",
        "no_pct",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    # Progress per comune
    df["progress"] = df["sections_reported"] / df["sections_total"]

    # Avoid division errors
    df["progress"] = df["progress"].fillna(0)

    return df


def filter_valid(df: pd.DataFrame) -> pd.DataFrame:
    # Keep only comuni with at least 1 section reported
    return df[df["sections_reported"] > 0].copy()


def compute_totals(df: pd.DataFrame) -> dict:
    total_yes = df["yes"].sum()
    total_no = df["no"].sum()

    total_votes = total_yes + total_no

    return {
        "yes": int(total_yes),
        "no": int(total_no),
        "yes_pct": (total_yes / total_votes * 100) if total_votes else 0,
        "no_pct": (total_no / total_votes * 100) if total_votes else 0,
        "sections_reported": int(df["sections_reported"].sum()),
        "sections_total": int(df["sections_total"].sum()),
        "progress": (
            df["sections_reported"].sum() / df["sections_total"].sum()
            if df["sections_total"].sum() > 0
            else 0
        ),
    }


def group_by_region(df: pd.DataFrame) -> list[dict]:
    grouped = []

    for region, g in df.groupby("region"):
        totals = compute_totals(g)

        grouped.append(
            {
                "region": region,
                **totals,
            }
        )

    return grouped


def group_by_province(df: pd.DataFrame) -> list[dict]:
    grouped = []

    for (region, province), g in df.groupby(["region", "province"]):
        totals = compute_totals(g)

        grouped.append(
            {
                "region": region,
                "province": province,
                **totals,
            }
        )

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

    return df[cols].to_dict(orient="records")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output-dir", default="docs/data")

    args = parser.parse_args()

    csv_path = Path(args.csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    df = load_data(csv_path)

    print("Enriching...")
    df = enrich(df)

    print("Filtering valid rows...")
    df_valid = filter_valid(df)

    if df_valid.empty:
        print("No valid data yet — exiting")
        return

    print("Computing aggregates...")

    national = compute_totals(df_valid)
    regions = group_by_region(df_valid)
    provinces = group_by_province(df_valid)
    comuni = build_comuni(df_valid)

    print("Saving JSON...")

    (output_dir / "national.json").write_text(json.dumps(national, indent=2))
    (output_dir / "regions.json").write_text(json.dumps(regions, indent=2))
    (output_dir / "provinces.json").write_text(json.dumps(provinces, indent=2))
    (output_dir / "comuni.json").write_text(json.dumps(comuni, indent=2))

    print("Done ✅")


if __name__ == "__main__":
    main()