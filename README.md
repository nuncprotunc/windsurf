# Windsurf Flashcard QA & Pinpoint Verifier

This repo houses tooling for flashcard quality assurance and a legal pinpoint verification pipeline.

## Installation
```bash
pip install -r requirements.txt

Running unit tests (default, offline)

Network/OpenAI suites are skipped by default via pytest markers.

pytest -q


To include the optional network/OpenAI scenarios:

pytest -q -m "network or openai"

Flashcard QA workflow

Validate one or more flashcard directories. The command writes JSON and Markdown summaries to reports/ and prints a coloured console summary showing any blocking errors.

python scripts/flashcard_workflow.py check "jd/LAWS50025 - Torts/*.yml" --policy jd/policy/cards_policy.yml --strict
python scripts/flashcard_workflow.py check jd/cards_yaml/*.yml --dry-run


--policy points to the consolidated policy file (defaults to jd/policy/cards_policy.yml).

--strict exits with a non-zero status when any card fails validation.

--dry-run ensures no backups are written; use this when trialling new material.

Reports are saved to reports/flashcard_check.json and reports/flashcard_check.md. Backups (when not using --dry-run) are rotated under ./backups/ with only the ten most recent runs retained.

Pinpoint verifier CLI
Offline mode (no network required)
python bin/pinpoint.py \
  --case "Rootes v Shelton" \
  --citation "(1966) 116 CLR 383" \
  --para "[12]" \
  --prop "Volenti requires acceptance of the risk" \
  --query "Rootes v Shelton volenti" \
  --source-file tests/fixtures/rootes.html

Online mode (requires egress)
python bin/pinpoint.py \
  --query "Rootes v Shelton volenti" \
  --case "Rootes v Shelton" \
  --citation "(1966) 116 CLR 383" \
  --para "[12]" \
  --prop "Volenti requires acceptance of the risk"

OpenAI demo

app_verify.py shows the OpenAI-backed verification path.

pip install openai
export OPENAI_API_KEY=...   # or set in your shell/CI secrets
python app_verify.py


