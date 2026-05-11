# PIT ERPNextSync

ERPNext app that syncs data from **SelectLine** (German ERP) into ERPNext. Connects to SelectLine's SQL Server (or 4D) database.

## Documentation
- **Mapping reference**: `app_data/documentation/MAPPING_GUIDE.md`

## Architecture

### Dual-database driver
Supports two backends: **pymssql** (MSSQL) and **p4d** (4D). SQL generation, column quoting, and fetch logic differ per driver. See `controller.py:db_connect()` for the dispatcher.

### Key DocTypes
| DocType | Purpose |
|---------|---------|
| `Sync Instance` | DB connection config, table mapping JSON, scheduler settings |
| `Sync Mapping` | Tracks one SelectLine record → ERPNext document relationship |
| `Sync Mapping Entry` | Child table of Sync Mapping; field-level mapping rows |
| `Selectline Table Mapping` | Child table of Sync Instance; JSON-based table/field mapping definitions |
| `PIT ERPNextSync Settings` | Single doctype (global settings, e.g. cascade-delete toggle) |
| `Sync Instance Hooks` | Child table of Sync Instance; Server Script hooks (before/after import/update) |

### Scripts (all in `pit_erpnextsync/scripts/`)
| Script | Role |
|--------|------|
| `controller.py` | Core: DB connections, mapping CRUD, ID format, SQL builders, queue helpers |
| `data_import.py` | Initial import from SelectLine → ERPNext |
| `update.py` | Timestamp-based incremental updates |
| `reconcile.py` | Diffs current JSON mapping against stored Sync Mapping entries |
| `scheduler.py` | Entry points for all/daily/hourly/weekly/monthly cron |
| `custom_scripts.py` | Ad-hoc bulk operations (e.g. create Website Items) |
| `field_vars.py` | Simple container for dynamic field variable resolution |
| `utils.py` | **Empty** — placeholder, do not use |

### Scheduler flow
Each cycle: `start_import()` → `run_bulk_update()`. Only enabled instances matching the repetition interval are processed. Long-running jobs use `frappe.enqueue(queue="long", timeout=600)`.

### Mapping ID format
```
<instance_name>:<table_name>:<primary_key>
```
Underscores replace spaces. Used to cross-reference SelectLine records to ERPNext documents.

### Field mapping types
- `sl_column` — direct column from SelectLine
- `default` — static literal value
- `field_var` — dynamic variable (resolved at runtime)
- `mapped_value` — cross-reference to another mapping's field
- `table_fields` — child table fields

## Development

### Lint & format
```bash
pre-commit run --all-files    # ruff linter + import sort + formatter, eslint, prettier
# or just:
ruff check .                  # linter only
ruff format .                 # formatter only
```
No test suite exists (all `test_*.py` files are empty stubs). There is no `npm run test` or equivalent.

### Style
- Ruff: 110 char line length, Python 3.10+, double quotes, **tab indentation**
- Pre-commit hooks run on `git commit`

### Dependencies
- `pymssql>=2.2.0` (MSSQL driver)
- `p4d>=1.8` (4D driver)
- Implicit: `pit_erpnext` (parent app, provides `pit_erpnext.scripts.logger`)

### Logging
All scripts use `pit_erpnext.scripts.logger.make_log(message, level, APP_NAME, with_traceback=...)`.

### Nested module structure
The inner Python module mirrors the app name: `pit_erpnextsync/pit_erpnextsync/pit_erpnextsync/`. Most imports are `from pit_erpnextsync.scripts.controller import ...`.

### Code editing policy
ALL code edits MUST be done in this local project only. Never modify code directly on remote servers via SSH, even if SSH access is available.

## Common Tasks

### Run a manual import
```python
from pit_erpnextsync.scripts.data_import import start_import
start_import(instance="Instance Name", top=100, types_str='["Customer"]')
```

### Debug import issues
1. Check Error Log doctype (filter by app name)
2. "Test Connection" button on Sync Instance form
3. Verify mapping JSON validity
4. Check field requirements in mapping definition
