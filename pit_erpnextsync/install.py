import json

import frappe
from frappe.model.document import Document

from pit_erpnextsync.scripts import controller
from pit_erpnext.scripts.logger import make_log



# name of the composite index that keeps the two per-mapping orphan checks in
# reconcile.apply_field_removals() and SyncMapping.on_delete_mapping() cheap
MAPPING_ENTRY_INDEX_NAME = "mapping_doctype_docname"
MAPPING_ENTRY_INDEX_FIELDS = ["mapping_doctype", "docname"]


def ensure_sync_mapping_entry_index() -> None:
    """Create the composite index on `Sync Mapping Entry` if it is missing.

    `Sync Mapping Entry` grows to millions of rows on long-running instances, and both
    orphan checks used to filter it with `parent != <mapping>`, which Frappe renders as
    `coalesce(parent,'') <> '<mapping>'` — not sargable. MariaDB therefore fell back to
    reading the whole `modified` index for the `ORDER BY modified DESC LIMIT 1`: measured
    on a 2.1M-row table, 43 s and 2.1M index entries read for a result of 3 rows. Run once
    per mapping that has a field to remove, in every parallel reconcile worker, that drove
    MariaDB to ~780 % CPU while the workers sat idle waiting for SQL.

    The `(mapping_doctype, docname)` index turns that lookup into 3 index reads. It is
    deliberately composite: `frappe.db.get_column_index()` ignores multi-column indexes, so
    `bench migrate` will not drop it again. Called from
    `patches/add_sync_mapping_entry_index.py` and from the `after_migrate` hook, so it
    cannot silently disappear on a fresh site or on another bench.
    """
    try:
        if not frappe.db.table_exists("Sync Mapping Entry"):
            return

        frappe.db.add_index(
            "Sync Mapping Entry",
            MAPPING_ENTRY_INDEX_FIELDS,
            index_name=MAPPING_ENTRY_INDEX_NAME,
        )
    except Exception as e:
        make_log(
            f"Could not ensure index {MAPPING_ENTRY_INDEX_NAME} on Sync Mapping Entry: {e}",
            "ERROR",
            controller.APP_NAME,
            with_traceback=True,
        )


# entry point for after_install hook
def after_install() -> None:
    pass