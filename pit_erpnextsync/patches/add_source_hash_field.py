import frappe


def execute():
	"""Add `source_hash` to Sync Mapping.

	The source ERP timestamp is a DATE without a time component, so changes made
	on the same day as the stored timestamp never bump it and were invisible to
	the update cycle. The bulk check now additionally compares a hash over all
	mapped source values (update.py:compute_source_hash) stored in this field.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	if not frappe.db.exists("Custom Field", {"dt": "Sync Mapping", "fieldname": "source_hash"}):
		create_custom_field(
			"Sync Mapping",
			{
				"fieldname": "source_hash",
				"label": "Source Hash",
				"fieldtype": "Data",
				"insert_after": "db_time_stamp",
				"read_only": 1,
				"no_copy": 1,
				"print_hide": 1,
			},
		)
