import frappe
import json
from croniter import croniter
from frappe.utils import now_datetime

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller
from pit_erpnextsync.scripts.data_import import start_import
from pit_erpnextsync.scripts.reconcile import start_reconciliation
from pit_erpnextsync.scripts.update import run_bulk_update


# get list of db instances
def get_instances(repetition: str) -> list:
	enabled_instances: list = frappe.get_all(
		"Sync Instance",
		filters={
			"enabled": 1,
			"repetition": repetition
		},
		fields=[
			"name",
			"enable_scheduler",
			"enable_reconcile",
			"repetition",
			"amount_of_data_rows",
			"types_to_import",
			"cron_expression",
		]
	)

	return enabled_instances


# scheduler event hooks
def run_all() -> None:
	run(get_instances("all"))

def run_daily() -> None:
	run(get_instances("daily"))

def run_hourly() -> None:
	run(get_instances("hourly"))

def run_weekly() -> None:
	run(get_instances("weekly"))

def run_monthly() -> None:
	run(get_instances("monthly"))


def run_cron() -> None:
	"""Check all cron-based instances and run those whose expression matches now."""
	instances = get_instances("cron")
	if not instances:
		return

	now = now_datetime().replace(second=0, microsecond=0)
	due_instances = []

	for inst in instances:
		cron_expr = inst.get("cron_expression")
		if not cron_expr:
			continue
		try:
			if croniter.match(cron_expr, now):
				due_instances.append(inst)
		except (ValueError, KeyError):
			make_log(
				f"Invalid cron expression '{cron_expr}' for instance {inst.get('name')}",
				"ERROR",
				controller.APP_NAME,
			)

	run(due_instances)


def get_multiple_query_types(instance: str) -> list:
	"""Return the instance's types whose mapping JSON uses multiple_query child tables."""
	mq_types: list = []
	instance_doc = frappe.get_doc("Sync Instance", instance)
	for row in instance_doc.table_mapping:
		try:
			mapping_json = json.loads(row.mapping or "[]")
		except (ValueError, TypeError):
			continue
		for mapped_doctype in mapping_json:
			if any(
				field.get("multiple_query") and field.get("table_fields")
				for field in mapped_doctype.get("fields", [])
			):
				mq_types.append(row.type)
				break
	return mq_types


# run import / update
def run(instances: list) -> None:
	if not instances:
		return

	for instance_data in instances:
		if not instance_data.get("enable_scheduler"):
			continue

		instance_name = instance_data.get("name")
		repetition = instance_data.get("repetition")

		frappe.db.set_value("Sync Instance", instance_name, "last_scheduled_sync", now_datetime())
		frappe.db.commit()

		make_log(
			f"Scheduled import/update ({repetition}) for {instance_name} is starting...",
			"INFO",
			controller.APP_NAME,
		)

		try:
			# Enqueue import and wait for it to finish before starting update,
			# so updates don't race against imports on the same records.
			import_job_id: str = start_import(
				instance=instance_name,
				top=instance_data.get("amount_of_data_rows"),
				types_str=instance_data.get("types_to_import"),
			)
			controller.wait_for_jobs([import_job_id])

			update_job_id: str = run_bulk_update(
				instance=instance_name,
				types_str=instance_data.get("types_to_import"),
			)

			make_log(
				f"Background jobs for import/update ({repetition}) for {instance_name} created successfully",
				"INFO",
				controller.APP_NAME,
			)

			# Reconcile types with multiple_query child tables so structural
			# changes (added/removed source rows) are applied to child tables.
			if instance_data.get("enable_reconcile"):
				controller.wait_for_jobs([update_job_id])
				mq_types: list = get_multiple_query_types(instance_name)
				if mq_types:
					make_log(
						f"Starting reconcile for {instance_name} (types: {mq_types})",
						"INFO",
						controller.APP_NAME,
					)
					start_reconciliation(
						instance=instance_name,
						types_str=json.dumps(mq_types),
						dry_run=False,
					)

		except Exception as e:
			make_log(
				f"Could not run scheduled import/update for {instance_name}: {e}",
				"ERROR",
				controller.APP_NAME,
				with_traceback=True,
			)
			continue