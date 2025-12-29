# Copyright (c) 2025, PIT IT GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from pit_erpnextsync_selectline.scripts import controller
from pit_erpnext.scripts.logger import make_log


class SelectlineDBInstance(Document):

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


	


		

		
