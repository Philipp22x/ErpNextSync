import frappe


def check_settings():
	settings = frappe.get_single("PIT ERPNextSync Settings")
	for f in settings.meta.fields:
		val = getattr(settings, f.fieldname, None)
		if val is not None:
			print(f"{f.fieldname}: {val}")
