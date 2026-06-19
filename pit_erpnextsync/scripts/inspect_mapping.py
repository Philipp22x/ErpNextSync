import frappe
import json


def inspect():
	minst = frappe.get_all("Sync Instance", filters={"enabled": 1}, pluck="name")
	for inst_name in minst:
		inst = frappe.get_doc("Sync Instance", inst_name)
		for tm in inst.table_mapping:
			if tm.type != "Item":
				continue
			mj = json.loads(tm.mapping)
			for dt_def in mj:
				if dt_def.get("doctype") != "Item":
					continue
				for f in dt_def.get("fields", []):
					fn = f.get("fieldname", "")
					if fn not in ("barcodes", "uoms"):
						continue
					print("=== %s ===" % fn)
					print("  multiple_query:", f.get("multiple_query"))
					print("  mq_table:", f.get("multiple_query_table"))
					print("  mq_condition:", f.get("multiple_query_condition"))
					for tf in f.get("table_fields", []):
						print(
							"    %s: sl_col=%s reqd=%s"
							% (tf.get("table_fieldname"), tf.get("sl_column"), tf.get("reqd"))
						)
			return
