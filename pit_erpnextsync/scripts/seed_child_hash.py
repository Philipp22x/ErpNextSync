"""Seed `Sync Mapping.child_hash` without touching a single document.

Why this exists: adding the child VALUE net to the change detection must not
force a mass update of every transaction (the check treats an empty stored hash
as "changed", which would re-run all ~7.500 transaction mappings at once, hooks
included). This script computes the value fingerprint of each mapping's CURRENT
source child rows — with the very same helpers the two checks use — and stores
it, so only real changes fire afterwards.

Run (bench python, not `bench execute`; see SKILL.md):
    cd ~/frappe-bench && ./env/bin/python -c "
    import frappe; frappe.init(site='<site>', sites_path='<bench>/sites'); frappe.connect()
    from pit_erpnextsync.scripts.seed_child_hash import main; main('<instance>', '', 1)"
    ... dry_run=1 prints the plan, dry_run=0 writes.

Afterwards: `update.bulk_check_instance('<instance>')` must report the real
deviations only (0 changed = stored value matches the source for every mapping).
"""

import frappe

from pit_erpnextsync.scripts import update
from pit_erpnextsync.scripts.controller import APP_NAME
from pit_erpnext.scripts.logger import make_log


def main(instance: str, types_str: str = "", dry_run=1) -> dict:
	"""Store the current child value fingerprint of every mapping of an instance.

	Returns {"types": n, "stored": n, "skipped_no_group": n, "fallback_types": [..]}.
	"""
	dry: bool = str(dry_run) in ("1", "True", "true", "yes")
	instance_doc = frappe.get_doc("Sync Instance", instance)
	schema: str = frappe.db.get_value("Sync Instance", instance, "schema") or ""

	if not update.child_hash_available():
		raise Exception(
			"Sync Mapping.child_hash does not exist on this site - run `bench --site <site> migrate` "
			"(patch pit_erpnextsync.patches.add_child_hash_field) first."
		)

	types: list = [r.type for r in instance_doc.table_mapping]
	if types_str:
		wanted = {t.strip() for t in str(types_str).split(",") if t.strip()}
		types = [t for t in types if t in wanted]

	summary: dict = {"dry_run": dry, "types": 0, "stored": 0, "skipped_no_group": 0, "fallback_types": []}

	for current_type in types:
		table_mapping_row = next((r for r in instance_doc.table_mapping if r.type == current_type), None)
		if table_mapping_row is None:
			continue
		groups = update.get_multiple_query_groups(instance_doc, current_type)
		if not groups:
			summary["skipped_no_group"] += 1
			continue

		# collect_fingerprints=True reuses the bulk check's own computation (one
		# child query per group) — no second implementation that could drift.
		res = update.bulk_check_type_changes(
			instance=instance,
			instance_doc=instance_doc,
			table_mapping_row=table_mapping_row,
			schema=schema,
			collect_fingerprints=True,
		)
		if res.get("fallback"):
			summary["fallback_types"].append(current_type)
			make_log(
				f"Seed child_hash: bulk path not usable for {instance}/{current_type} - skipped",
				"WARNING",
				APP_NAME,
			)
			continue

		fingerprints: dict = res.get("fingerprints") or {}
		summary["types"] += 1
		total_mappings = frappe.db.count(
			"Sync Mapping",
			{"selectline_db_instance": instance, "type": current_type, "enable": 1},
		)
		print("%-16s mappings=%-6d fingerprints=%-6d changed_by_other_signals=%d" % (
			current_type, total_mappings, len(fingerprints), len(res.get("changed") or [])), flush=True)

		if dry:
			continue

		written: int = 0
		for mapping_name, fingerprint in fingerprints.items():
			frappe.db.set_value("Sync Mapping", mapping_name, "child_hash", fingerprint, update_modified=False)
			written += 1
			if written % 500 == 0:
				frappe.db.commit()
		frappe.db.commit()
		summary["stored"] += written

	print("SEED RESULT: %s" % summary, flush=True)
	return summary
