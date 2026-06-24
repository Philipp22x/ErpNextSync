import frappe
from pit_erpnextsync.scripts import controller


def debug2():
	mapping_name = "8gkc0dvds1"

	stored_entries = controller.get_mapping_table_data(mapping_name)

	print(f"Total entries: {len(stored_entries)}")

	stale_entry_names = []
	for entry in stored_entries:
		crn = entry.get("child_row_name")
		crd = entry.get("child_row_doctype")
		if crn and crd:
			ex = frappe.db.exists(crd, crn)
			if not ex:
				stale_entry_names.append(entry.get("name"))
				print(f"  STALE: {entry.get('name')} -> {crd}:{crn} exists={ex}")

	print(f"\nStale entries found: {len(stale_entry_names)}")

	if stale_entry_names:
		print("Deleting stale entries...")
		for entry_name in stale_entry_names:
			print(f"  Deleting {entry_name}")
			frappe.delete_doc("Sync Mapping Entry", entry_name, ignore_permissions=True, force=True)
		frappe.db.commit()
		print("Done deleting")

		# Re-check
		stored_after = controller.get_mapping_table_data(mapping_name)
		child_after = [e for e in stored_after if e.get("child_row_fieldname")]
		print(f"\nChild entries after deletion: {len(child_after)}")
		for e in child_after:
			print(f"  {e.get('fieldname')}.{e.get('child_row_fieldname')} crn={e.get('child_row_name')}")
	else:
		print("No stale entries found — something is wrong with the detection")
