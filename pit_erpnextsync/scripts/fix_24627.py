import frappe
import json
from pit_erpnextsync.scripts import controller
from pit_erpnextsync.scripts.reconcile import reconcile_single_mapping


def fix_24627():
	mapping_name = "8gkc0dvds1"

	print("=== BEFORE: CHILD ENTRIES ===")
	entries = frappe.db.sql(
		"SELECT name, fieldname, child_row_fieldname, child_row_name, child_row_doctype, selectline_column "
		"FROM `tabSync Mapping Entry` WHERE parent = %s AND child_row_fieldname IS NOT NULL",
		mapping_name, as_dict=True
	)
	stale = 0
	for e in entries:
		exists = "NULL"
		if e.child_row_name and e.child_row_doctype:
			exists = "EXISTS" if frappe.db.exists(e.child_row_doctype, e.child_row_name) else "MISSING"
		if exists == "MISSING":
			stale += 1
		print(f"  {e.fieldname}.{e.child_row_fieldname} sl={e.selectline_column} child={e.child_row_name} -> {exists}")

	print(f"\nStale entries: {stale}")
	print(f"Total child entries before: {len(entries)}")

	print("\n=== RUNNING RECONCILE FOR THIS MAPPING ===")
	result = reconcile_single_mapping(
		instance="officeno1_migration",
		mapping_name=mapping_name,
		dry_run=False
	)
	print(f"Result: {result}")

	print("\n=== AFTER: CHILD ENTRIES ===")
	entries_after = frappe.db.sql(
		"SELECT name, fieldname, child_row_fieldname, child_row_name, child_row_doctype, selectline_column "
		"FROM `tabSync Mapping Entry` WHERE parent = %s AND child_row_fieldname IS NOT NULL",
		mapping_name, as_dict=True
	)
	for e in entries_after:
		exists = "NULL"
		if e.child_row_name and e.child_row_doctype:
			exists = "EXISTS" if frappe.db.exists(e.child_row_doctype, e.child_row_name) else "MISSING"
		print(f"  {e.fieldname}.{e.child_row_fieldname} sl={e.selectline_column} child={e.child_row_name} -> {exists}")

	print(f"\nTotal child entries after: {len(entries_after)}")

	print("\n=== ACTUAL CHILD ROWS ===")
	uoms = frappe.db.sql(
		"SELECT name, uom, conversion_factor FROM `tabUOM Conversion Detail` WHERE parent = '24627'",
		as_dict=True
	)
	print(f"UOMs: {len(uoms)}")
	for u in uoms:
		print(f"  {u.name}: uom={u.uom} conv={u.conversion_factor}")

	barcodes = frappe.db.sql(
		"SELECT name, barcode, barcode_type FROM `tabItem Barcode` WHERE parent = '24627'",
		as_dict=True
	)
	print(f"Barcodes: {len(barcodes)}")
	for b in barcodes:
		print(f"  {b.name}: barcode={b.barcode} type={b.barcode_type}")

	print("\n=== DONE ===")
