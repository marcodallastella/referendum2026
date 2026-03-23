#!/usr/bin/env python3
"""
Scraper for Italian referendum 2026 results from Ministero dell'Interno API.

Uses the undocumented API at eleapi.interno.gov.it that powers elezioni.interno.gov.it.

Endpoints discovered:
  - votantiFI: Turnout/affluence data at province level (lists all comuni)
  - votantiFIZ: Turnout at comune level (includes sezione breakdown)
  - scrutiniFI: Results data at province level (not live until polls close)
  - scrutiniCI: Results at another aggregation level (not live until polls close)
  - scrutiniSI: Results at yet another level (not live until polls close)

URL pattern:
  {base}/siel/PX/{endpoint}/DE/{date}/TE/09/SK/{quesito}/PR/{provincia}
  {base}/siel/PX/{endpoint}/DE/{date}/TE/09/SK/{quesito}/PR/{provincia}/CM/{comune}

Province codes (PR) are alphabetical by province name (001=Agrigento, ..., 115=Sulcis Iglesiente).
Comune codes (CM) are the API's internal numbering (NOT ISTAT progressivi).
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
TIPO_ELEZIONE = "09"  # referendum

HEADERS = {
    "Origin": "https://elezioni.interno.gov.it",
    "Referer": "https://elezioni.interno.gov.it/",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
}

# API province codes (PR) mapped to ISTAT province codes.
# Discovered empirically: PR codes are alphabetical by province name.
# fmt: off
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
# fmt: on

ALL_PR_CODES = sorted(PR_TO_ISTAT.keys())


def load_istat_metadata(xlsx_path: str) -> dict:
    """Load province and region names from the ISTAT Excel file.

    Returns dict: istat_prov_code -> {regione, regione_code, provincia}
    """
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    meta = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        prov_code = row[2]
        if prov_code not in meta:
            meta[prov_code] = {
                "regione_code": row[0],
                "regione": row[10],
                "provincia": row[11],
            }
    wb.close()
    return meta


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore,
    delay: float,
    retries: int = 3,
) -> dict | None:
    """Fetch JSON from the API with retries and rate limiting."""
    for attempt in range(retries):
        async with semaphore:
            try:
                resp = await client.get(url, timeout=15)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                if "Error" in data:
                    logger.debug("API error for %s: %s", url, data["Error"].get("desc"))
                    return None
                # Check for null ente_p (invalid PR/CM combo)
                if data.get("enti", {}).get("ente_p") is None:
                    return None
                await asyncio.sleep(delay)
                return data
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                wait = (2**attempt) * 0.5
                logger.warning("Attempt %d failed for %s: %s (retry in %.1fs)", attempt + 1, url, e, wait)
                await asyncio.sleep(wait)
            except Exception as e:
                logger.error("Unexpected error for %s: %s", url, e)
                return None
    logger.error("All %d retries failed for %s", retries, url)
    return None


def build_url(endpoint: str, date: str, sk: str, pr: str, cm: str | None = None) -> str:
    """Build an API URL."""
    url = f"{API_BASE}/{endpoint}/DE/{date}/TE/{TIPO_ELEZIONE}/SK/{sk}/PR/{pr}"
    if cm is not None:
        url += f"/CM/{cm}"
    return url


def parse_affluence_province(data: dict, pr_code: str, sk: str) -> list[dict]:
    """Parse a province-level votantiFI response into per-comune rows."""
    rows = []
    ente_p = data["enti"]["ente_p"]
    provincia_name = ente_p["desc"]
    provincia_cod = ente_p["cod"]
    cod_reg = ente_p["com"][0]["cod_reg"] if ente_p.get("com") else None

    for comune_data in data["enti"].get("enti_f", []):
        row = {
            "pr_code": pr_code,
            "provincia_api_name": provincia_name,
            "provincia_api_cod": provincia_cod,
            "cod_reg": cod_reg,
            "cm_code": f"{comune_data['cod']:04d}",
            "comune_name": comune_data["desc"],
            "comune_cod": comune_data["cod"],
            "quesito": int(sk),
            "ele_m": comune_data.get("ele_m"),
            "ele_f": comune_data.get("ele_f"),
            "ele_t": comune_data.get("ele_t"),
            "tipo_tras": comune_data.get("tipo_tras"),
        }

        # Extract turnout data from each comunicazione (time slot)
        for com_vot in comune_data.get("com_vot") or []:
            com_num = com_vot["com"]
            row[f"com{com_num}_dt"] = com_vot.get("dt_com")
            row[f"com{com_num}_enti_p"] = com_vot.get("enti_p")
            row[f"com{com_num}_enti_t"] = com_vot.get("enti_t")
            row[f"com{com_num}_perc"] = com_vot.get("perc")
            row[f"com{com_num}_vot_m"] = com_vot.get("vot_m")
            row[f"com{com_num}_vot_f"] = com_vot.get("vot_f")
            row[f"com{com_num}_vot_t"] = com_vot.get("vot_t")

        rows.append(row)

    return rows


def parse_results_province(data: dict, pr_code: str, sk: str) -> list[dict]:
    """Parse a province-level scrutiniFI response into per-comune rows.

    The exact response structure will be determined when results become available.
    This is a best-effort parser based on the expected structure.
    """
    rows = []
    ente_p = data["enti"]["ente_p"]
    provincia_name = ente_p["desc"]
    cod_reg = ente_p["com"][0]["cod_reg"] if ente_p.get("com") else None

    for comune_data in data["enti"].get("enti_f", []):
        row = {
            "pr_code": pr_code,
            "provincia_api_name": provincia_name,
            "cod_reg": cod_reg,
            "cm_code": f"{comune_data['cod']:04d}",
            "comune_name": comune_data["desc"],
            "comune_cod": comune_data["cod"],
            "quesito": int(sk),
        }
        # Include all fields from the response - we don't know the exact structure yet
        for key, value in comune_data.items():
            if key not in ("desc", "cod", "com_vot", "tipo"):
                row[f"scr_{key}"] = value

        # Parse nested vote data if present
        for com_vot in comune_data.get("com_vot") or []:
            for key, value in com_vot.items():
                row[f"scr_{key}"] = value

        rows.append(row)

    return rows


async def scrape_mode(
    client: httpx.AsyncClient,
    endpoint: str,
    parser,
    date: str,
    quesiti: list[str],
    semaphore: asyncio.Semaphore,
    delay: float,
    raw_dir: Path,
) -> list[dict]:
    """Scrape all provinces × quesiti for a given endpoint using true async concurrency."""

    async def fetch_one(pr: str, sk: str) -> tuple[str, str, dict | None]:
        url = build_url(endpoint, date, sk, pr)
        data = await fetch_json(client, url, semaphore, delay)
        return pr, sk, data

    # Launch all requests concurrently (bounded by semaphore)
    tasks = [fetch_one(pr, sk) for sk in quesiti for pr in ALL_PR_CODES]
    total = len(tasks)
    logger.info("[%s] Launching %d requests (concurrency=%d)...", endpoint, total, semaphore._value)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_rows = []
    failed = 0
    errors = 0

    for result in results:
        if isinstance(result, Exception):
            errors += 1
            if errors <= 3:
                logger.error("[%s] Task exception: %s", endpoint, result)
            continue

        pr, sk, data = result
        if data is not None:
            raw_path = raw_dir / f"{endpoint}_SK{sk}_PR{pr}.json"
            raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            rows = parser(data, pr, sk)
            all_rows.extend(rows)
        else:
            failed += 1
            if failed <= 5:
                logger.warning("[%s] No data for PR/%s SK/%s", endpoint, pr, sk)

    ok = total - failed - errors
    logger.info("[%s] Done: %d OK, %d no-data, %d errors", endpoint, ok, failed, errors)
    return all_rows


async def scrape_all(
    mode: str,
    date: str,
    quesiti: list[str],
    output_dir: Path,
    delay: float,
    concurrency: int,
):
    """Main scraping orchestrator."""
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(concurrency)
    timestamp = datetime.now(timezone.utc).isoformat()

    # Load ISTAT metadata if available
    istat_meta = {}
    istat_path = Path("Elenco-comuni-italiani.xlsx")
    if istat_path.exists():
        logger.info("Loading ISTAT metadata from %s", istat_path)
        istat_meta = load_istat_metadata(str(istat_path))
    else:
        logger.warning("ISTAT file not found at %s - province/region names will use API values only", istat_path)

    async with httpx.AsyncClient(headers=HEADERS, http2=False) as client:
        affluence_rows = []
        results_rows = []

        if mode in ("affluence", "both"):
            logger.info("Fetching affluence data for %d provinces × %d quesiti...", len(ALL_PR_CODES), len(quesiti))
            affluence_rows = await scrape_mode(
                client, "votantiFI", parse_affluence_province, date, quesiti, semaphore, delay, raw_dir
            )
            logger.info("Affluence: %d rows collected", len(affluence_rows))

        if mode in ("results", "both"):
            logger.info("Fetching results data (scrutiniFI)...")
            results_rows = await scrape_mode(
                client, "scrutiniFI", parse_results_province, date, quesiti, semaphore, delay, raw_dir
            )
            if results_rows:
                logger.info("Results: %d rows collected", len(results_rows))
            else:
                logger.info("Results: no data available yet (polls may still be open)")

    # Build DataFrames and enrich with ISTAT metadata
    all_dfs = []

    if affluence_rows:
        df_aff = pd.DataFrame(affluence_rows)
        df_aff["data_type"] = "affluence"
        all_dfs.append(df_aff)

    if results_rows:
        df_res = pd.DataFrame(results_rows)
        df_res["data_type"] = "results"
        all_dfs.append(df_res)

    if not all_dfs:
        logger.error("No data collected!")
        return

    df = pd.concat(all_dfs, ignore_index=True)

    # Enrich with ISTAT metadata
    if istat_meta:
        istat_prov_codes = {pr: istat for pr, istat in PR_TO_ISTAT.items()}

        def get_meta(pr_code, field):
            istat = istat_prov_codes.get(pr_code, "")
            return istat_meta.get(istat, {}).get(field, "")

        df["istat_prov_code"] = df["pr_code"].map(lambda x: istat_prov_codes.get(x, ""))
        df["regione_code"] = df["pr_code"].map(lambda x: get_meta(x, "regione_code"))
        df["regione_name"] = df["pr_code"].map(lambda x: get_meta(x, "regione"))
        df["provincia_name"] = df["pr_code"].map(lambda x: get_meta(x, "provincia"))

    df["fetched_at"] = timestamp

    # Reorder columns: geo info first, then quesito, then data
    geo_cols = [
        "regione_code", "regione_name", "istat_prov_code", "provincia_name",
        "pr_code", "provincia_api_name", "cm_code", "comune_name", "comune_cod",
    ]
    meta_cols = ["quesito", "data_type", "fetched_at"]
    existing_geo = [c for c in geo_cols if c in df.columns]
    existing_meta = [c for c in meta_cols if c in df.columns]
    other_cols = [c for c in df.columns if c not in existing_geo + existing_meta]
    df = df[existing_geo + existing_meta + other_cols]

    # Save CSV
    csv_path = output_dir / "referendum_results.csv"
    df.to_csv(csv_path, index=False)
    logger.info("Saved %d rows to %s", len(df), csv_path)

    # Also save a summary
    summary = {
        "timestamp": timestamp,
        "mode": mode,
        "quesiti": quesiti,
        "provinces_scraped": len(ALL_PR_CODES),
        "total_rows": len(df),
        "unique_comuni": df["comune_name"].nunique() if "comune_name" in df.columns else 0,
    }
    summary_path = output_dir / "scrape_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    logger.info("Summary: %s", json.dumps(summary))


def main():
    parser = argparse.ArgumentParser(
        description="Scraper for Italian referendum 2026 results (Ministero dell'Interno API)"
    )
    parser.add_argument(
        "--mode",
        choices=["affluence", "results", "both"],
        default="affluence",
        help="What to fetch: affluence (turnout), results (scrutini), or both (default: affluence)",
    )
    parser.add_argument(
        "--date",
        default=DEFAULT_DATE,
        help="Election date in YYYYMMDD format (default: 20260322)",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory for CSV and raw JSON (default: output)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay between API requests in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent API requests (default: 5)",
    )
    parser.add_argument(
        "--quesiti",
        nargs="+",
        default=["01", "02", "03", "04", "05"],
        help="Quesito numbers to scrape (default: 01 02 03 04 05)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    # Setup logging - suppress httpx request noise
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(
        scrape_all(
            mode=args.mode,
            date=args.date,
            quesiti=args.quesiti,
            output_dir=output_dir,
            delay=args.delay,
            concurrency=args.concurrency,
        )
    )


if __name__ == "__main__":
    main()
