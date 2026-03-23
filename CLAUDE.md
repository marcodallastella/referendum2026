# Claude Code Instructions — Referendum 2026

## Project

Data journalism platform for Italian referendum 2026 election results. Scrapes `eleapi.interno.gov.it`
(undocumented live API), processes data, publishes results in near real-time via GitHub Actions and a
public-facing website.

See `AGENTS.md` for the full specialist agent team definition and usage instructions.

## Agent Team

This project uses a team of 6 specialist agents defined in `AGENTS.md`:

| Agent | Role |
|---|---|
| `scraper-engineer` | Scraper robustness, data pipeline, API resilience |
| `devops-engineer` | GitHub Actions, CI/CD, deploy pipeline |
| `frontend-developer` | Frontend performance, UX, accessibility |
| `data-viz-designer` | Charts, maps, visual hierarchy, color system |
| `editorial-advisor` | Narrative, methodology, attribution, tone |
| `security-reviewer` | Dependencies, secrets, XSS, supply chain |

To activate an agent, ask: *"Act as the [agent-name] from AGENTS.md and..."*

## API Reference

- **Base:** `https://eleapi.interno.gov.it/siel/PX`
- **Referrer required:** `https://elezioni.interno.gov.it/`
- **Pattern:** `{base}/{endpoint}/DE/{date}/TE/09/SK/{quesito}/PR/{province}[/CM/{comune}]`
- **Endpoints:** `votantiFI` (turnout, live), `scrutiniFI` (results, post-close)
- **Gotchas:**
  - `perc` field uses comma decimal separator (`"31,64"`) — parse carefully
  - Province codes (PR) are alphabetical by name, not ISTAT codes
  - `ente_p: null` = invalid combo, treat as 404
  - Response may contain `Error` key on HTTP 200

## Key Files

- `scraper.py` — async Python scraper (httpx + asyncio)
- `output/referendum_results.csv` — scraped turnout data (39,475 rows)
- `output/raw/` — raw JSON per province per quesito
- `Elenco-comuni-italiani.xlsx` — ISTAT municipality metadata for enrichment

## Working Principles

- **Accuracy over speed** — but aim for both
- **Never assume API stability** — it's undocumented and can change mid-election
- **Surface uncertainty explicitly** — partial data must be labeled as such
- **Election night is a hard deadline** — distinguish "must fix now" from "improve later"
- **Non-technical audience** — journalists, citizens, politicians on their phones
- **Data integrity is paramount** — a wrong number is a reputational disaster
