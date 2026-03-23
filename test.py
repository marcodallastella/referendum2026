import httpx
import json

URL = "https://eleapi.interno.gov.it/siel/PX/scrutiniFI/DE/20260322/TE/09/SK/01/RE/11/PR/003/CM/0080"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://elezioni.interno.gov.it",
    "referer": "https://elezioni.interno.gov.it/",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
}

def main():
    print("Calling API...")

    with httpx.Client(timeout=10, headers=HEADERS) as client:
        response = client.get(URL)

        print(f"Status code: {response.status_code}")
        response.raise_for_status()

        data = response.json()

    print("\n=== FULL RESPONSE (truncated) ===")
    print(json.dumps(data, indent=2)[:2000])

    print("\n=== TOP-LEVEL KEYS ===")
    for key in data.keys():
        print("-", key)


if __name__ == "__main__":
    main()