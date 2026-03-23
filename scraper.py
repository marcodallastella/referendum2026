#!/usr/bin/env python3
"""
Scraper for Italian referendum 2026 results (Ministero dell'Interno API).

Fetches scrutiniFI at province level: /RE/{cod_reg}/PR/{pr}
Province region codes are extracted from existing votantiFI raw data.
550 total calls (110 provinces × 5 quesiti).
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

ALL_PR_CODES = [
    "001", "002", "003", "004", "005", "006", "007", "008", "009", "010",
    "011", "012", "013", "014", "015", "016", "017", "018", "019", "020",
    "021", "022", "023", "024", "025", "026", "027", "028", "029", "030",
    "031", "032", "033", "034", "035", "036", "037", "038", "039", "040",
    "041", "042", "043", "044", "045", "046", "047", "048", "049", "050",
    "051", "052", "053", "054", "055", "056", "057", "058", "059", "060",
    "061", "062", "063", "064", "065", "066", "067", "068", "069", "070",
    "071", "072", "073", "074", "075", "076", "077", "078", "079", "080",
    "081", "082", "083", "084", "085", "086", "087", "088", "089", "090",
    "091", "092", "093", "094", "095", "096", "097", "098", "099", "100",
    "101", "102", "103", "104", "105", "106", "112", "113", "114", "115",
]


def build_scrutini_url(date: str, sk: str, cod_reg: int, pr: str) -> str:
    return f"{API_BASE}/scrutiniFI/DE/{date}/TE/{TIPO_ELEZIONE}/SK/{sk}/RE/{cod_reg:02d}/PR/{pr}"


def build_votanti_url(date: str, sk: str, pr: str) -> str:
    return f"{API_BASE}/votantiFI/DE/{date}/TE/{TIPO_ELEZIONE}/SK/{sk}/PR/{pr}"


def parse_pct(value):
    if value is None:
        return None
    return float(str(value).replace(",", "."))


async def fetch_json(client, url, semaphore, delay):
    async with semaphore:
        try:
            r = await client.get(url, timeout=15)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
            if "Error" in data:
                logger.debug("API error for %s: %s", url, data["Error"])
                return None
            await asyncio.sleep(delay)
            return data
        except Exception as e:
            logger.warning("Failed %s: %s", url, e)
            return None


def load_pr_region_map(raw_dir: Path) -> dict[str, int]:
    """Extract PR → cod_reg mapping from existing votantiFI raw files."""
    pr_to_reg = {}
    for pr in ALL_PR_CODES:
        path = raw_dir / f"votantiFI_SK01_PR{pr}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                ente_p = data.get("enti", {}).get("ente_p", {})
                com_list = ente_p.get("com", [])
                if com_list and com_list[0].get("cod_reg"):
                    pr_to_reg[pr] = com_list[0]["cod_reg"]
            except Exception as e:
                logger.warning("Failed to parse %s: %s", path, e)
    return pr_to_reg


def parse_scrutini_result(data: dict, sk: str, pr: str) -> dict | None:
    """Parse a province-level scrutiniFI response."""
    info = data.get("int", {})
    schede = data.get("scheda", [])
    if not schede:
        return None
    s = schede[0]

    reported = s.get("sz_perv", 0)
    total = info.get("sz_tot", 0)

    if reported == 0:
        state = "no_results"
    elif reported < total:
        state = "partial"
    else:
        state = "complete"

    return {
        "quesito": sk,
        "pr_code": pr,
        "cod_reg": info.get("cod_reg"),
        "cod_prov": info.get("cod_prov"),
        "desc_reg": info.get("desc_reg"),
        "desc_prov": info.get("desc_prov"),
        "ele_t": info.get("ele_t"),
        "sz_tot": total,
        "sz_perv": reported,
        "vot_t": s.get("vot_t"),
        "si": s.get("voti_si"),
        "no": s.get("voti_no"),
        "perc_si": parse_pct(s.get("perc_si")),
        "perc_no": parse_pct(s.get("perc_no")),
        "bianche": s.get("sk_bianche"),
        "nulle": s.get("sk_nulle"),
        "state": state,
    }


async def scrape_all(date, quesiti, output_dir, delay, concurrency):
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(concurrency)
    timestamp = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient(headers=HEADERS) as client:

        # Step 1: Build PR → region code mapping from votantiFI raw files
        logger.info("Loading province-region mapping from votantiFI data...")
        pr_to_reg = load_pr_region_map(raw_dir)

        # Fetch missing province region codes
        missing_prs = [pr for pr in ALL_PR_CODES if pr not in pr_to_reg]
        if missing_prs:
            logger.info("Fetching votantiFI for %d missing provinces...", len(missing_prs))

            async def fetch_votanti(pr):
                url = build_votanti_url(date, "01", pr)
                return pr, await fetch_json(client, url, semaphore, delay)

            results = await asyncio.gather(*[fetch_votanti(pr) for pr in missing_prs])
            for pr, data in results:
                if data:
                    raw_path = raw_dir / f"votantiFI_SK01_PR{pr}.json"
                    raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                    ente_p = data.get("enti", {}).get("ente_p", {})
                    com_list = ente_p.get("com", [])
                    if com_list and com_list[0].get("cod_reg"):
                        pr_to_reg[pr] = com_list[0]["cod_reg"]

        logger.info("Province-region map: %d provinces", len(pr_to_reg))

        # Step 2: Fetch scrutiniFI at province level
        logger.info("Fetching scrutiniFI for %d quesiti × %d provinces...",
                    len(quesiti), len(pr_to_reg))

        async def fetch_scrutini(pr, sk):
            cod_reg = pr_to_reg.get(pr)
            if not cod_reg:
                logger.warning("No region code for PR %s — skipping", pr)
                return None
            url = build_scrutini_url(date, sk, cod_reg, pr)
            data = await fetch_json(client, url, semaphore, delay)
            if data:
                return parse_scrutini_result(data, sk, pr)
            return None

        tasks = [
            fetch_scrutini(pr, sk)
            for sk in quesiti
            for pr in ALL_PR_CODES
        ]

        all_results = await asyncio.gather(*tasks)
        rows = [r for r in all_results if r is not None]

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
    parser.add_argument("--quesiti", nargs="+", default=["01"])
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
