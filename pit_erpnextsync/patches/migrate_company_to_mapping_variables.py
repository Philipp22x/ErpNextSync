import frappe


def execute():
	"""Migrate the legacy Sync Instance `company` Link field to the
	`mapping_variables` child table.

	The single `company` field was replaced by a generic child table where each
	row maps a variable name to any document (Dynamic Link on a DocType). Any
	existing company value becomes a row ``var_name = "company"`` pointing at
	that Company, preserving ``{company}`` placeholders in the mappings.
	"""
	if "company" not in frappe.db.get_table_columns("Sync Instance"):
		return

	instances = frappe.db.sql(
		"""SELECT name, company FROM `tabSync Instance`
		WHERE company IS NOT NULL AND company != ''""",
		as_dict=True,
	)
	if not instances:
		return

	for row in instances:
		doc = frappe.get_doc("Sync Instance", row.name)
		if any(v.var_name == "company" for v in doc.get("mapping_variables") or []):
			continue
		doc.append(
			"mapping_variables",
			{
				"var_name": "company",
				"document_type": "Company",
				"document_name": row.company,
			},
		)
		doc.flags.ignore_permissions = True
		doc.save()

	frappe.db.commit()
