import frappe
import json
from croniter import croniter
from frappe.utils import now_datetime

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller
from pit_erpnextsync.scripts.data_import import start_import
from pit_erpnextsync.scripts.reconcile import start_reconciliation
from pit_erpnextsync.scripts.update import run_bulk_update


SCHEDULE_DOCTYPE: str = "Sync Instance Schedule"

# A cycle for one instance imports, updates and reconciles the SAME records, so
# two cycles of the same instance must never overlap - even when they come from
# two different schedule rows (e.g. an hourly import and a daily update). The
# lock is held for the whole cycle and expires after the cycle timeout, so a
# killed worker cannot block the instance forever.
CYCLE_LOCK_TTL: int = 7200
CYCLE_LOCK_WAIT: int = 1800
CYCLE_LOCK_POLL: int = 15


def _cycle_lock_key(instance: str) -> str:
	"""Cache key of the per-instance cycle lock (site-prefixed: benches share a redis)."""
	return f"{frappe.local.site}:pes_cycle_lock:{instance}"


def _acquire_cycle_lock(instance: str) -> bool:
	"""Take the per-instance cycle lock; True when this cycle may run."""
	return bool(
		frappe.cache().set(
			_cycle_lock_key(instance),
			now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
			nx=True,
			ex=CYCLE_LOCK_TTL,
		)
	)


def _release_cycle_lock(instance: str) -> None:
	frappe.cache().delete(_cycle_lock_key(instance))


def _wait_for_cycle_lock(instance: str) -> bool:
	"""Wait for the lock of a running cycle on the same instance, then take it."""
	import time

	deadline: float = time.time() + CYCLE_LOCK_WAIT
	while time.time() < deadline:
		if _acquire_cycle_lock(instance):
			return True
		time.sleep(CYCLE_LOCK_POLL)
	return False


# get list of scheduled jobs for one repetition interval
def get_schedules(repetition: str) -> list:
	"""Return the enabled schedule rows matching `repetition` for all active instances.

	Every row of `Sync Instance Schedule` is an independent job carrying its own
	repetition and its own Import/Update/Reconcile phases. `enable_scheduler` on
	the Sync Instance stays the master switch for all of its rows.
	"""
	instances: dict = {
		row.name: row
		for row in frappe.get_all(
			"Sync Instance",
			filters={
				"enabled": 1,
				"enable_scheduler": 1,
			},
			fields=[
				"name",
				"amount_of_data_rows",
				"types_to_import",
			],
		)
	}
	if not instances:
		return []

	schedules: list = frappe.get_all(
		SCHEDULE_DOCTYPE,
		filters={
			"parenttype": "Sync Instance",
			"parent": ["in", list(instances.keys())],
			"repetition": repetition,
			"enabled": 1,
		},
		fields=[
			"name",
			"parent",
			"enabled",
			"repetition",
			"cron_expression",
			"enable_import",
			"enable_update",
			"enable_reconcile",
			"types_to_import",
			"import_batch_size",
		],
		order_by="parent asc, idx asc",
	)

	for schedule in schedules:
		instance = instances.get(schedule.get("parent")) or {}
		# a row may carry its own import settings; an empty row value falls back
		# to the instance's Import Settings (so migrated rows keep their scope)
		schedule["types_to_import"] = schedule.get("types_to_import") or instance.get("types_to_import")
		schedule["import_batch_size"] = schedule.get("import_batch_size") or instance.get("import_batch_size")
		schedule["amount_of_data_rows"] = instance.get("amount_of_data_rows")

	return schedules


def get_instance_schedules(instance: str) -> list:
	"""All schedule rows of one instance (used by scripts/reports)."""
	return frappe.get_all(
		SCHEDULE_DOCTYPE,
		filters={"parenttype": "Sync Instance", "parent": instance},
		fields=["name", "enabled", "repetition", "cron_expression", "enable_import", "enable_update", "enable_reconcile", "types_to_import", "import_batch_size", "last_scheduled_sync", "idx"],
		order_by="idx asc",
	)


# scheduler event hooks
def run_all() -> None:
	run(get_schedules("all"))

def run_daily() -> None:
	run(get_schedules("daily"))

def run_hourly() -> None:
	run(get_schedules("hourly"))

def run_weekly() -> None:
	run(get_schedules("weekly"))

def run_monthly() -> None:
	run(get_schedules("monthly"))


def run_cron() -> None:
	"""Check all cron-based schedule rows and run those whose expression matches now."""
	schedules = get_schedules("cron")
	if not schedules:
		return

	now = now_datetime().replace(second=0, microsecond=0)
	due_schedules = []

	for schedule in schedules:
		cron_expr = schedule.get("cron_expression")
		if not cron_expr:
			continue
		try:
			if croniter.match(cron_expr, now):
				due_schedules.append(schedule)
		except (ValueError, KeyError):
			make_log(
				f"Invalid cron expression '{cron_expr}' for schedule {schedule.get('name')} "
				f"of instance {schedule.get('parent')}",
				"ERROR",
				controller.APP_NAME,
			)

	run(due_schedules)


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


# run the phases enabled in each due schedule row
def run(schedules: list) -> None:
	if not schedules:
		return

	for schedule in schedules:
		instance_name = schedule.get("parent")
		repetition = schedule.get("repetition")

		if not schedule.get("enabled"):
			continue

		do_import: bool = bool(schedule.get("enable_import"))
		do_update: bool = bool(schedule.get("enable_update"))
		do_reconcile: bool = bool(schedule.get("enable_reconcile"))

		if not (do_import or do_update or do_reconcile):
			make_log(
				f"Scheduled job ({repetition}) for {instance_name} [{schedule.get('name')}] has no phase enabled "
				f"(Import/Update/Reconcile) - skipped",
				"WARNING",
				controller.APP_NAME,
			)
			continue

		# stamp the row that actually fired (the parent field is legacy)
		frappe.db.set_value(
			SCHEDULE_DOCTYPE,
			schedule.get("name"),
			"last_scheduled_sync",
			now_datetime(),
			update_modified=False,
		)
		frappe.db.commit()

		phases: list = [
			phase
			for phase, enabled in (("import", do_import), ("update", do_update), ("reconcile", do_reconcile))
			if enabled
		]

		make_log(
			f"Scheduled {', '.join(phases)} ({repetition}) for {instance_name} is starting (cycle queued)...",
			"INFO",
			controller.APP_NAME,
		)

		# Enqueue the full import -> wait -> update -> wait -> reconcile cycle as ONE
		# long-queue background job. The cron entry (default queue, 300s timeout) must
		# never block on wait_for_jobs(), otherwise it dies with a JobTimeoutException
		# ("Task exceeded maximum timeout value (300 seconds)"). deduplicate by job_id
		# skips when a cycle for this SCHEDULE ROW is already QUEUED or STARTED, so
		# cron ticks cannot start overlapping cycles of the same job. Overlap between
		# different rows of the same instance is prevented by the cycle lock inside
		# _run_cycle.
		frappe.enqueue(
			"pit_erpnextsync.scripts.scheduler._run_cycle",
			queue="long",
			timeout=CYCLE_LOCK_TTL,
			job_id=f"pes_cycle:{instance_name}:{schedule.get('name')}",
			deduplicate=True,
			instance=instance_name,
			schedule_row=schedule.get("name"),
			repetition=repetition,
			amount_of_data_rows=schedule.get("amount_of_data_rows"),
			types_to_import=schedule.get("types_to_import"),
			import_batch_size=schedule.get("import_batch_size"),
			do_import=do_import,
			do_update=do_update,
			do_reconcile=do_reconcile,
		)


def _run_cycle(
	instance,
	schedule_row=None,
	repetition="all",
	amount_of_data_rows=None,
	types_to_import=None,
	import_batch_size=None,
	do_import=True,
	do_update=True,
	do_reconcile=False,
) -> None:
	"""Long-queue orchestration: import -> wait -> update -> wait -> reconcile.

	Only the phases enabled in the schedule row run; each phase waits for the
	previous one so updates never race imports on the same records. types_to_import
	and import_batch_size come from the schedule row and fall back to the
	instance's Import Settings when the row leaves them empty.
	"""
	if not (do_import or do_update or do_reconcile):
		return

	# serialize all cycles of one instance (independent of which row they came from)
	if not _wait_for_cycle_lock(instance):
		make_log(
			f"Scheduled job ({repetition}) for {instance} [{schedule_row}] skipped: "
			f"another cycle for this instance is still running",
			"WARNING",
			controller.APP_NAME,
		)
		return

	try:
		import_job_id = None
		update_job_id = None

		if do_import:
			import_job_id = start_import(
				instance=instance,
				top=amount_of_data_rows,
				types_str=types_to_import,
				batch_size=import_batch_size,
			)
			# import first, then update - never the other way round, so updates
			# don't race against imports on the same records
			controller.wait_for_jobs([import_job_id])

		if do_update:
			update_job_id = run_bulk_update(
				instance=instance,
				types_str=types_to_import,
				batch_size=import_batch_size,
			)

		make_log(
			f"Background jobs for scheduled job ({repetition}) for {instance} [{schedule_row}] created successfully",
			"INFO",
			controller.APP_NAME,
		)

		# Reconcile types with multiple_query child tables so structural
		# changes (added/removed source rows) are applied to child tables.
		if do_reconcile:
			if update_job_id:
				controller.wait_for_jobs([update_job_id])
			mq_types: list = get_multiple_query_types(instance)
			# a row's types scope the reconcile too (empty = all mq types)
			row_types: list = controller.parse_types_input(types_to_import)
			if row_types:
				scoped_types: list = [mapping_type for mapping_type in mq_types if mapping_type in row_types]
				if len(scoped_types) != len(mq_types):
					make_log(
						f"Reconcile for {instance} scoped by the schedule row's types: {scoped_types} (instance mq types: {mq_types})",
						"INFO",
						controller.APP_NAME,
					)
				mq_types = scoped_types
			if mq_types:
				make_log(
					f"Starting reconcile for {instance} (types: {mq_types})",
					"INFO",
					controller.APP_NAME,
				)
				start_reconciliation(
					instance=instance,
					types_str=json.dumps(mq_types),
					dry_run=False,
					batch_size=import_batch_size,
				)

	except Exception as e:
		make_log(
			f"Could not run scheduled job for {instance} [{schedule_row}]: {e}",
			"ERROR",
			controller.APP_NAME,
			with_traceback=True,
		)
	finally:
		_release_cycle_lock(instance)
