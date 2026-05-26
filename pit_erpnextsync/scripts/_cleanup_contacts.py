import frappe


def run():
	"""Clean up stale _user_tags and unnamed duplicate Contacts."""
	instance = "officeno1_migration"

	# 1. Clear stale _user_tags on Contacts (raw "True"/"false" values from old code)
	stale = frappe.db.sql(
		"""SELECT name, _user_tags FROM tabContact
		WHERE _user_tags IS NOT NULL AND _user_tags NOT LIKE "%,%"
		AND LENGTH(_user_tags) < 20""",
		as_dict=True,
	)
	print(f"Contacts with stale _user_tags: {len(stale)}")

	count = 0
	for c in stale:
		frappe.db.set_value("Contact", c.name, "_user_tags", None)
		count += 1
		if count % 500 == 0:
			frappe.db.commit()
			print(f"  ...{count}")
	frappe.db.commit()
	print(f"Cleaned _user_tags on {count} Contacts")

	# 2. Delete unnamed Contacts (duplicates from before name_set fix)
	unnamed = frappe.db.sql(
		"""SELECT name FROM tabContact
		WHERE first_name IS NULL AND last_name IS NULL""",
		as_dict=True,
	)
	print(f"\nUnnamed Contacts to delete: {len(unnamed)}")

	count = 0
	for c in unnamed:
		try:
			frappe.delete_doc("Contact", c.name, ignore_permissions=True, force=True)
			count += 1
			if count % 500 == 0:
				frappe.db.commit()
				print(f"  ...{count}")
		except Exception:
			pass
	frappe.db.commit()
	print(f"Deleted {count} unnamed Contacts")

	# 3. Also clean up stale Customer _user_tags if any remain
	stale_cust = frappe.db.sql(
		"""SELECT name, _user_tags FROM tabCustomer
		WHERE _user_tags IN ('0', '1', ',')""",
		as_dict=True,
	)
	if stale_cust:
		print(f"\nCustomers with stale _user_tags: {len(stale_cust)}")
		count = 0
		for c in stale_cust:
			frappe.db.set_value("Customer", c.name, "_user_tags", None)
			count += 1
		frappe.db.commit()
		print(f"Cleaned _user_tags on {count} Customers")

	print("\nDONE")
