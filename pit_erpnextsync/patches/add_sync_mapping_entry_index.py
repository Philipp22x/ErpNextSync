import frappe

from pit_erpnextsync.install import ensure_sync_mapping_entry_index


def execute():
	"""Add the composite (mapping_doctype, docname) index to `Sync Mapping Entry`.

	Both per-mapping orphan checks (reconcile.apply_field_removals and
	SyncMapping.on_delete_mapping) filtered the entry table with `parent != <mapping>`,
	which Frappe renders as `coalesce(parent,'') <> '<mapping>'` — not sargable. MariaDB
	therefore read the whole `modified` index for the `ORDER BY modified DESC LIMIT 1`.
	Measured on a 2.1M-row entry table: 43 s and 2.1M index entries read for a result of
	3 rows. Running once per mapping that has a field to remove, in every parallel
	reconcile worker, that pegged MariaDB at ~780 % CPU while the workers waited idle.

	The index is created by pit_erpnextsync.install.ensure_sync_mapping_entry_index, which
	is also wired to the `after_migrate` hook so it cannot silently disappear again.
	"""
	ensure_sync_mapping_entry_index()
