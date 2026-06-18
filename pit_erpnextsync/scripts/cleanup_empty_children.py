"""Cleanup empty child rows — paste into bench console."""
import frappe


def cleanup_empty_children():
	DOCTYPES = ["Customer", "Supplier", "Address", "Contact", "Item"]
	SKIP_FIELDS = {
		"name", "parent", "parenttype", "parentfield", "idx",
		"creation", "modified", "modified_by", "owner", "docstatus",
		"_user_tags", "_comments", "_assign", "_liked_by",
		"lft", "rgt", "old_parent",
	}
	SKIP_FIELDTYPES = {"Section Break", "Column Break", "HTML", "Button", "Image", "Fold"}
	has_sync = frappe.db.exists("DocType", "Sync Mapping Entry")
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
			if has_sync:
				frappe.db.sql(
					f"UPDATE `tabSync Mapping Entry` SET child_row_name = NULL, child_row_doctype = NULL WHERE child_row_name IN ({ph})",
					tuple(names),
				)
			frappe.db.sql(f"DELETE FROM `tab{child_dt}` WHERE name IN ({ph})", tuple(names))
			total_deleted += len(names)
			print(f"{dt} / {child_dt}: removed {len(names)} empty rows")

	frappe.db.commit()
	print(f"\nDone! {total_deleted} empty child rows removed. Run update sync next.")


cleanup_empty_children()
