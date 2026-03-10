# PIT ERPNextSync - AI Agent Documentation

## Project Overview

**PIT ERPNextSync** is an ERPNext app that serves as a connector between **SelectLine** (a German ERP system) and **ERPNext**. It synchronizes data from SelectLine's SQL Server database into ERPNext.

## Architecture

### Core Components

#### DocTypes (Data Models)

| DocType | Purpose |
|---------|---------|
| `Sync Instance` | Database connection configuration and sync settings |
| `Sync Mapping` | Tracks relationships between SelectLine records and ERPNext documents |
| `Sync Mapping Entry` | Child table storing field-level mappings |
| `Selectline Table Mapping` | JSON-based table mapping definitions |
| `PIT ERPNextSync Settings` | Global application settings |

#### Main Scripts

| Script | Purpose |
|--------|---------|
| `controller.py` | Core database connection, mapping management, and utility functions |
| `data_import.py` | Initial data import from SelectLine to ERPNext |
| `update.py` | Updates existing records based on timestamp changes |
| `reconcile.py` | Reconciles mapping changes with current JSON definitions |
| `scheduler.py` | Automated sync scheduling (all/daily/hourly/weekly/monthly) |

### Key Features

- **Database Connection**: Uses `pymssql` to connect to SQL Server
- **JSON Mapping**: Flexible field mapping via JSON configuration files
- **Scheduled Sync**: Automated background jobs for regular synchronization
- **Field Variables**: Dynamic value resolution during import
- **Child Table Support**: Handles complex nested document structures
- **Reconciliation**: Detects and applies mapping definition changes

## Data Flow

```
1. Configure Sync Instance with database credentials
2. Load table mapping JSON (defines which tables/columns map to which DocTypes/fields)
3. Fetch data from SelectLine SQL Server
4. Create ERPNext documents based on mapping
5. Store mapping relationships for future updates
6. Scheduled updates check timestamps and sync changes
```

## Technical Stack

- **Framework**: Frappe/ERPNext (Python)
- **Database**: SQL Server (SelectLine) via pymssql
- **Scheduling**: Frappe background jobs
- **Code Quality**: Ruff linter, pre-commit hooks

## File Structure

```
pit_erpnextsync/
├── pit_erpnextsync/
│   ├── pit_erpnextsync/
│   │   ├── doctype/
│   │   │   ├── sync_instance/
│   │   │   ├── sync_mapping/
│   │   │   ├── sync_mapping_entry/
│   │   │   ├── selectline_table_mapping/
│   │   │   └── pit_erpnextsync_settings/
│   │   ├── page/
│   │   │   └── selectline_sync_dash/
│   │   └── workspace/
│   │       └── pit_erpnext_sync/
│   ├── scripts/
│   │   ├── controller.py
│   │   ├── data_import.py
│   │   ├── update.py
│   │   ├── reconcile.py
│   │   ├── scheduler.py
│   │   ├── utils.py
│   │   └── classes/
│   │       └── field_vars.py
│   ├── hooks.py
│   └── install.py
├── pyproject.toml
└── README.md
```

## Important Implementation Details

### Mapping ID Format
Selectline IDs follow the format: `<instance>:<table>:<primary_key>`

### Field Mapping Types
- `sl_column` - Direct column mapping from SelectLine
- `default` - Static default value
- `field_var` - Dynamic field variable
- `mapped_value` - Cross-reference to another mapping
- `table_fields` - Child table fields

### Scheduler Events
Configured in `hooks.py`:
- `all` - Every 4 minutes
- `daily` - Daily
- `hourly` - Hourly
- `weekly` - Weekly
- `monthly` - Monthly

### Error Handling
All scripts use centralized logging via `pit_erpnext.scripts.logger.make_log()`

## Dependencies

```toml
[project]
dependencies = [
    "pymssql>=2.2.0",
]
```

## Development Guidelines

1. **Code Style**: Uses Ruff with 110 character line length
2. **Type Hints**: Python 3.10+ type annotations throughout
3. **Error Handling**: Comprehensive try-except blocks with logging
4. **Background Jobs**: Long-running operations use Frappe's job queue
5. **Database Transactions**: Explicit commits after document operations

## Common Tasks

### Adding a New Field Mapping
1. Update the JSON mapping file
2. Run reconciliation to apply changes to existing records
3. New imports will automatically use the updated mapping

### Debugging Import Issues
1. Check logs in Error Log (filtered by app name)
2. Verify database connection with "Test Connection" button
3. Review mapping JSON validity
4. Check field requirements in mapping definition

### Running Manual Import
```python
from pit_erpnextsync.scripts.data_import import start_import
start_import(instance="Instance Name", top=100, types_str='["Customer"]')
```
