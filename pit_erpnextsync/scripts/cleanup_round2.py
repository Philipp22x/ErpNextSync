"""Cleanup round 2 — empty rows + merged child entries. Paste into bench console."""


def cleanup_round2():
	import frappe

	DOCTYPES = ["Customer", "Supplier", "Address", "Contact", "Item"]
	SKIP_FIELDS = {
		"name", "parent", "parenttype", "parentfield", "idx",
		"creation", "modified", "modified_by", "owner", "docstatus",
		"_user_tags", "_comments", "_assign", "_liked_by",
		"lft", "rgt", "old_parent",
	}
	SKIP_FIELDTYPES = {"Section Break", "Column Break", "HTML", "Button", "Image", "Fold"}

	# --- Step 1: Delete empty child rows (created by partial update) ---
	total_deleted = 0
	for dt in DOCTYPES:
		meta = frappe.get_meta(dt)
		for tf in [f for f in meta.fields if f.fieldtype == "Table"]:
			child_dt = tf.options
			if not child_dt:
				continue
			child_meta = frappe.get_meta(child_dt)
			data_fields = [
				f.fieldname
				for f in child_meta.fields
				if f.fieldname
				and f.fieldname not in SKIP_FIELDS
				and f.fieldtype not in SKIP_FIELDTYPES
			]
			if not data_fields:
				continue
			cond = " AND ".join([f"`{fn}` IS NULL OR `{fn}` = ''" for fn in data_fields])
			empty = frappe.db.sql(f"SELECT name FROM `tab{child_dt}` WHERE {cond}", as_dict=True)
			if not empty:
				continue
			names = [r["name"] for r in empty]
			ph = ", ".join(["%s"] * len(names))
			# Clear mapping refs
			frappe.db.sql(
				f"UPDATE `tabSync Mapping Entry` SET child_row_name = NULL, child_row_doctype = NULL WHERE child_row_name IN ({ph})",
				tuple(names),
			)
			# Delete empty rows
			frappe.db.sql(f"DELETE FROM `tab{child_dt}` WHERE name IN ({ph})", tuple(names))
			total_deleted += len(names)
			print(f"{dt} / {child_dt}: deleted {len(names)} empty rows")

	print(f"\nStep 1 done: {total_deleted} empty rows removed")

	# --- Step 2: Fix merged child entries ---
	# When child_row_name was NULL, ensure_child_row_exists re-linked ALL entries
	# for the same fieldname to one child row. This merged entries that should
	# be on separate child rows (e.g. multiple conversion_factor entries with
	# different sl_cols like GEBINDE_1, GEBINDE_2 on the same UOM row).
	#
	# Fix: find groups where multiple entries share the same child_row_name but
	# have different selectline_column for the same child_row_fieldname. Clear
	# child_row_name for all but the first in each group so the update creates
	# separate child rows.

	merged_fixed = 0
	for dt in DOCTYPES:
		# Find all Sync Mapping Entries for this doctype's child tables
		entries = frappe.db.sql(
			"""
			SELECT name, parent, docname, fieldname, child_row_fieldname,
			       child_row_name, selectline_column
			FROM `tabSync Mapping Entry`
			WHERE docname IN (SELECT name FROM `tab{dt}`)
			  AND child_row_name IS NOT NULL
			  AND child_row_name != ''
			  AND child_row_fieldname IS NOT NULL
			ORDER BY parent, docname, fieldname, child_row_name, child_row_fieldname
			""".format(dt=dt),
			as_dict=True,
		)

		# Group by (parent, docname, fieldname, child_row_name, child_row_fieldname)
		# and find groups with multiple different selectline_column values
		from collections import defaultdict

		groups = defaultdict(list)
		for e in entries:
			key = (e["parent"], e["docname"], e["fieldname"], e["child_row_name"], e["child_row_fieldname"])
			groups[key].append(e)

		for key, group in groups.items():
			sl_cols = set(e["selectline_column"] for e in group if e["selectline_column"])
			if len(sl_cols) <= 1:
				continue  # Not merged

			# Keep the first entry, clear child_row_name for the rest
			parent_name, docname, fieldname, child_row_name, child_row_fieldname = key
			for e in group[1:]:
				frappe.db.set_value("Sync Mapping Entry", e["name"], "child_row_name", None, update_modified=False)
				frappe.db.set_value("Sync Mapping Entry", e["name"], "child_row_doctype", None, update_modified=False)
				merged_fixed += 1

			print(
				f"  {dt} {docname}: {fieldname}.{child_row_fieldname} "
				f"un-merged {len(group) - 1} entries from child {child_row_name} "
				f"(sl_cols: {sl_cols})"
			)

	print(f"\nStep 2 done: {merged_fixed} merged entries un-linked")
	frappe.db.commit()
	print(f"\nAll done! Deleted {total_deleted} empty rows, un-merged {merged_fixed} entries.")
	print("Run update sync now — fixed code will create correct separate child rows.")


cleanup_round2()
