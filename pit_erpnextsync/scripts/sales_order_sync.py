import frappe
from pit_erpnext.scripts.logger import make_log

from pit_erpnextsync.scripts import controller

# frappe.flags key used to prevent SyncMapping.on_trash from cascading
# back to the ERPNext document we are already deleting ourselves.
SKIP_CASCADE_FLAG = "pit_skip_sync_cascade"


# * HELPERS ##########################################################################################


def _find_sync_mappings_for_doc(doctype: str, docname: str) -> list[str]:
	"""Return Sync Mapping names whose entries point to *docname*."""
	return frappe.db.get_all(
		"Sync Mapping Entry",
		filters={"mapping_doctype": doctype, "docname": docname},
		pluck="parent",
		distinct=True,
	)


def _resolve_table_name(instance: str, mapping_type: str, table_from_id: str) -> str:
	"""Resolve the raw source table name for *mapping_type* from the instance's table mapping.

	create_object_id() prepends ``<type>_`` to the table name, so the value
	stored inside selectline_id is ``<type>_<table_name>``.  We look up the
	table mapping to get the raw name that matches what the import loop
	compares against.
	"""
	candidates: list[str] = frappe.db.get_all(
		"Selectline Table Mapping",
		filters={"parent": instance, "parenttype": "Sync Instance", "type": mapping_type},
		pluck="table_name",
	)
	if not candidates:
		return table_from_id
	if table_from_id in candidates:
		return table_from_id
	prefix = f"{mapping_type}_"
	if table_from_id.startswith(prefix):
		stripped = table_from_id[len(prefix) :]
		if stripped in candidates:
			return stripped
	return candidates[0]


def _create_ignore_rule_from_mapping(mapping_name: str) -> None:
	"""Add an Import Ignore Rule row to the Sync Instance from a Sync Mapping."""
	mapping = frappe.db.get_value(
		"Sync Mapping",
		mapping_name,
		["selectline_db_instance", "type", "selectline_id"],
		as_dict=True,
	)
	if not mapping:
		return

	parts = mapping.selectline_id.split(":")
	if len(parts) != 3:
		make_log(
			f"Could not parse selectline_id '{mapping.selectline_id}' for ignore rule",
			"WARNING",
			controller.APP_NAME,
		)
		return

	primary_key_value = parts[2]
	table_name = _resolve_table_name(mapping.selectline_db_instance, mapping.type, parts[1])

	instance_doc = frappe.get_doc("Sync Instance", mapping.selectline_db_instance)
	instance_doc.append(
		"import_ignore_rules_list",
		{"type": mapping.type, "table_name": table_name, "primary_key": primary_key_value},
	)
	instance_doc.save(ignore_permissions=True)
	make_log(
		f"Added import ignore rule: type={mapping.type}, table={table_name}, pk={primary_key_value}",
		"INFO",
		controller.APP_NAME,
	)


def _delete_mappings(mapping_names: list[str]) -> None:
	"""Delete Sync Mappings while suppressing the on_trash cascade."""
	frappe.flags[SKIP_CASCADE_FLAG] = True
	try:
		for name in mapping_names:
			frappe.delete_doc("Sync Mapping", name, ignore_permissions=True)
	finally:
		frappe.flags[SKIP_CASCADE_FLAG] = False


# * WHITELISTED METHODS ##############################################################################


@frappe.whitelist()
def is_sales_order_synced(sales_order_name: str) -> bool:
	"""Check whether a Sales Order has an associated Sync Mapping."""
	return bool(_find_sync_mappings_for_doc("Sales Order", sales_order_name))


@frappe.whitelist()
def delete_synced_sales_order(sales_order_name: str, add_ignore_rule: bool = False) -> None:
	"""Delete a synced Sales Order together with its Sync Mapping(s).

	Args:
	    sales_order_name: Name of the Sales Order to delete.
	    add_ignore_rule: If True, add an Import Ignore Rule row to the
	        Sync Instance so the source row is skipped on the next import.
	"""
	if isinstance(add_ignore_rule, str):
		add_ignore_rule = add_ignore_rule.lower() in ("true", "1", "yes")

	mapping_names = _find_sync_mappings_for_doc("Sales Order", sales_order_name)

	if add_ignore_rule:
		for name in mapping_names:
			_create_ignore_rule_from_mapping(name)

	# Delete Sync Mappings first (with cascade suppressed) so the Dynamic
	# Link entries are gone before the Sales Order's link validation runs.
	_delete_mappings(mapping_names)

	# The before_delete hook sees the cascade-skip flag is already unset
	# (we unset it in _delete_mappings) and finds no remaining mappings,
	# so it becomes a no-op.  Link validation passes and the SO is deleted.
	frappe.delete_doc("Sales Order", sales_order_name, ignore_permissions=True)


# * HOOKS ############################################################################################


def before_delete_sales_order(doc, method: str) -> None:
	"""before_delete hook on Sales Order.

	Cleans up Sync Mappings *before* Frappe's link validation runs, so
	deleting a synced Sales Order does not raise a LinkValidationError.

	The form-path is handled by :func:`delete_synced_sales_order` which
	sets the cascade-skip flag and deletes mappings explicitly.  This hook
	covers list-view and any other delete path.
	"""
	# delete_synced_sales_order already handled cleanup — bail out.
	if frappe.flags.get(SKIP_CASCADE_FLAG):
		return

	mapping_names = _find_sync_mappings_for_doc("Sales Order", doc.name)
	if not mapping_names:
		return

	_delete_mappings(mapping_names)
