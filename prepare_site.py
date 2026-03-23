#!/usr/bin/env python3
"""
Prepare site-ready data from scraped referendum results.
Updated to output EXACTLY the nested JSON structure required by app.js.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

def load_data(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)

    # Ensure numerical columns are safe floats/ints
    cols_to_check = ["yes", "no", "sections_reported", "sections_total", "electors"]
    for c in cols_to_check:
        if c in df.columns: 
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        else: 
            df[c] = 0

    # Fill missing text columns
    for c in ["region", "province", "comune"]:
        if c not in df.columns:
            df[c] = "Sconosciuto"
        df[c] = df[c].fillna("Sconosciuto")

    return df

def compute_totals(df: pd.DataFrame) -> dict:
    total_yes = int(df["yes"].sum())
    total_no = int(df["no"].sum())
    total_votes = total_yes + total_no
    
    electors = int(df["electors"].sum())
    avg_turnout = float((total_votes / electors * 100) if electors > 0 else 0.0)

    # EXACT NESTED STRUCTURE APP.JS EXPECTS
    return {
        "elettori": electors,
        "fetched_at": datetime.now().isoformat(),
        "has_results": bool(total_votes > 0),
        "affluenza": {
            "best_perc": avg_turnout,
            "best_votanti": total_votes,
            "snapshots": [] # Safely mapped as empty for the progress bar
        },
        "results": {
            "perc_si": float((total_yes / total_votes * 100) if total_votes else 0.0),
            "perc_no": float((total_no / total_votes * 100) if total_votes else 0.0),
            "si": total_yes,
            "no": total_no,
            "validi": total_votes
        },
        "scrutini_p": int(df["sections_total"].sum()),
        "scrutini_t": int(df["sections_reported"].sum())
    }

def group_by_region(df: pd.DataFrame) -> list[dict]:
    grouped = []
    for region_name, g in df.groupby("region"):
        totals = compute_totals(g)
        totals["regione"] = region_name  # app.js expects "r.regione"
        grouped.append(totals)
    return grouped

def build_comuni(df: pd.DataFrame) -> list[dict]:
    comuni_list = []
    for _, row in df.iterrows():
        total_votes = row["yes"] + row["no"]
        # app.js popup expects specific Italian properties
        comuni_list.append({
            "regione": row["region"],
            "provincia": row["province"],
            "comune": row["comune"],
            "elettori": int(row["electors"]),
            "perc_si": float((row["yes"]/total_votes*100) if total_votes > 0 else 0.0),
            "perc_no": float((row["no"]/total_votes*100) if total_votes > 0 else 0.0),
            "si": int(row["yes"]),
            "no": int(row["no"]),
            "com4_perc": float((total_votes / row["electors"] * 100) if row["electors"] > 0 else 0.0), 
            "com4_vot": int(total_votes)
        })
    return comuni_list

def main():
    parser = argparse.ArgumentParser(description="Prepare referendum results JSON")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output-dir", default="docs/data")
    parser.add_argument("--skip-boundaries", action="store_true")
    parser.add_argument("--boundaries")
    
    args = parser.parse_args()

    csv_path = Path(args.csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        print(f"Error: {csv_path} not found.")
        sys.exit(1)

    df = load_data(csv_path)

    national = compute_totals(df)
    regions = group_by_region(df)
    comuni = build_comuni(df)

    (output_dir / "national.json").write_text(json.dumps(national, indent=2))
    (output_dir / "regions.json").write_text(json.dumps(regions, indent=2))
    (output_dir / "comuni.json").write_text(json.dumps(comuni, indent=2))

    print("Data processed perfectly for app.js!")

if __name__ == "__main__":
    main()