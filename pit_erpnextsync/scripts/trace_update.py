import frappe
import json

from pit_erpnextsync.scripts import controller


def trace_update():
	mapping_name = "8gkc0dvds1"
	instance = "officeno1_migration"

	mapping_doc = frappe.get_doc("Sync Mapping", mapping_name)
	mapping_table_data = controller.get_mapping_table_data(mapping_name=mapping_name)

	# Load mapping JSON
	instance_doc = frappe.get_doc("Sync Instance", instance)
	mapping_json = []
	for tm_row in instance_doc.table_mapping:
		if tm_row.type == mapping_doc.type:
			mapping_json = json.loads(tm_row.mapping)
			break

	# Build mq_sl_columns
	mq_sl_columns = set()
	for mapped_doctype in mapping_json:
		for field in mapped_doctype.get("fields", []):
			if field.get("multiple_query") and field.get("table_fields"):
				for tf in field.get("table_fields", []):
					if tf.get("sl_column"):
						mq_sl_columns.add(tf["sl_column"])
	print(f"mq_sl_columns: {mq_sl_columns}")

	# Build valid_columns
	valid_columns = [
		d["selectline_column"]
		for d in mapping_table_data
		if d.get("selectline_column")
		and not d["selectline_column"].startswith("_")
		and d["selectline_column"] not in mq_sl_columns
	]
	unique_cols = list(dict.fromkeys(valid_columns))
	print(f"\nvalid_columns ({len(unique_cols)}):")
	for c in unique_cols:
		print(f"  {c}")

	has_barcode = "BARCODE" in unique_cols
	has_ean = "EAN" in unique_cols
	print(f"\nBARCODE in columns: {has_barcode}")
	print(f"EAN in columns: {has_ean}")

	# Fetch data
	schema = frappe.db.get_value("Sync Instance", instance, "schema") or ""
	id_data = {"primary_key": "24627"}
	columns = unique_cols[:]

	ts_col = None
	for tm_row in instance_doc.table_mapping:
		if tm_row.type == mapping_doc.type:
			ts_col = tm_row.timestamp_column_name
			break
	if ts_col:
		columns.append(ts_col)

	sql = controller.make_sql_string_single_row(
		instance=instance,
		table_name="Artikel",
		columns=columns,
		primary_key_col=mapping_doc.primary_key_column,
		primary_key_val="24627",
		schema=schema
	)
	print(f"\nSQL columns count: {len(columns)}")
	fetched_data = controller.fetch_data(instance=instance, sql=sql)
	if fetched_data:
		print(f"Fetched keys: {list(fetched_data[0].keys())}")
		print(f"BARCODE = {repr(fetched_data[0].get('BARCODE'))}")
		print(f"EAN = {repr(fetched_data[0].get('EAN'))}")
	else:
		print("NO DATA FETCHED")
		return

	# Trace barcode entries
	print("\n=== TRACING BARCODE ENTRIES ===")
	for row in mapping_doc.mapping_table:
		if row.fieldname != "barcodes":
			continue
		col_key = row.selectline_column
		if " AS " in col_key or " as " in col_key:
			col_key = col_key.rsplit(" AS ", 1)[-1].rsplit(" as ", 1)[-1].strip()

		field_value = fetched_data[0].get(col_key)
		print(f"\n  Entry: {row.fieldname}.{row.child_row_fieldname} sl_col={row.selectline_column}")
		print(f"    col_key = {repr(col_key)}")
		print(f"    field_value = {repr(field_value)} (type: {type(field_value).__name__})")
		print(f"    child_row_name = {row.child_row_name}")
		print(f"    child_row_doctype = {row.child_row_doctype}")
		if field_value is None or field_value == "":
			print(f"    -> WOULD SKIP (None or empty)")
		else:
			print(f"    -> WOULD SET barcode = {repr(field_value)}")

	print("\n=== DONE ===")
