import json

import frappe

ENTRY_DOCTYPE = "Information Table Entry"
LEGACY_FIELD = "info"
NEW_FIELD = "value"


def execute():
	"""v16 migration: move Information Table Entry values and sync mappings off the
	legacy `info` column onto `value`/`text`/`numeric_value`/`checkbox`.

	The v16 doctype restructuring replaces `info` with `value`. The doctype JSON of
	this app ships the new field names, but a site's LIVE sync configuration keeps
	writing `table_fieldname: "info"` into a column that no longer exists -> silent
	data loss. This patch migrates, in this order:

	1. leftover data: copy `info` -> `value` where `value` is still empty
	   (only if the legacy column still exists in the site DB),
	2. live config: rewrite `"table_fieldname": "info"` in every Selectline Table
	   Mapping JSON and every Sync Mapping Entry.child_row_fieldname.

	No-op on benches whose Information Table Entry doctype has no `value` field
	(pre-v16 structure).
	"""
	if not _target_doctype_present():
		print(f"  {ENTRY_DOCTYPE}: no `value` field in meta (pre-v16 doctype) - nothing to do")
		return

	data_migrated = _migrate_entry_values()
	config_migrated = _migrate_mapping_config() if _legacy_field_gone() else False
	if not _legacy_field_gone():
		print(f"  {ENTRY_DOCTYPE}: `info` still in meta - leaving sync config untouched")

	if data_migrated or config_migrated:
		frappe.clear_cache()
	frappe.db.commit()


def _target_doctype_present():
	if not frappe.db.table_exists(ENTRY_DOCTYPE):
		return False
	meta = frappe.get_meta(ENTRY_DOCTYPE, cached=False)
	return NEW_FIELD in {field.fieldname for field in meta.fields}


def _migrate_entry_values():
	condition = "`value` IS NULL AND `info` IS NOT NULL AND `info` != ''"
	if not _has_column(LEGACY_FIELD):
		return 0

	count = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{ENTRY_DOCTYPE}` WHERE {condition}")[0][0]
	if not count:
		return 0

	frappe.db.sql(f"UPDATE `tab{ENTRY_DOCTYPE}` SET `value` = `info` WHERE {condition}")
	print(f"  Migrated {count} {ENTRY_DOCTYPE} rows: `info` -> `value` (existing values kept)")
	return count


def _migrate_mapping_config():
	changed = 0

	entry_count = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabSync Mapping Entry` WHERE child_row_fieldname = %s", (LEGACY_FIELD,)
	)[0][0]
	if entry_count:
		frappe.db.sql(
			"UPDATE `tabSync Mapping Entry` SET child_row_fieldname = %s WHERE child_row_fieldname = %s",
			(NEW_FIELD, LEGACY_FIELD),
		)
		changed += entry_count
		print(f"  Updated {entry_count} Sync Mapping Entry rows: child_row_fieldname {LEGACY_FIELD} -> {NEW_FIELD}")

	for row in frappe.get_all(
		"Selectline Table Mapping",
		filters={"mapping": ("like", "%info%")},
		fields=["name", "mapping"],
	):
		try:
			data = json.loads(row.mapping or "")
		except (TypeError, ValueError):
			continue
		hits = _replace_legacy_field(data)
		if hits:
			frappe.db.set_value("Selectline Table Mapping", row.name, "mapping", json.dumps(data, indent=1))
			changed += hits
			print(f"  Updated mapping JSON {row.name}: {hits} table field(s) {LEGACY_FIELD} -> {NEW_FIELD}")

	return changed


def _replace_legacy_field(data):
	"""Recursively replace {"table_fieldname": "info"} with "value" in parsed mapping JSON."""
	hits = 0
	if isinstance(data, dict):
		for key, val in data.items():
			if key == "table_fieldname" and val == LEGACY_FIELD:
				data[key] = NEW_FIELD
				hits += 1
			else:
				hits += _replace_legacy_field(val)
	elif isinstance(data, list):
		for item in data:
			hits += _replace_legacy_field(item)
	return hits


def _legacy_field_gone():
	"""True when the legacy `info` field has disappeared from the doctype meta."""
	return not any(
		field.fieldname == LEGACY_FIELD
		for field in frappe.get_meta(ENTRY_DOCTYPE, cached=False).fields
	)


def _has_column(column):
	return bool(
		frappe.db.sql(
			"SELECT COUNT(*) FROM information_schema.COLUMNS "
			"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
			(f"tab{ENTRY_DOCTYPE}", column),
		)[0][0]
	)
