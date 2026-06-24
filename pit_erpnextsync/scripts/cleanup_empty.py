import frappe


def cleanup():
	DOCTYPES = ["Customer", "Supplier", "Address", "Contact", "Item"]
	SKIP = {"name","parent","parenttype","parentfield","idx","creation","modified","modified_by","owner","docstatus","_user_tags","_comments","_assign","_liked_by","lft","rgt","old_parent"}
	SKIP_TYPES = {"Section Break","Column Break","HTML","Button","Image","Fold"}
	total = 0
	for dt in DOCTYPES:
		meta = frappe.get_meta(dt)
		for tf in [f for f in meta.fields if f.fieldtype == "Table"]:
			cdt = tf.options
			if not cdt:
				continue
			cmeta = frappe.get_meta(cdt)
			df = [f.fieldname for f in cmeta.fields if f.fieldname and f.fieldname not in SKIP and f.fieldtype not in SKIP_TYPES]
			if not df:
				continue
			cond = " AND ".join([f"`{fn}` IS NULL OR `{fn}` = ''" for fn in df])
			empty = frappe.db.sql(f"SELECT name FROM `tab{cdt}` WHERE {cond}", as_dict=True)
			if not empty:
				continue
			names = [r["name"] for r in empty]
			ph = ", ".join(["%s"] * len(names))
			frappe.db.sql(f"UPDATE `tabSync Mapping Entry` SET child_row_name = NULL, child_row_doctype = NULL WHERE child_row_name IN ({ph})", tuple(names))
			frappe.db.sql(f"DELETE FROM `tab{cdt}` WHERE name IN ({ph})", tuple(names))
			total += len(names)
			print(f"{dt} / {cdt}: {len(names)} empty rows removed")
	frappe.db.commit()
	print(f"\nDone! {total} empty child rows removed.")
