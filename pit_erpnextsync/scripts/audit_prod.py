import frappe
import json


def audit():
	print("=== SYNC INSTANCES ===")
	instances = frappe.get_all(
		"Sync Instance",
		fields=["name", "enabled", "repetition", "cron_expression", "import_batch_size"],
	)
	for inst in instances:
		print(f"  {inst.name}: enabled={inst.enabled} rep={inst.repetition} batch={inst.import_batch_size}")
		tm_rows = frappe.get_all(
			"Selectline Table Mapping",
			filters={"parent": inst.name, "parenttype": "Sync Instance"},
			fields=["type", "table_name", "primary_key", "timestamp_column_name"],
		)
		for tm in tm_rows:
			print(f"    type={tm.type} table={tm.table_name} pk={tm.primary_key} ts_col={tm.timestamp_column_name}")

	print("\n=== SYNC MAPPING STATS ===")
	total = frappe.db.count("Sync Mapping")
	enabled = frappe.db.count("Sync Mapping", {"enable": 1})
	print(f"  Total: {total}, Enabled: {enabled}, Disabled: {total - enabled}")

	print("\n=== MAPPINGS BY TYPE ===")
	by_type = frappe.db.sql(
		"""
		SELECT type, COUNT(*) as cnt,
		       SUM(CASE WHEN enable=1 THEN 1 ELSE 0 END) as enabled
		FROM `tabSync Mapping` GROUP BY type ORDER BY cnt DESC
		""",
		as_dict=True,
	)
	for r in by_type:
		print(f"  {r.type}: {r.cnt} total ({r.enabled} enabled)")

	print("\n=== CHILD ROW NAME ISSUES ===")
	null_crn = frappe.db.count(
		"Sync Mapping Entry",
		{"child_row_fieldname": ["is", "set"], "child_row_name": ["in", [None, ""]]},
	)
	print(f"  Entries with child_row_fieldname but NULL/empty child_row_name: {null_crn}")

	null_crd = frappe.db.count(
		"Sync Mapping Entry",
		{
			"child_row_fieldname": ["is", "set"],
			"child_row_name": ["is", "set"],
			"child_row_doctype": ["in", [None, ""]],
		},
	)
	print(f"  Entries with child_row_name but NULL/empty child_row_doctype: {null_crd}")

	print("\n=== ORPHANED CHILD REFERENCES ===")
	child_doctypes = frappe.db.sql_list(
		"""
		SELECT DISTINCT child_row_doctype
		FROM `tabSync Mapping Entry`
		WHERE child_row_doctype IS NOT NULL AND child_row_doctype != ''
		"""
	)
	for cdt in child_doctypes:
		if not frappe.db.exists("DocType", cdt):
			print(f"  WARNING: child_row_doctype '{cdt}' does not exist!")
			continue
		names = frappe.get_all(
			"Sync Mapping Entry",
			filters={"child_row_doctype": cdt, "child_row_name": ["is", "set"]},
			pluck="child_row_name",
			distinct=True,
		)
		if not names:
			continue
		existing = set(
			frappe.get_all(cdt, filters={"name": ["in", names]}, pluck="name")
		)
		orphaned = [n for n in names if n not in existing]
		if orphaned:
			print(f"  {cdt}: {len(orphaned)} orphaned names (out of {len(names)} total)")

	print("\n=== MERGED ENTRIES ===")
	merged = frappe.db.sql(
		"""
		SELECT mapping_doctype, fieldname, child_row_fieldname,
		       child_row_name, COUNT(DISTINCT selectline_column) as col_cnt,
		       GROUP_CONCAT(DISTINCT selectline_column) as cols
		FROM `tabSync Mapping Entry`
		WHERE child_row_fieldname IS NOT NULL AND child_row_fieldname != ''
		  AND child_row_name IS NOT NULL AND child_row_name != ''
		  AND selectline_column IS NOT NULL
		GROUP BY mapping_doctype, fieldname, child_row_name, child_row_fieldname
		HAVING col_cnt > 1
		LIMIT 30
		""",
		as_dict=True,
	)
	for m in merged:
		print(
			f"  {m.mapping_doctype}.{m.fieldname}.{m.child_row_fieldname} "
			f"child={m.child_row_name}: {m.col_cnt} sl_cols ({m.cols})"
		)
	if len(merged) == 30:
		total_merged = frappe.db.sql(
			"""
			SELECT COUNT(*) FROM (
			    SELECT child_row_name, child_row_fieldname, fieldname, mapping_doctype
			    FROM `tabSync Mapping Entry`
			    WHERE child_row_fieldname IS NOT NULL AND child_row_fieldname != ''
			      AND child_row_name IS NOT NULL AND child_row_name != ''
			      AND selectline_column IS NOT NULL
			    GROUP BY mapping_doctype, fieldname, child_row_name, child_row_fieldname
			    HAVING COUNT(DISTINCT selectline_column) > 1
			) t
			"""
		)[0][0]
		print(f"  ... showing 30 of {total_merged} total merged groups")
	elif not merged:
		print("  (none found)")

	print("\n=== EMPTY CHILD ROWS ===")
	SKIP = {
		"name", "parent", "parenttype", "parentfield", "idx",
		"creation", "modified", "modified_by", "owner", "docstatus",
		"_user_tags", "_comments", "_assign", "_liked_by",
		"lft", "rgt", "old_parent",
	}
	SKIP_TYPES = {"Section Break", "Column Break", "HTML", "Button", "Image", "Fold"}
	for cdt in child_doctypes:
		if not frappe.db.exists("DocType", cdt):
			continue
		meta = frappe.get_meta(cdt)
		data_fields = [
			f.fieldname
			for f in meta.fields
			if f.fieldname and f.fieldname not in SKIP and f.fieldtype not in SKIP_TYPES
		]
		if not data_fields:
			continue
		cond = " AND ".join([f"(`{fn}` IS NULL OR `{fn}` = '')" for fn in data_fields])
		cnt = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{cdt}` WHERE {cond}")[0][0]
		if cnt > 0:
			print(f"  {cdt}: {cnt} empty child rows")

	print("\n=== TIMESTAMP STATUS ===")
	no_ts = frappe.db.count("Sync Mapping", {"db_time_stamp": ["in", [None, ""]]})
	print(f"  Mappings with NULL/empty timestamp: {no_ts}")

	print("\n=== DONE ===")
