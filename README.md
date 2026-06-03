# ERPNextSync


**A Frappe/ERPNext app that synchronizes master data from legacy ERP systems into ERPNext.**

ERPNextSync connects directly to external databases (Microsoft SQL Server, 4D, and more), reads source records via configurable JSON mappings, and creates or updates the corresponding ERPNext documents automatically. It supports scheduled background sync, incremental timestamp-based updates, cross-reference resolution between related documents, and hook scripts for custom pre-/post-processing.

Designed to work with **any legacy ERP system** that exposes its data through a supported database protocol.

---

## Features

- **Dual database driver** -- connects to external databases via Microsoft SQL Server (`pymssql`) or 4D (`p4d`)
- **Declarative JSON mappings** -- define how source tables and columns map to ERPNext DocTypes and fields, with no Python required
- **Multiple value sources** -- direct column mapping, static defaults, dynamic field variables, and cross-reference lookups between mappings
- **Child table support** -- map child rows from the same record or from a related table via sub-queries
- **Incremental updates** -- timestamp-based change detection so only modified records are re-synced
- **Reconciliation** -- diff stored mappings against the current JSON definition and detect drift
- **Scheduler integration** -- configurable per-instance intervals (all / hourly / daily / weekly / monthly) with long-running background jobs
- **Hook scripts** -- attach Server Script hooks (before/after import, before/after update) to any Sync Instance
- **Dashboard page** -- a dedicated desk page for monitoring sync status

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | >= 3.10 |
| Frappe Framework | v15+ |
| ERPNext | v15+ (recommended) |
| `pit_erpnext` app | installed (provides shared logging utilities) |

The source ERP system must expose its database over the network via one of the supported protocols:

- **Microsoft SQL Server** (any edition, including Express)
- **4D Server** (via the 4D native protocol)

---

## Installation

Install the app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/<org>/pit_erpnextsync --branch develop
bench install-app pit_erpnextsync
bench migrate
```

The `pymssql` and `p4d` Python packages are installed automatically as declared dependencies.

---

## Quick Start

### 1. Create a Sync Instance

Navigate to **Search Bar > Sync Instance > + New** and fill in:

| Field | Description |
|-------|-------------|
| Instance Name | A human-readable label (e.g. "Legacy ERP Production") |
| Driver | `pymssql` (SQL Server) or `p4d` (4D) |
| Server / Port | Host address and port of the source database |
| User / Password | Database credentials |
| Database | Database name (MSSQL only) |

Click **Test Connection** to verify connectivity.

### 2. Add Table Mappings

In the **Table Mapping** child table on the Sync Instance, add one or more mapping entries. Each entry contains a JSON definition that maps a source database table to one or more ERPNext DocTypes.

Minimal example -- import customers:

```json
[
  {
    "doctype": "Customer",
    "reqd": 1,
    "fields": [
      {
        "fieldname": "customer_name",
        "sl_column": "CompanyName",
        "reqd": 1
      },
      {
        "fieldname": "customer_type",
        "default": "Company"
      }
    ]
  }
]
```

See the full **[Mapping Guide](app_data/documentation/MAPPING_GUIDE.md)** for all available keywords, child table handling, cross-references, and complete examples.

### 3. Run an Import

**From the UI:** Use the action buttons on the Sync Instance form.

**From bench console:**

```python
from pit_erpnextsync.scripts.data_import import start_import

start_import(
    instance="Legacy ERP Production",
    top=100,                        # limit rows (omit for all)
    types_str='["Customer"]'        # restrict to specific DocTypes
)
```

### 4. Enable Scheduled Sync

On the Sync Instance, check **Enable Scheduler** and set the **Repetition** interval. The Frappe scheduler will then automatically run imports and incremental updates at the configured frequency.

---

## Architecture

### How Sync Works

```
Source ERP DB                  ERPNextSync                    ERPNext
  (MSSQL/4D)                                                    (MariaDB)
      |                              |                              |
      |  1. Connect (pymssql/p4d)    |                              |
      |<-----------------------------|                              |
      |                              |                              |
      |  2. SELECT rows              |                              |
      |<-----------------------------|                              |
      |                              |                              |
      |  3. Map via JSON definitions |                              |
      |                              |                              |
      |                              |  4. frappe.get_doc / insert   |
      |                              |----------------------------->|
      |                              |                              |
      |                              |  5. Store Sync Mapping       |
      |                              |----------------------------->|
```

1. **Connect** to the source database using the configured driver
2. **Fetch** rows from the source table (with optional `TOP n` limit)
3. **Transform** each row according to the JSON mapping definition
4. **Insert or update** the corresponding ERPNext document
5. **Track** the relationship in a Sync Mapping record for future updates and reconciliation

### DocTypes

| DocType | Type | Purpose |
|---------|------|---------|
| **Sync Instance** | Regular | Database connection config, table mappings, scheduler settings |
| **Table Mapping** | Child of Sync Instance | JSON mapping definition for one source table |
| **Sync Instance Hooks** | Child of Sync Instance | Server Script hooks (before/after import/update) |
| **Sync Mapping** | Regular | Tracks one source record to ERPNext document relationship |
| **Sync Mapping Entry** | Child of Sync Mapping | Field-level mapping audit trail |
| **ERPNextSync Settings** | Single | Global settings (e.g. cascade-delete toggle) |

### Mapping ID Format

Every synced record is identified by a composite key:

```
<instance_name>:<table_name>:<primary_key>
```

Spaces are replaced with underscores. This ID is stored in the Sync Mapping and used for incremental updates and cross-reference resolution.

### Field Mapping Types

| Type | Keyword | Description |
|------|---------|-------------|
| Direct column | `sl_column` | Value from a source database column (with optional `alt_key` fallback) |
| Static default | `default` | A fixed literal value |
| Field variable | `field_var` | A dynamic variable set earlier in the import chain via `post_field_vars` |
| Cross-reference | `mapped_value` | Lookup a field from another already-imported document |
| Redis context | `set_redis` / `get_redis` | Store and retrieve values within the same row's processing chain |
| Value transform | `value_map` | Map source values to ERPNext values (e.g. country codes to country names) |
| Child table | `table_fields` | Define rows for an ERPNext child table |
| Sub-query | `multiple_query` | Fetch child rows from a separate source table |

See the full **[Keyword Reference](#json-mapping-reference)** below for all available options.

### Scripts

All core logic lives in `pit_erpnextsync/scripts/`:

| Module | Responsibility |
|--------|----------------|
| `controller.py` | Database connections, mapping CRUD, SQL builders, queue helpers |
| `data_import.py` | Initial bulk import from source database into ERPNext |
| `update.py` | Timestamp-based incremental updates |
| `reconcile.py` | Diff current JSON mapping against stored Sync Mapping entries |
| `scheduler.py` | Frappe scheduler entry points (all/daily/hourly/weekly/monthly) |
| `custom_scripts.py` | Ad-hoc bulk operations (e.g. create Website Items) |
| `classes/field_vars.py` | `FieldVars` class -- dynamic field variable resolution |

### Scheduler Flow

Each scheduled cycle executes two phases per enabled instance:

1. **`start_import()`** -- import new records that don't yet have a Sync Mapping
2. **`run_bulk_update()`** -- detect and apply changes to previously imported records

Long-running jobs are enqueued via `frappe.enqueue(queue="long", timeout=600)`.

---

## JSON Mapping Reference

The mapping system is the core of ERPNextSync. Each table mapping entry is a JSON array that describes how to read one source table and create one or more ERPNext documents per row.

For a narrative walkthrough with worked examples, see the **[Mapping Guide](app_data/documentation/MAPPING_GUIDE.md)**.

For a comprehensive example that uses **every available keyword**, see **[`complete_example_mapping.json`](app_data/import_json_templates/complete_example_mapping.json)**.

### Top-Level Keywords (per table mapping entry)

These are set on the outermost object -- one per source table:

| Keyword | Required | Type | Description |
|---------|----------|------|-------------|
| `idx` | Yes | int | Execution order (processed in ascending order) |
| `type` | Yes | string | Human-readable label for this mapping (e.g. `"Customer"`, `"AdditionalContacts"`) |
| `doc_type` | Yes | string | Primary ERPNext DocType this mapping produces |
| `table_name` | Yes | string | Source database table name (may include alias, e.g. `"CONTACTS C1"`) |
| `primary_key` | Yes | string | Column that uniquely identifies each row in the source table |
| `query_filter` | No | string | SQL `WHERE` clause to filter source rows (e.g. `"IS_ACTIVE = 1"`) |
| `order_by` | No | string | SQL `ORDER BY` column(s) |
| `timestamp_column_name` | No | string | Column used for incremental update detection |
| `timestamp_column_type` | No | string | Set to `"rowversion"` for MSSQL rowversion columns |
| `mapping` | Yes | array | Array of document definitions (see below) |

### Document-Level Keywords

Each object inside `mapping` defines one ERPNext document to create per source row:

| Keyword | Required | Type | Description |
|---------|----------|------|-------------|
| `doctype` | Yes | string | ERPNext DocType to create (e.g. `"Customer"`, `"Address"`) |
| `reqd` | No | 0 or 1 | If `1`, the entire import for this row stops if creation fails |
| `fields` | Yes | array | Field mapping definitions (see below) |
| `post_field_vars` | No | array | Capture field values after creation for use in subsequent documents |
| `doctype_flags` | No | array | Frappe document flags to set before insert |

**`post_field_vars`** entries:

| Key | Description |
|-----|-------------|
| `var_name` | Name to store the value under (referenced later via `field_var`) |
| `field_name` | ERPNext field to capture from the newly created document |

**`doctype_flags`** common values:

| Flag | Description |
|------|-------------|
| `name_set` | Document name is pre-set, skip auto-naming |
| `ignore_validate` | Skip validation hooks on insert |
| `ignore_links` | Skip link validation (useful for circular references) |
| `create_website_item` | Set to `0` to suppress automatic Website Item creation |

### Field-Level Keywords

Each object inside `fields` maps one source value to one ERPNext field:

| Keyword | Required | Type | Description |
|---------|----------|------|-------------|
| `fieldname` | Yes | string | Target ERPNext field name |
| `sl_column` | No | string | Source database column (can also be a SQL expression with alias) |
| `alt_key` | No | string | Fallback column if `sl_column` returns empty/null |
| `default` | No | any | Static literal value |
| `field_var` | No | string | Reference to a value captured by `post_field_vars` |
| `mapped_value` | No | object | Cross-reference lookup to another mapping (see below) |
| `table_fields` | No | array | Child table field definitions (see below) |
| `reqd` | No | 0, 1, 2 | `0` = optional, `1` = skip this document if empty, `2` = abort entire import |
| `force_str_type` | No | 0 or 1 | Convert the resolved value to string |
| `value_map` | No | object | Key-value map to transform source values to ERPNext values |
| `value_map_default` | No | string | Fallback value when `value_map` has no matching key |
| `set_redis` | No | string | Store the resolved value in Redis context under this key (for use by `get_redis` in later documents) |
| `get_redis` | No | string | Retrieve a value previously stored via `set_redis` |
| `is_phone_no` | No | 0 or 1 | Apply phone number formatting to the value |
| `deduplicate_on` | No | string | Column name to deduplicate child rows on (used with `multiple_query`) |

> **Note:** Use exactly one value source per field: `sl_column`, `default`, `field_var`, `mapped_value`, or `get_redis`.

### `mapped_value` Object

Cross-references another already-imported mapping to resolve a linked document:

| Key | Description |
|-----|-------------|
| `table_name` | Source table name of the referenced mapping |
| `sl_id` | Column in the *current* row whose value is the foreign key |
| `doc_type` | ERPNext DocType of the referenced document |
| `fieldname` | Field to retrieve from the referenced ERPNext document (usually `"name"`) |

### Child Table Keywords (`table_fields`)

When `fieldname` points to an ERPNext child table (e.g. `email_ids`, `links`, `barcodes`), use `table_fields` to define the child row columns. Each entry supports the same value-source keywords as regular fields:

| Keyword | Description |
|---------|-------------|
| `table_fieldname` | Field name within the child table row |
| `sl_column` | Source column |
| `alt_key` | Fallback column |
| `default` | Static value |
| `field_var` | Variable reference |
| `mapped_value` | Cross-reference |
| `get_redis` | Redis context value |
| `reqd` | Required level |
| `force_str_type` | String conversion |
| `value_map` | Value transformation |
| `value_map_default` | Fallback for value_map |
| `is_phone_no` | Phone formatting |
| `set_redis` | Store value in Redis context |

**Repeating the same `fieldname`** appends additional child rows (e.g. multiple emails, multiple barcodes).

### Multiple Query (child rows from a separate table)

When child data lives in a different source table, add these keywords at the field level alongside `table_fields`:

| Keyword | Type | Description |
|---------|------|-------------|
| `multiple_query` | 1 or true | Enable sub-query for this child table |
| `multiple_query_table` | string | Source table for child rows (may include JOINs) |
| `multiple_query_condition` | string | SQL `WHERE` clause; use `{ColumnName}` to reference parent row values |
| `deduplicate_on` | string | Remove duplicate child rows by this column |

### Quick Reference

```json
{
  "idx": 1,
  "type": "Customer",
  "doc_type": "Customer",
  "table_name": "CUSTOMERS",
  "primary_key": "CUSTOMER_ID",
  "timestamp_column_name": "LAST_MODIFIED",
  "query_filter": "IS_ACTIVE = 1",
  "order_by": "CUSTOMER_ID",
  "mapping": [
    {
      "doctype": "Customer",
      "reqd": 1,
      "doctype_flags": [{ "name_set": 1, "ignore_validate": 1 }],
      "post_field_vars": [
        { "var_name": "erp_customer_id", "field_name": "name" }
      ],
      "fields": [
        { "fieldname": "name", "sl_column": "CUST_NO", "reqd": 1, "set_redis": "erp_cust" },
        { "fieldname": "customer_name", "sl_column": "COMPANY", "alt_key": "NAME", "reqd": 1 },
        { "fieldname": "customer_type", "default": "Company" },
        { "fieldname": "territory", "field_var": "default_territory" },
        { "fieldname": "tax_category", "sl_column": "COUNTRY",
          "value_map": { "AT": "Domestic", "DE": "EU" }, "value_map_default": "Export" },
        { "fieldname": "custom_legacy_id", "sl_column": "CUSTOMER_ID", "force_str_type": 1 },
        { "fieldname": "item_group", "mapped_value": {
            "table_name": "GROUPS", "sl_id": "GroupId",
            "doc_type": "Item Group", "fieldname": "name"
        }}
      ]
    },
    {
      "doctype": "Address",
      "fields": [
        { "fieldname": "address_line1", "sl_column": "STREET" },
        { "fieldname": "links", "table_fields": [
            { "table_fieldname": "link_doctype", "default": "Customer" },
            { "table_fieldname": "link_name", "get_redis": "erp_cust", "force_str_type": 1 }
        ]}
      ]
    },
    {
      "doctype": "Contact",
      "fields": [
        { "fieldname": "first_name", "sl_column": "CONTACT_FIRST" },
        { "fieldname": "phone_nos", "table_fields": [
            { "table_fieldname": "phone", "sl_column": "PHONE", "is_phone_no": 1 },
            { "table_fieldname": "is_primary_phone", "default": 1 }
        ]},
        { "fieldname": "links", "table_fields": [
            { "table_fieldname": "link_doctype", "default": "Customer" },
            { "table_fieldname": "link_name", "field_var": "erp_customer_id" }
        ]}
      ]
    }
  ]
}
```

---

## Configuration

### Global Settings

Navigate to **ERPNextSync Settings** (single DocType) to configure:

- Cascade-delete behavior when Sync Mappings are removed
- Other global defaults

### Per-Instance Settings

Each **Sync Instance** can be configured independently:

- Database connection (driver, host, port, credentials)
- Table mappings (one or more JSON definitions)
- Scheduler repetition interval
- Field variables (key-value pairs available to all mappings)
- Hook scripts (custom logic before/after import and update)
- Amount of data rows to process per run

---

## Troubleshooting

### Connection Issues

1. Click **Test Connection** on the Sync Instance form
2. Verify the database server is reachable from the ERPNext host
3. Check firewall rules for the configured port (default: 1433 for MSSQL)
4. Confirm the database user has `SELECT` permissions on the required tables

### Import Failures

1. Check the **Error Log** DocType in ERPNext (filter by `pit_erpnextsync`)
2. Verify the JSON mapping syntax is valid
3. Ensure all `sl_column` names match the actual source database column names (case-sensitive)
4. Check that mandatory ERPNext fields are covered in the mapping
5. Test with a small batch first using the `top` parameter

### Documents Not Linking

- Ensure the parent document is listed **before** the child in the JSON array
- Verify `post_field_vars` captures the correct field
- Check that `field_var` names match exactly between producer and consumer

### Incremental Updates Not Running

- Confirm the Sync Instance has **Enable Scheduler** checked
- Check that the **Repetition** interval matches the Frappe scheduler frequency
- Review Scheduled Job Logs for errors
- Verify the source table has a reliable timestamp column for change detection

---

## Development

### Project Structure

```
pit_erpnextsync/
  pit_erpnextsync/
    config/                    # App configuration
    hooks.py                   # Frappe hooks (scheduler, install, etc.)
    install.py                 # Post-install setup
    modules.txt               # Frappe module registration
    patches.txt               # Database migration patches
    public/                   # Static assets (JS, CSS)
    scripts/                  # Core sync logic
      controller.py           # DB connections, mapping CRUD, SQL builders
      data_import.py          # Bulk import
      update.py               # Incremental updates
      reconcile.py            # Mapping reconciliation
      scheduler.py            # Scheduler entry points
      custom_scripts.py       # Ad-hoc operations
      classes/
        field_vars.py         # Dynamic field variable resolution
    templates/                # Web templates
    pit_erpnextsync/
      doctype/                # DocType definitions
        sync_instance/
        sync_mapping/
        sync_mapping_entry/
        table_mapping/
        sync_instance_hooks/
        pit_erpnextsync_settings/
      page/
        sync_dashboard/ # Dashboard page
      workspace/              # Desk workspace definitions
app_data/
  documentation/
    MAPPING_GUIDE.md          # Full mapping reference
  import_json_templates/      # Example mapping JSON files
```

### Setup

```bash
# Clone and install
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/<org>/pit_erpnextsync --branch develop
bench install-app pit_erpnextsync

# Enable pre-commit hooks
cd apps/pit_erpnextsync
pre-commit install
```

### Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

- **Line length:** 110 characters
- **Target:** Python 3.10+
- **Quote style:** double quotes
- **Indentation:** tabs

Run manually:

```bash
# Full pre-commit suite (ruff, eslint, prettier)
pre-commit run --all-files

# Ruff only
ruff check .       # lint
ruff format .      # format
```

Pre-commit hooks run automatically on `git commit`.

### Dependencies

| Package | Purpose |
|---------|---------|
| `pymssql >= 2.2.0` | Microsoft SQL Server driver |
| `p4d >= 1.8` | 4D database driver |
| `pit_erpnext` | Parent app (provides `pit_erpnext.scripts.logger`) |

### Logging

All scripts use the shared logging utility from `pit_erpnext`:

```python
from pit_erpnext.scripts.logger import make_log

make_log("Import completed", "INFO", "pit_erpnextsync")
make_log("Something failed", "ERROR", "pit_erpnextsync", with_traceback=True)
```

Log entries appear in the ERPNext **Error Log** DocType.

### Example Mapping Templates

The `app_data/import_json_templates/` directory contains mapping examples that can serve as starting points for new integrations:

| File | Description |
|------|-------------|
| **[`complete_example_mapping.json`](app_data/import_json_templates/complete_example_mapping.json)** | Comprehensive reference example that demonstrates **every available keyword** across 12 table mappings (Item Groups, Payment Terms, Customers with Address/Contact chains, Suppliers, Item Attributes with `multiple_query`, Items with variants/barcodes/UOM conversions, Pricing Rules, Leads with `post_field_vars`/`field_var`, and more). Start here to understand the full capabilities. |
| `cobra_default_mapping.json` | Customers, Contacts, Leads, and Addresses from a CRM system (Cobra) |
| `lang_officeno1_mapping.json` | Full integration: Payment Terms, Customers, Suppliers, Item Groups, Items with barcodes/UOMs/supplier items, Item Prices, Pricing Rules, Delivery Addresses, Stock Bins |
| `mwlaser_mapping.json` | Customers with email preferences (SQL subqueries), CRM Addresses/Contacts via `mapped_value`, Items with barcodes |
| `default_mapping_hellatex_V2.json` | Item Attributes with `multiple_query`, variant parent/child Items with `deduplicate_on` |
| `default_mapping873f88.json` | Customers with CRM addresses, Items with barcodes |
| `steinmassl_customer_mapping.json` | Payment Terms, Customers with `set_redis`/`get_redis` linking, CRM Addresses via `mapped_value` |

---

## License

This project is licensed under the [MIT License](license.txt).

---

## Authors

The ERPNextSync Contributors
