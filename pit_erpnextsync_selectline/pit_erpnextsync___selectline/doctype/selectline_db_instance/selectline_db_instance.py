# Copyright (c) 2025, PIT IT GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from pit_erpnextsync_selectline.scripts import controller
from pit_erpnextsync_selectline.scripts import reconcile
from pit_erpnext.scripts.logger import make_log


class SelectlineDBInstance(Document):

	def before_rename(self, old: str, new: str, merge: bool=False):
		controller.change_mapping_id_bulk(old, new)

	# get types from table mapping 
	def get_table_mapping(self) -> list:
		result: list = []
		for row in self.table_mapping:
			
			# validate rows
			if (
				not row.type or 
				not row.doc_type or 
				not row.table_name or 
				not row.primary_key or 
				not row.mapping
			):
				continue

			# get types
			result.append(row)

		return result

	@frappe.whitelist()
	def preview_reconciliation(self) -> dict:
		"""
		Preview mapping reconciliation - shows what would be changed without applying.
		"""
		try:
			# Parse types from comma-separated string
			types_list = []
			if self.types_to_reconcile:
				types_list = [t.strip() for t in self.types_to_reconcile.split(",") if t.strip()]
			
			result = reconcile.start_reconciliation(
				instance=self.name,
				types_str=frappe.as_json(types_list),
				dry_run=True
			)
			
			if result.get("status") == "success":
				frappe.msgprint(
					f"Reconciliation preview queued successfully.<br>"
					f"Mappings to process: {result.get('mappings_count', 0)}<br>"
					f"Check Error Log for details as jobs complete.",
					title="Reconciliation Preview",
					indicator="blue"
				)
			else:
				frappe.msgprint(
					f"Failed to queue reconciliation preview: {result.get('message', 'Unknown error')}",
					title="Error",
					indicator="red"
				)
			
			return result
			
		except Exception as e:
			frappe.log_error(f"Preview reconciliation failed: {e}")
			frappe.msgprint(
				f"Failed to start reconciliation preview: {str(e)}",
				title="Error",
				indicator="red"
			)
			return {"status": "error", "message": str(e)}

	@frappe.whitelist()
	def apply_reconciliation(self) -> dict:
		"""
		Apply mapping reconciliation - actually makes changes to mappings and documents.
		"""
		try:
			# Parse types from comma-separated string
			types_list = []
			if self.types_to_reconcile:
				types_list = [t.strip() for t in self.types_to_reconcile.split(",") if t.strip()]
			
			# Confirm with user
			result = reconcile.start_reconciliation(
				instance=self.name,
				types_str=frappe.as_json(types_list),
				dry_run=False
			)
			
			if result.get("status") == "success":
				frappe.msgprint(
					f"Reconciliation queued successfully.<br>"
					f"Mappings to process: {result.get('mappings_count', 0)}<br>"
					f"<b>Warning:</b> This will modify existing documents and mappings.<br>"
					f"Check Error Log for details as jobs complete.",
					title="Reconciliation Started",
					indicator="orange"
				)
			else:
				frappe.msgprint(
					f"Failed to queue reconciliation: {result.get('message', 'Unknown error')}",
					title="Error",
					indicator="red"
				)
			
			return result
			
		except Exception as e:
			frappe.log_error(f"Apply reconciliation failed: {e}")
			frappe.msgprint(
				f"Failed to start reconciliation: {str(e)}",
				title="Error",
				indicator="red"
			)
			return {"status": "error", "message": str(e)}



