import frappe


def execute():
	"""Move the per-instance scheduler settings into `Sync Instance Schedule` rows.

	Before this change a Sync Instance had ONE repetition (`repetition` +
	`cron_expression`), one `enable_reconcile` flag and one `last_scheduled_sync`
	stamp. The scheduler now reads one or more schedule rows per instance, so the
	old single setting has to become exactly one row per instance - otherwise a
	configured and running instance would silently stop being scheduled.

	The legacy fields stay on the doctype (hidden, read-only) so this patch can
	still read them after a `bench migrate`; it is idempotent and does nothing for
	instances that already have schedule rows.
	"""
	instances = frappe.get_all("Sync Instance", fields=["name"])

	for instance in instances:
		name = instance.name

		if frappe.db.exists("Sync Instance Schedule", {"parenttype": "Sync Instance", "parent": name}):
			continue

		legacy = {
			"repetition": frappe.db.get_value("Sync Instance", name, "repetition"),
			"cron_expression": frappe.db.get_value("Sync Instance", name, "cron_expression"),
			"enable_reconcile": frappe.db.get_value("Sync Instance", name, "enable_reconcile"),
			"last_scheduled_sync": frappe.db.get_value("Sync Instance", name, "last_scheduled_sync"),
		}

		# an instance without any repetition value is left alone: there was
		# nothing scheduled for it before this change either
		if not legacy.get("repetition"):
			continue

		doc = frappe.get_doc("Sync Instance", name)
		doc.append(
			"schedules",
			{
				"enabled": 1,
				"repetition": legacy.get("repetition") or "all",
				"cron_expression": legacy.get("cron_expression"),
				"enable_import": 1,
				"enable_update": 1,
				# the old single flag decided whether the cycle reconciled
				"enable_reconcile": 1 if legacy.get("enable_reconcile") else 0,
				# types_to_import / import_batch_size stay EMPTY on the migrated row:
				# an empty row value falls back to the instance's Import Settings, so
				# the instance keeps exactly its previous scope and batch size
				"last_scheduled_sync": legacy.get("last_scheduled_sync"),
			},
		)
		doc.flags.ignore_permissions = True
		doc.save()

		print(f"migrated scheduler settings of {name} into Sync Instance Schedule")
