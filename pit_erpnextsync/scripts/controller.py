import json
from pprint import pprint

import frappe
import pymssql
import p4d
from frappe.model.document import Document
from frappe.utils.background_jobs import get_jobs, get_queue, get_redis_conn
from pit_erpnext.scripts.logger import make_log
from rq.registry import FailedJobRegistry, FinishedJobRegistry

# constants
APP_NAME: str = "pit_erpnextsync"
DEBUG_LOG_NAME: str = f"{APP_NAME}_DEBUG"

# Type alias for database connection
db_connection = pymssql.Connection | p4d.py4d_connection

# *## CONNECTION ##################################################################################


# create connection to db
def db_connect(instance: str) -> db_connection | None:
	"""Connects to a SQL database

	Args:
	    instance (str): Name of the Sync Instance doc

	Returns:
	    db_connection | None: Database connection or None if fails
	"""

	db_cred: dict = get_instance_data(instance=instance)

	if not db_cred:
		make_log(f"Database credentials for instance {instance} not valid", "ERROR", APP_NAME)
		return None

	driver: str = db_cred.get("driver", "pymssql")

	if driver == "pymssql":
		return _connect_mssql(db_cred, instance)
	elif driver == "p4d":
		return _connect_4d(db_cred, instance)
	else:
		make_log(f"Unknown driver '{driver}' for instance {instance}", "ERROR", APP_NAME)
		return None


def _connect_mssql(db_cred: dict, instance: str) -> pymssql.Connection | None:
	"""Connect to MSSQL database"""
	try:
		conn: pymssql.Connection = pymssql.connect(
			server=db_cred["server"],
			user=db_cred["user"],
			password=db_cred["password"],
			database=db_cred["database"],
			port=int(db_cred["port"]),
			login_timeout=30,
			timeout=30,
		)
		return conn

	except pymssql.Error as e:
		make_log(f"Could not connect to MSSQL instance {instance}: {e}", "ERROR", APP_NAME)
		return None


def _connect_4d(db_cred: dict, instance: str):
	"""Connect to 4D database using p4d driver"""
	try:
		conn = p4d.connect(
			host=db_cred["server"],
			port=int(db_cred["port"]),
			user=db_cred["user"],
			password=db_cred["password"],
		)
		return conn

	except Exception as e:
		make_log(f"Could not connect to 4D instance {instance}: {e}", "ERROR", APP_NAME)
		return None


# connection test from db instance
@frappe.whitelist()
def connection_test(instance: str) -> bool:
	"""Checks the connection to the db instance

	Args:
	    instance (str): Name of the Sync Instance doc

	Returns:
	    bool: success = True, fail = False
	"""

	db_cred: dict = get_instance_data(instance=instance)
	if not db_cred:
		return False

	driver: str = db_cred.get("driver", "pymssql")
	conn: db_connection | None = db_connect(instance=instance)

	if conn is None:
		return False

	try:
		if driver == "pymssql":
			with conn.cursor() as cur:
				cur.execute("SELECT 1")
				cur.fetchone()
		else:  # p4d (4D database)
			# p4d is DB-API 2.0 compliant, test with a simple query
			cur = conn.cursor()
			cur.execute("SELECT 1 FROM _USER_SCHEMAS LIMIT 1")
			cur.close()

		make_log(f"Connection successfully tested for instance: {instance}", "INFO", APP_NAME)
		return True

	except Exception as e:
		make_log(f"Connection test failed for {instance}: {e}", "ERROR", APP_NAME)
		return False

	finally:
		try:
			conn.close()
		except Exception:
			pass


# *## GET DATA ##################################################################################


# fetch data from db
def fetch_data(instance: str, sql: str) -> list | None:
	"""Fetch data from database using appropriate driver"""

	db_cred: dict = get_instance_data(instance=instance)
	if not db_cred:
		return None

	driver: str = db_cred.get("driver", "pymssql")
	conn: db_connection | None = db_connect(instance=instance)

	if conn is None:
		return None

	try:
		if driver == "pymssql":
			return _fetch_data_mssql(conn, sql, instance)
		else:  # p4d (4D database)
			return _fetch_data_4d(conn, sql, instance)

	except Exception as e:
		make_log(f"Fetching Data failed for {instance}: {e} {frappe.get_traceback()}", "ERROR", APP_NAME)
		return None

	finally:
		try:
			conn.close()
		except Exception:
			pass


def _fetch_data_mssql(conn: pymssql.Connection, sql: str, instance: str) -> list:
	"""Fetch data from MSSQL database"""
	fetched: list = []
	with conn.cursor(as_dict=True) as cur:
		cur.execute(sql)

		while True:
			rows = cur.fetchall()
			if not rows:
				break
			for r in rows:
				fetched.append(r)

	return fetched


def _fetch_data_4d(conn, sql: str, instance: str) -> list:
	"""Fetch data from 4D database using p4d driver.
	p4d uses a C library (lib4d_sql) which handles encoding better than python4DBI."""

	make_log(f"4D SQL execute: {sql[:500]}", "INFO", APP_NAME)

	try:
		cursor = conn.cursor()
		cursor.execute(sql)
	except Exception as e:
		make_log(f"4D execute failed: {e}", "ERROR", APP_NAME)
		try:
			cursor.close()
		except Exception:
			pass
		return []

	if cursor.rowcount == 0:
		try:
			cursor.close()
		except Exception:
			pass
		return []

	# p4d description returns (name_bytes, type, ...) - name is bytes, decode it
	headers = []
	for desc in cursor.description:
		col_name = desc[0]
		if isinstance(col_name, bytes):
			col_name = col_name.decode("utf-8")
		headers.append(col_name)

	result: list = []
	skipped: int = 0

	# Fetch row-by-row to skip problematic rows
	while True:
		try:
			row = cursor.fetchone()
			if row is None:
				break
			row_dict: dict = {}
			for i, value in enumerate(row):
				row_dict[headers[i]] = value
			result.append(row_dict)
		except Exception as e:
			skipped += 1
			if skipped <= 10:
				make_log(f"Skipped row due to 4D driver error: {e}", "WARNING", APP_NAME)
			continue

	if skipped > 0:
		make_log(f"Fetched {len(result)} rows, skipped {skipped} problematic rows for {instance}", "WARNING", APP_NAME)

	make_log(f"Fetched {len(result)} rows from 4D for {instance}", "INFO", APP_NAME)

	try:
		cursor.close()
	except Exception:
		pass

	return result


def fetch_multiple_rows(
	instance: str, table: str, condition: str, schema: str = "", parent_data: dict = None
) -> list:
	"""Fetch multiple rows from a related table for dynamic child table creation.

	Args:
	    instance (str): Name of the Sync Instance doc
	    table (str): Table name to query
	    condition (str): SQL WHERE condition (may include WHERE keyword which will be stripped)
	    schema (str): Database schema (optional)
	    parent_data (dict): Parent row data for placeholder replacement (e.g., {ColumnName: value})

	Returns:
	    list: List of row dictionaries, empty list if no results or error
	"""
	db_cred: dict = get_instance_data(instance=instance)
	if not db_cred:
		return []

	driver: str = db_cred.get("driver", "pymssql")
	conn: db_connection | None = db_connect(instance=instance)

	if conn is None:
		return []

	try:
		# Build schema prefix
		schema_prefix = f"{schema}." if schema else ""

		# Strip WHERE from condition if present (case-insensitive)
		condition_clean = condition.strip()
		if condition_clean.upper().startswith("WHERE "):
			condition_clean = condition_clean[6:].strip()

		# Replace placeholders with parent data values
		# Format 1: TableAlias.ColumnName -> replaced with actual value from parent_data
		# Format 2: {ColumnName} -> replaced with actual value from parent_data (explicit placeholder)
		if parent_data:
			import re

			# First, handle explicit placeholders like {ColumnName}
			explicit_placeholder_pattern = r"\{([A-Za-z_][A-Za-z0-9_]*)\}"

			def replace_explicit_placeholder(match):
				column = match.group(1)
				if column in parent_data:
					value = parent_data[column]
					# Quote string values, leave numbers as-is
					if isinstance(value, str):
						return f"'{value.replace(chr(39), chr(39) + chr(39))}'"
					return str(value)
				# If not found, return original
				return match.group(0)

			condition_clean = re.sub(
				explicit_placeholder_pattern, replace_explicit_placeholder, condition_clean
			)

			# Then, handle table.column patterns like A1.Id, table.column, etc.
			# Only replace if the alias is NOT the table being queried (to avoid replacing column references)
			placeholder_pattern = r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)"

			# Extract table name/alias from the table parameter
			# Handle cases like "ARTVARI", "ARTVARI A1", "table alias", etc.
			table_parts = table.split()
			table_name = table_parts[0] if table_parts else table
			table_aliases = [table_name]
			if len(table_parts) >= 2:
				table_aliases.append(table_parts[-1])  # Last part might be an alias

			def replace_placeholder(match):
				alias = match.group(1)
				column = match.group(2)

				# Skip replacement if this is the table being queried (it's a column reference, not a value)
				if alias in table_aliases or alias.upper() == table_name.upper():
					return match.group(0)

				# Try to find the value in parent_data
				# Check for exact match first (e.g., "Id")
				if column in parent_data:
					value = parent_data[column]
					# Quote string values, leave numbers as-is
					if isinstance(value, str):
						return f"'{value.replace(chr(39), chr(39) + chr(39))}'"
					return str(value)
				# Check for alias.column format (e.g., "A1.Id")
				full_key = f"{alias}.{column}"
				if full_key in parent_data:
					value = parent_data[full_key]
					if isinstance(value, str):
						return f"'{value.replace(chr(39), chr(39) + chr(39))}'"
					return str(value)
				# If not found, return original
				return match.group(0)

			condition_clean = re.sub(placeholder_pattern, replace_placeholder, condition_clean)

		# Build SQL query
		sql = f"""
        SELECT *
        FROM {schema_prefix}{table}
        WHERE {condition_clean}
        """

		make_log(f"Multiple rows SQL: {sql}", "INFO", APP_NAME)

		if driver == "pymssql":
			with conn.cursor(as_dict=True) as cur:
				cur.execute(sql)
				rows = cur.fetchall()
				return rows if rows else []
		else:  # p4d (4D database)
			cursor = conn.cursor()
			cursor.execute(sql)

			if cursor.rowcount == 0:
				cursor.close()
				return []

			# p4d description returns (name_bytes, type, ...) - decode name
			headers = []
			for desc in cursor.description:
				col_name = desc[0]
				if isinstance(col_name, bytes):
					col_name = col_name.decode("utf-8")
				headers.append(col_name)

			rows = cursor.fetchall()
			result: list = []
			for row in rows:
				row_dict: dict = {}
				for i, value in enumerate(row):
					row_dict[headers[i]] = value
				result.append(row_dict)

			cursor.close()
			return result

	except Exception as e:
		make_log(f"Fetching multiple rows failed for {instance}.{table}: {e}", "ERROR", APP_NAME)
		return []

	finally:
		try:
			conn.close()
		except Exception:
			pass


# *## MAPPING ##################################################################################


# check if mapping exists
def check_mapping_exists(selectline_id: str) -> str | None:
	"""Checks if mapping already exists.

	Args:
	    selectline_id (str): Selectline id (<tablename>:<row id>)

	Returns:
	    str | None: name of the Sync Mapping doc or None if not exists
	"""

	result: list = frappe.get_all(
		"Sync Mapping", filters={"selectline_id": selectline_id}, limit=1, pluck="name"
	)

	if result:
		return result[0]
	else:
		return None


# create new mapping
def create_mapping_doc(
	instance: str,
	primary_key_column: str,
	mapping_obj_id: str,
	mapping_type: str,
	db_time_stamp: str = "",
	time_stamp_type: str = "datetime",
) -> Document | None:

	try:
		new_mapping_doc: Document = frappe.get_doc(
			{
				"doctype": "Sync Mapping",
				"selectline_db_instance": instance,
				"selectline_id": mapping_obj_id,
				"type": mapping_type,
				"db_time_stamp": db_time_stamp,
				"time_stamp_type": time_stamp_type,
				"primary_key_column": primary_key_column,
			}
		)

		new_mapping_doc.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)

		frappe.db.commit()
		return new_mapping_doc

	except frappe.exceptions.DuplicateEntryError:
		make_log(
			f"Mapping id {mapping_obj_id} already exists! Creating new mapping aborted", "ERROR", APP_NAME
		)
		return None

	except Exception as e:
		make_log(f"Could not create new mapping doc: {e} {frappe.get_traceback()}", "ERROR", APP_NAME)
		return None


# create new selectline mapping entry
def insert_mapping_row(mapping_doc_name: str, data: dict) -> str | None:

	try:
		new_mapping_row: Document = frappe.new_doc("Sync Mapping Entry")

		new_mapping_row.set("parenttype", "Sync Mapping")
		new_mapping_row.set("parent", mapping_doc_name)
		new_mapping_row.set("parentfield", "mapping_table")

		for key, value in data.items():
			new_mapping_row.set(key, value)

		new_mapping_row.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)

		frappe.db.commit()
		return new_mapping_row.name

	except Exception as e:
		make_log(f"Could not create new Sync Mapping Entry: {e} {frappe.get_traceback()}", "ERROR", APP_NAME)
		return None


# change all mapping ids instance name
def change_mapping_id_bulk(old_instance_name: str, new_instance_name: str) -> str:

	# validate args
	if not type(old_instance_name) == str or not type(new_instance_name) == str:
		_msg = f"Handle bulk change mapping id failed: no valid arguments -> {old_instance_name}, {new_instance_name}"
		make_log(_msg, "ERROR", APP_NAME, with_traceback=True)
		return _msg

	old_converted_name: str = old_instance_name.replace(" ", "_")

	instance_mapping_list: list = frappe.get_all(
		"Sync Mapping", filters={"selectline_id": ["like", f"%{old_converted_name}%"]}, pluck="name"
	)

	for mapping_doc_name in instance_mapping_list:
		sliced_mapping_id: list = frappe.db.get_value(
			"Sync Mapping", mapping_doc_name, "selectline_id"
		).split(":")
		sliced_mapping_id[0] = new_instance_name.replace(" ", "_")
		new_mapping_id = ":".join(sliced_mapping_id)

		frappe.enqueue(
			"pit_erpnextsync.scripts.controller.change_mapping_id",
			queue="long",
			timeout=600,
			mapping_doc_name=mapping_doc_name,
			new_id=new_mapping_id,
		)

	return "Renaming mappings is queued"


# get data of mapping doc as dict
def get_mapping_table_data(mapping_name: str) -> list:
	data: list = frappe.get_all(
		"Sync Mapping Entry",
		filters={"parenttype": "Sync Mapping", "parentfield": "mapping_table", "parent": mapping_name},
		fields=[
			"mapping_doctype",
			"docname",
			"fieldname",
			"selectline_column",
			"child_row_fieldname",
			"parent",
			"parenttype",
		],
	)

	return data


# change single mapping id
def change_mapping_id(mapping_doc_name: str, new_id: str) -> None:
	try:
		mapping_doc: Document = frappe.get_doc("Sync Mapping", mapping_doc_name)
	except:
		make_log(
			f"Failed to get Sync Mapping {mapping_doc_name} for renaming mapping_id",
			"ERROR",
			APP_NAME,
			with_traceback=True,
		)
		return

	if not mapping_doc.selectline_id:
		return

	mapping_doc.selectline_id = new_id
	mapping_doc.save()
	frappe.db.commit()


# def update_mapping() -> None:
#     pass

# def delete_mapping() -> None:
#     pass


# *## IMPORT/UPDATE HOOKS ####################################################################


def get_instance_hooks(instance: str, before_after: str, import_update: str) -> list | None:

	try:
		instance_doc: Document = frappe.get_doc("Sync Instance", instance)

		if not instance_doc:
			raise Exception(instance_doc)

	except Exception as e:
		make_log(
			f"Could not get instance {instance} doc for trigger hooks: {e}",
			"ERROR",
			APP_NAME,
			with_traceback=True,
		)
		return None

	scripts_to_call: list = []

	for row in instance_doc.hooks:
		if row.trigger == before_after:
			if row.action == import_update or row.action == "both":
				# api_method: str = frappe.get_value("Server Script", row.server_script, "api_method")

				# if not api_method:
				#     continue

				scripts_to_call.append(row.server_script)

	return scripts_to_call


def trigger_hooks(instance: str, before_after: str, import_update: str) -> None:
	scripts_to_call: list | None = get_instance_hooks(
		instance=instance, before_after=before_after, import_update=import_update
	)

	make_log(f"instance: {instance}", "ERROR", APP_NAME)
	make_log(f"before_after: {before_after}", "ERROR", APP_NAME)
	make_log(f"import_update: {import_update}", "ERROR", APP_NAME)
	make_log(f"scripts_to_call: {scripts_to_call}", "ERROR", APP_NAME)

	if not scripts_to_call:
		return None

	for script in scripts_to_call:
		try:
			server_script_doc: Document = frappe.get_doc("Server Script", script)
			server_script_doc.execute_method()

		except Exception as e:
			make_log(f"Could not get server script {script}: {e}", "ERROR", APP_NAME, with_traceback=True)
			return None


# *## UTILS ##################################################################################


def wait_for_jobs(job_ids: list, poll_interval: int = 2, timeout: int = 3600) -> bool:
	"""Wait for a list of background jobs to complete before proceeding.

	Used to enforce sequential processing of mapping types (by idx order).
	This prevents race conditions where e.g. ItemVarChild jobs run before
	Item Attribute jobs finish, causing empty attribute values.

	Args:
	    job_ids: List of job IDs to wait for
	    poll_interval: Seconds between status checks (default: 2)
	    timeout: Maximum seconds to wait before giving up (default: 3600)

	Returns:
	    bool: True if all jobs completed, False if timeout reached
	"""
	if not job_ids:
		return True

	import time
	queue = get_queue("long")
	finished_registry = FinishedJobRegistry(queue=queue)
	failed_registry = FailedJobRegistry(queue=queue)

	start_time = time.time()
	site_prefix = f"{frappe.local.site}::"

	while time.time() - start_time < timeout:
		finished_ids = set(finished_registry.get_job_ids())
		failed_ids = set(failed_registry.get_job_ids())
		done_ids = finished_ids | failed_ids

		# Check if all jobs are done (with or without site prefix)
		all_done = True
		for job_id in job_ids:
			full_id = f"{site_prefix}{job_id}" if not job_id.startswith(site_prefix) else job_id
			if full_id not in done_ids and job_id not in done_ids:
				all_done = False
				break

		if all_done:
			failed_count = sum(
				1 for jid in job_ids
				if f"{site_prefix}{jid}" in failed_ids or jid in failed_ids
			)
			if failed_count > 0:
				make_log(
					f"Jobs completed with {failed_count} failures out of {len(job_ids)}",
					"WARNING",
					APP_NAME,
				)
			return True

		time.sleep(poll_interval)

	make_log(
		f"Timeout waiting for {len(job_ids)} jobs after {timeout}s",
		"ERROR",
		APP_NAME,
	)
	return False


def update_jobs(instance: str, skip_hooks: bool = False) -> None:
	try:
		queue = get_queue("long")
		run_number = frappe.get_value("Sync Instance", instance, "runs")
		job_prefix = f"{frappe.local.site}::pes:{run_number}"

		queued_jobs = [j for j in queue.get_jobs() if j.id.startswith(job_prefix)]

		finished_registry = FinishedJobRegistry(queue=queue)
		finished_job_ids = finished_registry.get_job_ids()
		finished_jobs = [j for j in finished_job_ids if j.startswith(job_prefix)]

		failed_registry = FailedJobRegistry(queue=queue)
		failed_job_ids = failed_registry.get_job_ids()
		failed_jobs = [j for j in failed_job_ids if j.startswith(job_prefix)]

		queued_count = len(queued_jobs)
		finished_count = len(finished_jobs)
		failed_count = len(failed_jobs)
	
		if len(queued_jobs) <= 0 and not skip_hooks:
			# after hooks - only trigger if not managed by the caller (sequential processing)
			trigger_hooks(instance=instance, before_after="after", import_update="import")
			
	
		frappe.publish_realtime(
			"job_count_update",
			{
				"doctype": "Sync Instance",
				"docname": instance,
				"queued_jobs": queued_count,
				"finished_jobs": finished_count,
				"failed_jobs": failed_count,
			},
		)

	except Exception as e:
		make_log(f"Could not update active job count: {e}", "ERROR", APP_NAME, with_traceback=True)
		return


# create object mapping id
def create_object_id(instance: str, table_name: str, primary_key: str, mapping_type: str = "") -> str:
	if mapping_type:
		table_name = f"{mapping_type}_{table_name}"
	return f"{instance.replace(chr(32), chr(95))}:{table_name.replace(chr(32), chr(95))}:{primary_key.replace(chr(32), chr(95))}"


# get db credentials from instance doc
def get_instance_data(instance: str) -> dict | None:
	"""Gives the data / credentials for db connection

	Args:
	    instance (str): Name of the Sync Instance doc

	Returns:
	    dict | None: Dict of the DB credentials fetched from the Sync Instance doc
	"""

	# get instace doc
	instance_doc: Document = frappe.get_doc("Sync Instance", instance)

	if not instance_doc:
		return

	data: dict = {
		"server": instance_doc.server,
		"database": instance_doc.database,
		"user": instance_doc.user,
		"password": instance_doc.password,
		"port": int(instance_doc.port),
		"driver": instance_doc.driver,
	}

	# validate instance data
	if (
		not data.get("server")
		or not data.get("database")
		or not data.get("user")
		or not data.get("password")
		or not data.get("port")
	):
		return
	else:
		return data


# get settings doc
def get_settings_doc() -> Document | None:
	try:
		return frappe.get_single("Pit ErpNextSync Settings")

	except Exception as e:
		make_log(f"Could not get settings doc: {e}", "ERROR", APP_NAME)
		return None


# load table mapping json
@frappe.whitelist()
def load_table_mapping(instance: str) -> str | None:

	try:
		instance_doc: Document = frappe.get_doc("Sync Instance", instance)

		# load json data
		file_url: str | None = instance_doc.mapping_json_file

		if not file_url:
			make_log(f"Loading table mapping aborted because file is missing", "WARNING", APP_NAME)
			return None

		file_path: str = frappe.get_site_path(file_url.lstrip("/"))

		with open(file_path, "r") as f:
			data = json.loads(f.read())

		if not data:
			make_log(f"Could not load table mapping: Invalid data", "ERROR", APP_NAME)
			return None

		instance_doc.table_mapping = []
		instance_doc.save()

		# load to table
		for row in data:
			new_mapping_row: Document = frappe.new_doc("Selectline Table Mapping")
			new_mapping_row.parenttype = "Sync Instance"
			new_mapping_row.parent = instance
			new_mapping_row.parentfield = "table_mapping"

			for key, value in row.items():
				if key in ["mapping", "query_filter"]:
					new_mapping_row.set(key, json.dumps(value, indent=4))
				else:
					new_mapping_row.set(key, value)

			new_mapping_row.insert(ignore_permissions=True)
			frappe.db.commit()

			make_log(
				f"Created table mapping entry for Sync Instance {instance} successfully", "INFO", APP_NAME
			)

		return "success"

	except Exception as e:
		make_log(f"Could not load table mapping: {e}", "ERROR", APP_NAME)
		return None


# make the sql command str
def make_sql_string(
	instance: str, db_ts_col_name: str, mapping_row_data: Document, col_to_fetch: list, top: int = 0
) -> str:

	# add primary key if not in columns to fetch
	if not mapping_row_data.primary_key in col_to_fetch:
		col_to_fetch.append(mapping_row_data.primary_key)

	# add order_by columns if not already in coumns to fetch
	if mapping_row_data.order_by and mapping_row_data.order_by not in col_to_fetch:
		col_to_fetch.append(mapping_row_data.order_by)

	if db_ts_col_name:
		col_to_fetch.append(db_ts_col_name)

	# get driver type for SQL syntax differences
	driver: str = frappe.db.get_value("Sync Instance", instance, "driver") or "pymssql"

	# set amount to fetch
	top_str: str = ""
	limit_str: str = ""
	if top > 0:
		if driver == "pymssql":
			top_str = f"TOP ({top})"
		else:  # p4d - 4D SQL uses LIMIT (after ORDER BY)
			limit_str = f"LIMIT {top}"

	# handle filters if exists in mapping
	query_filter: str = mapping_row_data.get("query_filter")
	query_filter_command: str = ""
	if query_filter and type(query_filter) == str:
		query_filter_command = f"WHERE {query_filter.replace(chr(34), '')}"

	# get db schema from instance
	schema: str = frappe.db.get_value("Sync Instance", instance, "schema") or ""
	shema_dot: str = "." if schema else ""

	# set order by string
	order_by: str = mapping_row_data.primary_key
	if mapping_row_data.order_by:
		order_by = mapping_row_data.order_by

	# sql command - driver specific syntax
	if driver == "pymssql":
		col_string: str = ",\n".join(col_to_fetch)
		fetch_sql: str = f"""
        SELECT {top_str} {col_string}
        FROM {schema}{shema_dot}{mapping_row_data.table_name}
        {query_filter_command}
        ORDER BY {order_by}
        """
	else:  # p4d - 4D SQL uses LIMIT after ORDER BY
		# Use table alias 't' and bracket-quote all column names to avoid:
		# - ambiguity when column name matches table name (e.g. ZAHLUNGSBED.ZAHLUNGSBED)
		# - reserved keyword conflicts (e.g. TEXT)
		col_string: str = ",\n".join([f"t.[{col}]" for col in col_to_fetch])
		fetch_sql: str = f"""
        SELECT {col_string}
        FROM {schema}{shema_dot}{mapping_row_data.table_name} t
        {query_filter_command}
        ORDER BY t.[{order_by}]
        {limit_str}
        """

	make_log(f"SQL string:{fetch_sql}", "INFO", APP_NAME)
	return fetch_sql


# build sql query for fetching single row by primary key (used by update)
def make_sql_string_single_row(
	instance: str, table_name: str, columns: list, primary_key_col: str, primary_key_val: str, schema: str = ""
) -> str:
	"""Build SQL query to fetch a single row by primary key.
	
	Args:
	    instance: Sync Instance name
	    table_name: Database table name
	    columns: List of column names to fetch
	    primary_key_col: Primary key column name
	    primary_key_val: Primary key value
	    schema: Database schema (optional)
	
	Returns:
	    str: SQL query string
	"""
	driver: str = frappe.db.get_value("Sync Instance", instance, "driver") or "pymssql"
	schema_dot: str = f"{schema}." if schema else ""
	
	# Modified by PIT Agent Dev 1 - 2026-03-30: For 4D, always quote PK to support numeric-like VARCHAR keys (e.g. KUNDENNR).
	if driver == "p4d":
		quoted_pk = f"'{primary_key_val}'"
	else:
		# MSSQL: quote only non-numeric values
		quoted_pk = f"'{primary_key_val}'" if not str(primary_key_val).isdigit() else primary_key_val
	
	if driver == "pymssql":
		col_string = ", ".join(columns)
		sql = f"""
			SELECT {col_string}
			FROM {schema_dot}{table_name}
			WHERE {primary_key_col} = {quoted_pk}
		"""
	else:  # p4d - 4D SQL uses bracket-quoted column names
		col_string = ", ".join([f"t.[{col}]" for col in columns])
		sql = f"""
			SELECT {col_string}
			FROM {schema_dot}{table_name} t
			WHERE t.[{primary_key_col}] = {quoted_pk}
		"""
	
	make_log(f"Single row SQL: {sql}", "INFO", APP_NAME)
	return sql


# check if types are given and if given types are existing in mapping table
def get_types_to_import(instance: str, types_args: list) -> list:
	instance_doc: Document = frappe.get_doc("Sync Instance", instance)

	# check wich type (doctypes) has to import | if types arg is empty, import all types
	types_rows_to_import: list = []
	existing_type_rows: list = instance_doc.get_table_mapping()
	if not types_args:
		types_rows_to_import = existing_type_rows
	else:
		# check if given types are exists in instance table mapping
		for arg_type in types_args:
			existing_type: dict = next((t for t in existing_type_rows if t.get("type") == arg_type), None)

			if not existing_type:
				make_log(
					f"Type {arg_type} is not existing in instance {instance} table mapping. Import for this type aborted!",
					"WARNING",
					APP_NAME,
				)
				continue
			else:
				types_rows_to_import.append(existing_type)

	return types_rows_to_import


# get value from mapping entry
def get_mapped_value(sl_id: str, doc_type: str, fieldname: str) -> str:

	mapping_doc_name: any = frappe.db.exists("Sync Mapping", {"selectline_id": sl_id})

	if fieldname == "name":
		docname_list: list = frappe.get_all(
			"Sync Mapping Entry",
			filters={"parent": mapping_doc_name, "mapping_doctype": doc_type},
			pluck="docname",
		)

		return docname_list[0] if docname_list else ""

	if mapping_doc_name:
		mapping_entry_name: any = frappe.db.exists(
			"Sync Mapping Entry",
			{"parent": mapping_doc_name, "mapping_doctype": doc_type, "fieldname": fieldname},
		)

	else:
		return ""

	if mapping_entry_name:
		_doctype = (
			frappe.db.get_value(
				"Sync Mapping Entry",
				filters={"name": mapping_entry_name, "fieldname": fieldname},
				fieldname="mapping_doctype",
			),
		)
		_filters = (
			frappe.db.get_value(
				"Sync Mapping Entry",
				filters={"name": mapping_entry_name, "fieldname": fieldname},
				fieldname="docname",
			),
		)

		value: any = frappe.db.get_value(str(_doctype[0]), str(_filters[0]), fieldname=fieldname)

		return value

	else:
		return ""


# *## TIMESTAMP CONVERSION ####################################################################


def convert_timestamp_to_string(value: any, column_type: str = "datetime") -> str:
	"""Converts timestamp value to string format for storage.

	Args:
	    value: The timestamp value from database (datetime or bytes for rowversion)
	    column_type: "datetime" or "rowversion"

	Returns:
	    str: Formatted timestamp string (ISO format for datetime, hex for rowversion)
	"""
	if value is None:
		return ""

	if column_type == "rowversion":
		# Handle SQL Server timestamp/rowversion (8-byte binary)
		if isinstance(value, bytes):
			# Convert bytes to hex string with 0x prefix (SQL Server style)
			hex_string = value.hex().upper()
			return f"0x{hex_string}"
		elif isinstance(value, str):
			# If already a string, ensure it has 0x prefix
			if not value.startswith("0x"):
				return f"0x{value.upper()}"
			return value.upper()
		else:
			# Try to convert to string
			return str(value)
	else:
		# datetime type - convert to string
		return str(value)


# *## TESTS ##################################################################################
def test():
	pass
