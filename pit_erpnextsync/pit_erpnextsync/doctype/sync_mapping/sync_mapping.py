# Copyright (c) 2025, PIT IT GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from pit_erpnextsync.scripts import controller
from pit_erpnext.scripts.logger import make_log

class SyncMapping(Document):
	#### OVERRIDES #######################################
	def on_trash(self) -> None:
		result: bool = self.on_delete_mapping()
		if result:
			make_log(f"mapping {self.selectline_id} was deleted", "INFO", controller.APP_NAME)








	#### METHODS #########################################

	# check for deleting mapped doctypes
	def on_delete_mapping(self) -> bool:

		# Skip cascade when the mapping is being cleaned up as part of a
		# synced ERPNext document's deletion (see sales_order_sync.py).
		if frappe.flags.get("pit_skip_sync_cascade"):
			return True

		if not frappe.get_single_value("Pit ErpNextSync Settings", "delete_document"):
			return True

		try:	
			mapping_table = self.mapping_table

			if not mapping_table:
				return True
			
			docs_to_check: list = []

			# create list of dicts with all mapped docs
			for row in mapping_table:
				data: dict = {"doctype": row.mapping_doctype, "docname": row.docname}

				if data not in docs_to_check:
					docs_to_check.append(data)

			docs_to_delete: list = []

			# check if doc is not used in other mapping before delete
			for doc in docs_to_check:
				doc_list: list = frappe.get_all(
					"Sync Mapping Entry",
					filters={
						"parent": ["!=", self.name],
						"mapping_doctype": doc["doctype"],
						"docname": doc["docname"]
					},
					pluck = "parent"
				)

				if doc_list:
					continue

				else:
					docs_to_delete.append(doc)
					
			# delete docs
			for doc in docs_to_delete:
				frappe.delete_doc(doc["doctype"], doc["docname"], force=True, ignore_permissions=True, ignore_missing=True, ignore_on_trash=True)
				make_log(f"{doc['doctype']} {doc['docname']} was deleted with mapping {self.selectline_id}", "INFO", controller.APP_NAME)

			return True

		except Exception as e:
			make_log(f"Could not delete documents with mapping {self.selectline_id}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
			return False