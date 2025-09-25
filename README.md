# Windsurf Flashcard QA Workflow

This repository houses the flashcard quality assurance tooling for the JD workflow. Use the `flashcard_workflow.py` helper to run policy-compliant checks and generate reports.

## Running checks

Validate one or more flashcard directories by pointing the workflow at the YAML files you want to inspect. The command writes both JSON and Markdown summaries to `reports/` and prints a coloured console summary showing any blocking errors.

```
python scripts/flashcard_workflow.py check "jd/LAWS50025 - Torts/*.yml" --policy jd/policy/cards_policy.yml --strict
python scripts/flashcard_workflow.py check jd/cards_yaml/*.yml --dry-run
```

* `--policy` points to the consolidated policy file (defaults to `jd/policy/cards_policy.yml`).
* `--strict` exits with a non-zero status when any card fails validation.
* `--dry-run` ensures no backups are written; use this when trialling new material.

Reports are saved to `reports/flashcard_check.json` and `reports/flashcard_check.md`. Backups (when not using `--dry-run`) are rotated under `./backups/` with only the ten most recent runs retained.

## Tests

Run the automated coverage with:

```
python -m pytest -q
```
