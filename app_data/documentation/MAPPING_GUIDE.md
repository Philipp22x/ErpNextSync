# JSON Mapping Documentation

## Overview

The JSON mapping defines how data from **any source ERP** (MSSQL or 4D based — e.g. SelectLine, ModernOffice) transforms into **ERPNext** documents. It's stored in the **Selectline Table Mapping** DocType within each Sync Instance.

This documentation explains all available keywords and how to use them to create your own mappings.

---

## Table of Contents

1. [Top-Level Structure](#top-level-structure)
2. [Document-Level Keywords](#document-level-keywords)
3. [Field-Level Keywords](#field-level-keywords)
4. [Value Sources](#value-sources)
5. [Child Tables](#child-tables)
6. [Post Field Variables](#post-field-variables)
7. [DocType Flags](#doctype-flags)
8. [Complete Examples](#complete-examples)
9. [Best Practices](#best-practices)

---

## Top-Level Structure

The mapping is a JSON array where each element represents one ERPNext DocType to create:

```json
[
  {
    "doctype": "Customer",
    "reqd": 1,
    "fields": [...],
    "post_field_vars": [...],
    "doctype_flags": [...]
  },
  {
    "doctype": "Address",
    "reqd": 0,
    "fields": [...]
  }
]
```

**Key concept**: You can create multiple related documents from a single source row. For example, one row might create both a Customer and their primary Address.

---

## Document-Level Keywords

| Keyword | Required | Type | Description |
|---------|----------|------|-------------|
| `doctype` | **Yes** | string | The ERPNext DocType to create (e.g., "Customer", "Item", "Address") |
| `reqd` | No | 0 or 1 | If `1`, the document is required. If creation fails, the entire import stops |
| `fields` | **Yes** | array | List of field mappings (see [Field-Level Keywords](#field-level-keywords)) |
| `post_field_vars` | No | array | Capture field values after creation for use in subsequent documents |
| `doctype_flags` | No | array | Special Frappe flags to set on the document |

### Example

```json
{
  "doctype": "Customer",
  "reqd": 1,
  "fields": [...]
}
```

---

## Field-Level Keywords

Each field object must specify an ERPNext `fieldname` and ONE value source. The following keywords are available at the field level:

| Keyword | Required | Type | Description |
|---------|----------|------|-------------|
| `fieldname` | **Yes** | string | The ERPNext field name to populate |
| `reqd` | No | 0, 1, or 2 | Required level: 0=optional, 1=skip doc if empty, 2=abort import if empty |
| `force_str_type` | No | 0 or 1 | If `1`, convert the value to string |
| `trim` | No | int | Max characters to keep. Truncates the value (as string) to this length. Useful for fields with max length constraints (e.g. Item Name max 140 chars). Alias: `trim_to`. |

### Value Source Keywords (use only one per field)

| Keyword | Description |
|---------|-------------|
| `sl_column` | Source column name to fetch value from |
| `alt_key` | Alternative column name if `sl_column` is empty/null |
| `default` | Static default value |
| `field_var` | Reference to a dynamic field variable |
| `mapped_value` | Cross-reference to another mapping's field value |
| `table_fields` | Child table field definitions (for Table-type fields) |

---

## Value Sources

### 1. Direct Column Mapping (`sl_column`)

Maps a source column directly to an ERPNext field.

```json
{
  "fieldname": "customer_name",
  "sl_column": "CompanyName",
  "alt_key": "Name2",
  "reqd": 1
}
```

**How it works:**
- Fetches the value from the `CompanyName` column in the source table
- If `CompanyName` is empty/null, tries the `Name2` column (alt_key)
- If both are empty and `reqd: 1`, skips this document
- If both are empty and `reqd: 2`, aborts the entire import

### 2. Alternative Key (`alt_key`)

Provides a fallback column when the primary column is empty.

```json
{
  "fieldname": "email_id",
  "sl_column": "Email",
  "alt_key": "Email2"
}
```

### 3. Static Default Value (`default`)

Use when you want a fixed value regardless of source data.

```json
{
  "fieldname": "customer_type",
  "default": "Company"
}
```

```json
{
  "fieldname": "country",
  "default": "Germany"
}
```

### 4. Dynamic Field Variable (`field_var`)

References a value captured earlier in the import process.

```json
{
  "fieldname": "territory",
  "field_var": "default_territory"
}
```

**Setting field variables:**
- Use `post_field_vars` to capture values after document creation
- Global settings in Sync Instance can also define field variables

### 5. Cross-Reference Mapping (`mapped_value`)

Looks up a value from another already-imported document.

```json
{
  "fieldname": "customer_primary_contact",
  "mapped_value": {
    "table_name": "CONTACTS",
    "sl_id": "ContactId",
    "doc_type": "Contact",
    "fieldname": "name"
  }
}
```

**How it works:**
1. Takes the value from the current row's `ContactId` column
2. Looks up the Sync Mapping for source table `CONTACTS` with that ID
3. Finds the related ERPNext `Contact` document
4. Gets the `name` field from that Contact
5. Sets it as the value for `customer_primary_contact`

**Use case:** Linking a Customer to their primary Contact that was imported separately.

---

## Child Tables

Child tables in ERPNext (like Contact's email list, Customer's addresses) require special handling.

### Simple Child Table (same row)

When child data is in the same source row:

```json
{
  "fieldname": "email_ids",
  "table_fields": [
    {
      "table_fieldname": "email_id",
      "sl_column": "Email",
      "reqd": 1
    },
    {
      "table_fieldname": "is_primary",
      "default": 1
    }
  ]
}
```

### Multiple Child Rows (different table)

When child data is in a separate table (e.g., multiple contacts per customer):

```json
{
  "fieldname": "contacts",
  "multiple_query": true,
  "multiple_query_table": "CONTACTS",
  "multiple_query_condition": "CustomerId = {sl_column:CustomerId}",
  "table_fields": [
    {
      "table_fieldname": "first_name",
      "sl_column": "FirstName"
    },
    {
      "table_fieldname": "last_name",
      "sl_column": "LastName"
    }
  ]
}
```

**Child Table Keywords:**

| Keyword | Description |
|---------|-------------|
| `table_fieldname` | The field name within the child table |
| `sl_column` | Source column (same as parent level) |
| `alt_key` | Alternative column |
| `default` | Static default |
| `field_var` | Field variable reference |
| `mapped_value` | Cross-reference |
| `reqd` | Required level |
| `force_str_type` | Force string conversion |
| `trim` | Max characters to keep (truncates value to this length) |

**Multiple Query Keywords:**

| Keyword | Description |
|---------|-------------|
| `multiple_query` | Set to `true` to enable separate child table query |
| `multiple_query_table` | The source table containing child rows |
| `multiple_query_condition` | SQL WHERE clause to filter child rows |
| `match_key_column` | Optional. Stable source column (e.g. `rowid__`) used to match child rows across updates. Stored as `source_row_key` on mapping entries. Enables structural sync during update: new source rows are created as child rows, removed source rows are deleted. Without it, matching falls back to the first `reqd` `sl_column` value (legacy behavior — breaks when that value itself changes). |

**Condition syntax:** Use `{sl_column:ColumnName}` to reference parent row values.

---

## Post Field Variables

Capture values from created documents to use in subsequent mappings within the same import.

```json
{
  "doctype": "Customer",
  "reqd": 1,
  "fields": [...],
  "post_field_vars": [
    {
      "var_name": "customer_id",
      "field_name": "name"
    },
    {
      "var_name": "customer_group",
      "field_name": "customer_group"
    }
  ]
}
```

| Keyword | Description |
|---------|-------------|
| `var_name` | Name to store the value under for later reference |
| `field_name` | ERPNext field to capture from the created document |

**Example workflow:**
1. Create Customer → capture `name` as `customer_id`
2. Create Address → use `field_var: "customer_id"` to link to Customer

---

## DocType Flags

Special Frappe document flags for advanced scenarios.

```json
{
  "doctype": "Customer",
  "fields": [...],
  "doctype_flags": [
    {"name_set": true},
    {"ignore_links": true}
  ]
}
```

Common flags:
- `name_set`: Indicates the document name is already set, don't auto-generate
- `ignore_links`: Skip link validation during insert (useful for circular references)

---

## Complete Examples

### Example 1: Simple Customer Import

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
      },
      {
        "fieldname": "territory",
        "field_var": "default_territory"
      },
      {
        "fieldname": "customer_group",
        "default": "Commercial"
      }
    ],
    "post_field_vars": [
      {
        "var_name": "erp_customer_id",
        "field_name": "name"
      }
    ]
  }
]
```

### Example 2: Customer with Address

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
    ],
    "post_field_vars": [
      {
        "var_name": "erp_customer_id",
        "field_name": "name"
      }
    ]
  },
  {
    "doctype": "Address",
    "reqd": 0,
    "fields": [
      {
        "fieldname": "address_title",
        "sl_column": "CompanyName"
      },
      {
        "fieldname": "address_line1",
        "sl_column": "Street",
        "reqd": 1
      },
      {
        "fieldname": "city",
        "sl_column": "City"
      },
      {
        "fieldname": "country",
        "default": "Germany"
      },
      {
        "fieldname": "links",
        "table_fields": [
          {
            "table_fieldname": "link_doctype",
            "default": "Customer"
          },
          {
            "table_fieldname": "link_name",
            "field_var": "erp_customer_id"
          }
        ]
      }
    ]
  }
]
```

### Example 3: Customer with Multiple Contacts

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
      }
    ],
    "post_field_vars": [
      {
        "var_name": "erp_customer_id",
        "field_name": "name"
      }
    ]
  },
  {
    "doctype": "Contact",
    "reqd": 0,
    "multiple_query": true,
    "multiple_query_table": "CONTACTS",
    "multiple_query_condition": "CustomerId = {sl_column:CustomerId}",
    "fields": [
      {
        "fieldname": "first_name",
        "sl_column": "FirstName"
      },
      {
        "fieldname": "last_name",
        "sl_column": "LastName"
      },
      {
        "fieldname": "email_ids",
        "table_fields": [
          {
            "table_fieldname": "email_id",
            "sl_column": "Email"
          },
          {
            "table_fieldname": "is_primary",
            "default": 1
          }
        ]
      },
      {
        "fieldname": "links",
        "table_fields": [
          {
            "table_fieldname": "link_doctype",
            "default": "Customer"
          },
          {
            "table_fieldname": "link_name",
            "field_var": "erp_customer_id"
          }
        ]
      }
    ]
  }
]
```

### Example 4: Item with Cross-Reference

```json
[
  {
    "doctype": "Item",
    "reqd": 1,
    "fields": [
      {
        "fieldname": "item_code",
        "sl_column": "ArticleNumber",
        "reqd": 1
      },
      {
        "fieldname": "item_name",
        "sl_column": "Description"
      },
      {
        "fieldname": "item_group",
        "mapped_value": {
          "table_name": "ARTICLE_GROUPS",
          "sl_id": "GroupId",
          "doc_type": "Item Group",
          "fieldname": "name"
        }
      },
      {
        "fieldname": "stock_uom",
        "default": "Nos"
      }
    ]
  }
]
```

---

## Value Resolution Priority

For each field, the system resolves the value in this order:

1. **Check `alt_key`** - If specified and has a value, use it
2. **Use `sl_column`** - Get value from the specified column
3. **Apply `mapped_value`** - If defined, lookup the referenced document
4. **Use `field_var`** - Get value from the variable store
5. **Use `default`** - Use the static default value
6. **Apply `force_str_type`** - Convert to string if flag is set

---

## Best Practices

### 1. Always Set Required Fields

Mark essential fields with `"reqd": 1` to prevent incomplete data:

```json
{
  "fieldname": "customer_name",
  "sl_column": "CompanyName",
  "reqd": 1
}
```

### 2. Use Post Field Variables for Linking

Capture document names to link related documents:

```json
{
  "post_field_vars": [
    {
      "var_name": "customer_id",
      "field_name": "name"
    }
  ]
}
```

### 3. Test with Small Batches

Before running large imports, test with a small subset:
- Use the `top` parameter in the import function
- Check the Error Log in ERPNext for issues

### 4. Handle Child Tables Properly

- Use simple `table_fields` when data is in the same row
- Use `multiple_query` when child data is in a separate table
- Always include the `links` child table for Address/Contact linking

### 5. Use Alternative Keys for Fallback Data

```json
{
  "fieldname": "email",
  "sl_column": "Email",
  "alt_key": "Email2"
}
```

### 6. Leverage Field Variables for Global Settings

Set common values in the Sync Instance's field variables:
- `default_territory`
- `default_customer_group`
- `default_company`

Then reference them in mappings:

```json
{
  "fieldname": "territory",
  "field_var": "default_territory"
}
```

### 7. Use Cross-References for Relationships

When you need to link to documents imported in other mappings:

```json
{
  "fieldname": "customer",
  "mapped_value": {
    "table_name": "ADDRESSES",
    "sl_id": "CustomerId",
    "doc_type": "Customer",
    "fieldname": "name"
  }
}
```

### 8. Debugging Tips

- Check **Error Log** in ERPNext (search for "pit_erpnextsync")
- Enable **Debug Mode** in Sync Instance for verbose logging
- Use **Test Connection** button to verify database connectivity
- Validate JSON syntax before saving (use a JSON validator)

---

## Troubleshooting

### Import fails with "Required field missing"

- Check that all fields with `"reqd": 1` have values
- Verify `sl_column` names match the source table exactly
- Consider adding `alt_key` for fallback values

### Documents not linking properly

- Ensure you're capturing the field in `post_field_vars`
- Verify the `field_var` name matches exactly
- Check that the linked document is created first (order matters in the JSON array)

### Child tables not populating

- For `multiple_query`, verify the condition syntax
- Ensure `multiple_query_table` exists and is accessible
- Check that `table_fieldname` matches the ERPNext child table field names

### Cross-reference returns null

- Verify the target mapping exists and was imported
- Check that `table_name` matches the source table
- Ensure `sl_id` column contains valid foreign keys

---

## Quick Reference Card

```json
{
  "doctype": "DocTypeName",
  "reqd": 1,
  "fields": [
    {
      "fieldname": "erp_field",
      "sl_column": "SL_Column",
      "alt_key": "Alt_Column",
      "reqd": 1,
      "force_str_type": 0,
      "trim": 140
    },
    {
      "fieldname": "erp_field2",
      "default": "static_value"
    },
    {
      "fieldname": "erp_field3",
      "field_var": "variable_name"
    },
    {
      "fieldname": "erp_field4",
      "mapped_value": {
        "table_name": "SL_TABLE",
        "sl_id": "ForeignKeyColumn",
        "doc_type": "TargetDocType",
        "fieldname": "target_field"
      }
    },
    {
      "fieldname": "child_table_field",
      "multiple_query": true,
      "multiple_query_table": "CHILD_TABLE",
      "multiple_query_condition": "ParentId = {sl_column:Id}",
      "table_fields": [
        {
          "table_fieldname": "child_field",
          "sl_column": "ChildColumn"
        }
      ]
    }
  ],
  "post_field_vars": [
    {
      "var_name": "var_name",
      "field_name": "erp_field_to_capture"
    }
  ]
}
```

---

## Related Documentation

- [README.md](README.md) - Project overview and installation
- [AGENTS.md](AGENTS.md) - Technical architecture and developer guide

---

*For support or questions, check the Error Log in ERPNext or contact your system administrator.*
