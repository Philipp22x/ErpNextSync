import frappe


def check_24627():
	item_name = "24627"
	print(f"=== ITEM {item_name} ===")
	exists = frappe.db.exists("Item", item_name)
	print(f"Exists: {exists}")

	if exists:
		doc = frappe.get_doc("Item", item_name)
		print(f"UOMs: {len(doc.uoms)}")
		for u in doc.uoms:
			print(f"  uom={u.uom} conv={u.conversion_factor}")
		print(f"Barcodes: {len(doc.barcodes)}")
		for b in doc.barcodes:
			print(f"  barcode={b.barcode} type={b.barcode_type}")

	print("\n=== SYNC MAPPING ===")
	mapping = frappe.db.get_value("Sync Mapping", {"selectline_id": ["like", "%24627"], "type": "Item"}, "name")
	print(f"Mapping: {mapping}")

	if mapping:
		entries = frappe.get_all("Sync Mapping Entry",
			filters={"parent": mapping},
			fields=["fieldname", "child_row_fieldname", "child_row_name", "child_row_doctype", "selectline_column"])
		print(f"Total entries: {len(entries)}")
		child_entries = [e for e in entries if e.child_row_fieldname]
		parent_entries = [e for e in entries if not e.child_row_fieldname]
		print(f"Parent entries: {len(parent_entries)}")
		print(f"Child entries: {len(child_entries)}")
		for e in child_entries:
			print(f"  {e.fieldname}.{e.child_row_fieldname}: sl_col={e.selectline_column} child={e.child_row_name} dt={e.child_row_doctype}")

	print("\n=== RECONCILE LOGS ===")
	logs = frappe.db.sql("""
		SELECT name, method, error
		FROM `tabError Log`
		WHERE error LIKE '%24627%'
		ORDER BY creation DESC LIMIT 5
	""", as_dict=True)
	for l in logs:
		print(f"  {l.name}: {l.method}")

	print("\n=== DONE ===")
