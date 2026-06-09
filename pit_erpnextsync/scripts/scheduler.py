import frappe
from croniter import croniter
from frappe.utils import now_datetime

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller
from pit_erpnextsync.scripts.data_import import start_import
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


# run import / update
def run(instances: list) -> None:
	if not instances:
		return

	for instance_data in instances:
		if not instance_data.get("enable_scheduler"):
			continue

		instance_name = instance_data.get("name")
		repetition = instance_data.get("repetition")

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

			run_bulk_update(
				instance=instance_name,
				types_str=instance_data.get("types_to_import"),
			)

			make_log(
				f"Background jobs for import/update ({repetition}) for {instance_name} created successfully",
				"INFO",
				controller.APP_NAME,
			)

		except Exception as e:
			make_log(
				f"Could not run scheduled import/update for {instance_name}: {e}",
				"ERROR",
				controller.APP_NAME,
				with_traceback=True,
			)
			continue