# Deprecated Scripts

The following scripts have been consolidated into `flashcard_processor.py`:

- `apply_curated_edits.py`
- `repair_and_qa_yaml.py`
- `normalize_and_qa_cards.py`
- `seed_scaffolds.py`

## Migration Guide

### Old Commands -> New Commands

| Old Command | New Command |
|-------------|-------------|
| `python normalize_and_qa_cards.py` | `python flashcard_processor.py normalize --apply` |
| `python repair_and_qa_yaml.py` | `python flashcard_processor.py repair --apply` |
| `python apply_curated_edits.py` | `python flashcard_processor.py edit --apply` |
| `python seed_scaffolds.py "Card Name"` | `python flashcard_processor.py scaffold "Card Name"` |

### Complete Processing Pipeline

To run the complete processing pipeline (equivalent to running all old scripts in sequence):

```bash
python flashcard_processor.py process --apply
```

### New Features

1. **Unified Interface**: Single script for all flashcard processing tasks
2. **Safer Operations**: Dry-run mode by default, use `--apply` to make changes
3. **Better Error Handling**: More detailed error messages and validation
4. **Automatic Backups**: Creates backups before making changes
5. **Consistent Output**: Standardized logging and reporting
