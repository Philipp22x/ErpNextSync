import frappe


def execute():
	"""Add `child_hash` to Sync Mapping.

	The child key set (`source_row_key`) proves WHICH child rows exist, but not
	what is IN them: a changed value inside an existing row (e.g. a transaction
	line switched to a different article) leaves the parent timestamp, the parent
	hash and the child key set untouched, so the document counted as unchanged
	and the ERP child row kept the old value forever.

	`child_hash` stores a fingerprint over all mapped child values
	(update.py:compute_child_fingerprint / combine_child_fingerprints); both
	change checks (bulk_check_type_changes and detect_child_row_changes) compare
	it and update_mapping() writes it back.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	if not frappe.db.exists("Custom Field", {"dt": "Sync Mapping", "fieldname": "child_hash"}):
		create_custom_field(
			"Sync Mapping",
			{
				"fieldname": "child_hash",
				"label": "Child Hash",
				"fieldtype": "Data",
				"insert_after": "source_hash",
				"read_only": 1,
				"no_copy": 1,
				"print_hide": 1,
			},
		)
