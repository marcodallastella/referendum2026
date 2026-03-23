#!/usr/bin/env python3
"""
Scraper for Italian referendum 2026 results (Ministero dell'Interno API).

Simplified version:
- Uses ONLY scrutiniFI endpoint
- Fully data-driven (no time-based logic)
- Parses new API structure (int + scheda)
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

logger = logging.getLogger("referendum2026")

API_BASE = "https://eleapi.interno.gov.it/siel/PX"
DEFAULT_DATE = "20260322"
TIPO_ELEZIONE = "09"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://elezioni.interno.gov.it",
    "referer": "https://elezioni.interno.gov.it/",
    "user-agent": "Mozilla/5.0",
}

# Province codes
PR_TO_ISTAT = {
    "001": "084", "002": "006", "003": "042", "004": "007", "005": "051",
    "006": "044", "007": "005", "008": "064", "009": "072", "010": "025",
    "011": "062", "012": "016", "013": "037", "014": "021", "015": "017",
    "016": "074", "017": "118", "018": "085", "019": "070", "020": "061",
    "021": "087", "022": "079", "023": "069", "024": "013", "025": "078",
    "026": "019", "027": "004", "028": "086", "029": "038", "030": "048",
    "031": "071", "032": "040", "033": "060", "034": "010", "035": "031",
    "036": "053", "037": "008", "038": "066", "039": "011", "040": "059",
    "041": "075", "042": "049", "043": "046", "044": "043", "045": "020",
    "046": "045", "047": "077", "048": "083", "049": "015", "050": "036",
    "051": "063", "052": "003", "053": "114", "054": "028", "055": "082",
    "056": "034", "057": "018", "058": "054", "059": "041", "060": "068",
    "061": "033", "062": "050", "063": "047", "064": "076", "065": "088",
    "066": "039", "067": "080", "068": "035", "069": "057", "070": "058",
    "071": "029", "072": "065", "073": "112", "074": "009", "075": "052",
    "076": "089", "077": "014", "078": "073", "079": "067", "080": "055",
    "081": "001", "082": "081", "083": "022", "084": "026", "085": "030",
    "086": "012", "087": "027", "088": "002", "089": "023", "090": "024",
    "091": "056", "092": "032", "093": "093", "094": "094", "095": "115",
    "096": "096", "097": "101", "098": "097", "099": "098", "100": "100",
    "101": "099", "102": "103", "103": "102", "104": "108", "105": "109",
    "106": "110", "112": "113", "113": "117", "114": "116", "115": "119",
}

ALL_PR_CODES = sorted(PR_TO_ISTAT.keys())


def build_url(endpoint: str, date: str, sk: str, pr: str) -> str:
    return f"{API_BASE}/{endpoint}/DE/{date}/TE/{TIPO_ELEZIONE}/SK/{sk}/PR/{pr}"


def parse_pct(value):
    if value is None:
        return None
    return float(str(value).replace(",", "."))


def parse_results(data: dict) -> list[dict]:
    rows = []

    info = data.get("int", {})
    schede = data.get("scheda", [])

    if not schede:
        return rows

    for s in schede:
        reported = s.get("sz_perv", 0)
        total = info.get("sz_tot", 0)

        if reported == 0:
            state = "no_results"
        elif reported < total:
            state = "partial"
        else:
            state = "complete"

        row = {
            "region": info.get("desc_reg"),
            "province": info.get("desc_prov"),
            "comune": info.get("desc_com"),

            "cod_reg": info.get("cod_reg"),
            "cod_prov": info.get("cod_prov"),
            "cod_com": info.get("cod_com"),

            "electors": info.get("ele_t"),

            "sections_total": total,
            "sections_reported": reported,

            "yes": s.get("voti_si"),
            "no": s.get("voti_no"),

            "yes_pct": parse_pct(s.get("perc_si")),
            "no_pct": parse_pct(s.get("perc_no")),

            "last_update": s.get("dt_agg"),
            "state": state,
        }

        rows.append(row)

    return rows


async def fetch_json(client, url, semaphore, delay):
    async with semaphore:
        try:
            r = await client.get(url, timeout=15)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
            await asyncio.sleep(delay)
            return data
        except Exception as e:
            logger.warning("Failed %s: %s", url, e)
            return None


async def scrape_all(date, quesiti, output_dir, delay, concurrency):
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(concurrency)
    timestamp = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient(headers=HEADERS) as client:
        rows = []

        async def fetch_one(pr, sk):
            url = build_url("scrutiniFI", date, sk, pr)
            data = await fetch_json(client, url, semaphore, delay)
            return pr, sk, data

        tasks = [fetch_one(pr, sk) for sk in quesiti for pr in ALL_PR_CODES]

        results = await asyncio.gather(*tasks)

        for pr, sk, data in results:
            if not data:
                continue

            raw_path = raw_dir / f"scrutiniFI_SK{sk}_PR{pr}.json"
            raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

            parsed = parse_results(data)
            rows.extend(parsed)

    if not rows:
        logger.error("No data collected!")
        return

    df = pd.DataFrame(rows)
    df["fetched_at"] = timestamp

    csv_path = output_dir / "referendum_results.csv"
    df.to_csv(csv_path, index=False)

    logger.info("Saved %d rows to %s", len(df), csv_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=DEFAULT_DATE)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--quesiti",
        nargs="+",
        default=["01", "02", "03", "04", "05"],
    )
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(
        scrape_all(
            date=args.date,
            quesiti=args.quesiti,
            output_dir=output_dir,
            delay=args.delay,
            concurrency=args.concurrency,
        )
    )


if __name__ == "__main__":
    main()