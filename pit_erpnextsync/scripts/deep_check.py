import frappe


def deep_check():
	item = "24627"

	print("=== 1. ACTUAL CHILD ROWS IN DB ===")
	uoms = frappe.db.sql(f"SELECT name, uom, conversion_factor FROM `tabUOM Conversion Detail` WHERE parent = '{item}'", as_dict=True)
	print(f"UOMs ({len(uoms)}):")
	for u in uoms:
		print(f"  {u.name}: uom={u.uom} conv={u.conversion_factor}")

	barcodes = frappe.db.sql(f"SELECT name, barcode, barcode_type FROM `tabItem Barcode` WHERE parent = '{item}'", as_dict=True)
	print(f"Barcodes ({len(barcodes)}):")
	for b in barcodes:
		print(f"  {b.name}: barcode='{b.barcode}' type={b.barcode_type}")

	print("\n=== 2. SYNC MAPPING CHILD ENTRIES ===")
	mapping = frappe.db.get_value("Sync Mapping", {"selectline_id": ["like", f"%{item}"], "type": "Item"}, "name")
	print(f"Mapping: {mapping}")
	if mapping:
		entries = frappe.get_all("Sync Mapping Entry",
			filters={"parent": mapping, "child_row_fieldname": ["is", "set"]},
			fields=["fieldname", "child_row_fieldname", "child_row_name", "child_row_doctype", "selectline_column"],
			order_by="fieldname, child_row_name")
		for e in entries:
			exists = ""
			if e.child_row_name and e.child_row_doctype:
				exists = "EXISTS" if frappe.db.exists(e.child_row_doctype, e.child_row_name) else "MISSING"
			print(f"  {e.fieldname}.{e.child_row_fieldname}: sl_col={e.selectline_column} child={e.child_row_name} -> {exists}")

	print("\n=== 3. SOURCE DATA FROM MAPPING JSON ===")
	# What columns does the mapping JSON define for barcodes/uoms?
	import json
	inst = frappe.get_doc("Sync Instance", "officeno1_migration")
	for tm in inst.table_mapping:
		if tm.type != "Item":
			continue
		mj = json.loads(tm.mapping)
		for dt_def in mj:
			if dt_def.get("doctype") != "Item":
				continue
			for f in dt_def.get("fields", []):
				fn = f.get("fieldname")
				if fn in ("barcodes", "uoms"):
					tf_list = f.get("table_fields", [])
					sl_cols = [tf.get("sl_column") for tf in tf_list if tf.get("sl_column")]
					defaults = [(tf.get("table_fieldname"), tf.get("default")) for tf in tf_list if tf.get("default") is not None]
					reqd = [tf.get("table_fieldname") for tf in tf_list if tf.get("reqd")]
					print(f"  {fn}: sl_cols={sl_cols} defaults={defaults} reqd_fields={reqd}")

	print("\n=== 4. WHAT 4D RETURNS FOR THIS ITEM ===")
	from pit_erpnextsync.scripts import controller
	schema = frappe.db.get_value("Sync Instance", "officeno1_migration", "schema") or ""
	cols = ["BARCODE", "EAN", "EAN2", "EAN3", "MENGENEINHEIT", "GEWICHT_BRUTTO",
	        "LAENGE", "BREITE", "HOEHE", "M3ME", "GEBINDE_1", "GEBINDE_2",
	        "VERPACKUNGSMENGE", "UEBERVERPACKUNGMENGE"]
	sql = controller.make_sql_string_single_row(
		instance="officeno1_migration",
		table_name="Artikel",
		columns=cols,
		primary_key_col="ARTIKELNR",
		primary_key_val=item,
		schema=schema
	)
	data = controller.fetch_data(instance="officeno1_migration", sql=sql)
	if data:
		print(f"  Fetched {len(data)} rows")
		for key, val in data[0].items():
			print(f"    {key} = '{val}' (type: {type(val).__name__})")
	else:
		print(f"  NO DATA")

	print("\n=== DONE ===")
