import json
import time
import frappe
from frappe.model.document import Document
from typing import Dict, List, Tuple, Any, Optional

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller
from pit_erpnextsync.scripts.classes.field_vars import FieldVars


APP_NAME: str = "pit_erpnextsync"


def parse_types_input(types_input: str) -> List[str]:
	"""Parse types input from JSON string or comma-separated string."""
	if not types_input:
		return []

	types_input = str(types_input).strip()
	if not types_input:
		return []

	# Accept JSON list (e.g. '["Item","Customer"]') for compatibility.
	if types_input.startswith("["):
		try:
			parsed = json.loads(types_input)
			if isinstance(parsed, list):
				return [str(t).strip() for t in parsed if str(t).strip()]
		except Exception:
			pass

	# Fallback: comma-separated values from Sync Instance field.
	return [t.strip() for t in types_input.split(",") if t.strip()]


@frappe.whitelist()
def start_reconciliation(
	instance: str, 
	types_str: str = "", 
	dry_run: bool = True
) -> Dict:
	"""Entry point for reconciliation. Enqueues the actual work as a background job."""
	import uuid
	frappe.enqueue(
		"pit_erpnextsync.scripts.reconcile._run_reconciliation",
		queue="long",
		timeout=600,
		job_id=f"pes_reconcile_main:{uuid.uuid4().hex[:8]}",
		instance=instance,
		types_str=types_str,
		dry_run=dry_run
	)
	return {
		"status": "success",
		"message": "Reconciliation started in background"
	}


def _run_reconciliation(
	instance: str, 
	types_str: str = "", 
	dry_run: bool = True
) -> Dict:
	"""Actual reconciliation logic - runs as a long background job."""
	try:
		# Get instance doc
		instance_doc: Document = frappe.get_doc("Sync Instance", instance)
		if not instance_doc:
			raise Exception(f"Could not get instance doc {instance}")
		
		# Parse requested types. Explicit arg wins; fallback to instance setting.
		types: List[str] = parse_types_input(types_str)
		if not types:
			types = parse_types_input(instance_doc.get("types_to_import") or "")

		# Limit rows per type (0 means all), mirroring import behavior.
		rows_per_type: int = int(instance_doc.get("amount_of_data_rows") or 0)
		
		# Get all enabled mappings for this instance
		filters = {
			"selectline_db_instance": instance,
			"enable": 1
		}
		if types:
			filters["type"] = ["in", types]
		
		mapping_rows: List[Dict[str, str]] = frappe.get_all(
			"Sync Mapping",
			filters=filters,
			fields=["name", "type"]
		)

		if not mapping_rows:
			make_log(f"No enabled mappings found for instance {instance}", "WARNING", APP_NAME)
			return
		
		# Get types in idx order from instance table mapping
		types_in_order: List[str] = [row.type for row in instance_doc.table_mapping]
		if types:
			types_in_order = [t for t in types_in_order if t in types]

		# Group mappings by type
		mappings_by_type: Dict[str, List[str]] = {}
		for mapping_row in mapping_rows:
			mapping_name = mapping_row.get("name")
			mapping_type = mapping_row.get("type")
			if not mapping_name or not mapping_type:
				continue
			if mapping_type not in mappings_by_type:
				mappings_by_type[mapping_type] = []
			mappings_by_type[mapping_type].append(mapping_name)

		if rows_per_type > 0:
			for mapping_type, mapping_names in mappings_by_type.items():
				mappings_by_type[mapping_type] = mapping_names[:rows_per_type]

		# Batch reconcile jobs using import_batch_size — mirrors the import batch logic.
		# Each batch job processes its mappings serially (one DB connection at a time per job).
		# Setting import_batch_size=1 gives one mapping per job (max parallelism).
		# Setting it higher reduces concurrent DB connections.
		instance_values = frappe.get_value(
			"Sync Instance", instance, ["import_batch_size"], as_dict=True
		)
		batch_size: int = max(int(instance_values.get("import_batch_size") or 10), 1)

		import uuid
		all_queued_jobs: List[str] = []
		for current_type in types_in_order:
			type_mappings = mappings_by_type.get(current_type, [])
			if not type_mappings:
				continue

			batches: List[List[str]] = [
				type_mappings[i:i + batch_size]
				for i in range(0, len(type_mappings), batch_size)
			]

			type_job_ids: List[str] = []
			for batch in batches:
				job_id = f"pes_reconcile:{uuid.uuid4().hex[:16]}"
				frappe.enqueue(
					"pit_erpnextsync.scripts.reconcile.reconcile_batch",
					queue="long",
					timeout=600 * len(batch),
					job_id=job_id,
					instance=instance,
					mapping_names=batch,
					dry_run=dry_run
				)
				type_job_ids.append(job_id)

			make_log(
				f"Reconciliation queued {len(type_job_ids)} batch jobs for type {current_type} "
				f"({len(type_mappings)} mappings, batch_size={batch_size}, dry_run={dry_run})",
				"INFO",
				APP_NAME
			)

			all_queued_jobs.extend(type_job_ids)

		total_effective = sum(len(v) for v in mappings_by_type.values())
		make_log(
			f"Reconciliation completed for {total_effective} mappings "
			f"(dry_run={dry_run}, rows_per_type={rows_per_type or 'all'}, types={types or 'all'})",
			"INFO",
			APP_NAME
		)
		
	except Exception as e:
		make_log(
			f"Failed to run reconciliation: {e} {frappe.get_traceback()}",
			"ERROR",
			APP_NAME
		)


def reconcile_batch(
	instance: str,
	mapping_names: List[str],
	dry_run: bool = True
) -> None:
	"""
	Background job: Reconciles a batch of mappings serially.
	Processes each mapping one at a time — keeps DB connections sequential
	within this job, while multiple batch jobs can still run in parallel.
	"""
	for mapping_name in mapping_names:
		reconcile_single_mapping(instance=instance, mapping_name=mapping_name, dry_run=dry_run)


def reconcile_single_mapping(
	instance: str,
	mapping_name: str,
	dry_run: bool = True
) -> Dict:
	"""
	Background job: Reconciles a single mapping record with current JSON definition.
	
	Args:
		instance: Name of the Sync Instance
		mapping_name: Name of the Sync Mapping doc
		dry_run: If True, only preview changes
	
	Returns:
		Dict with reconciliation results
	"""
	try:
		# Get mapping doc
		mapping_doc: Document = frappe.get_doc("Sync Mapping", mapping_name)
		if not mapping_doc:
			raise Exception(f"Mapping {mapping_name} not found")
		
		# Get the mapping type
		mapping_type: str = mapping_doc.type
		if not mapping_type:
			raise Exception(f"Mapping {mapping_name} has no type")
		
		# Get current JSON mapping from instance
		instance_doc: Document = frappe.get_doc("Sync Instance", instance)
		new_json_mapping: Optional[List[Dict]] = get_current_json_mapping(instance_doc, mapping_type)
		
		if not new_json_mapping:
			raise Exception(f"No JSON mapping found for type {mapping_type}")
		
		# Get stored mapping entries
		stored_entries: List[Dict] = controller.get_mapping_table_data(mapping_name)
		
		# First detect changes to know what columns we need to fetch
		# We do a preliminary comparison without fetched_obj
		preliminary_changes: Dict = get_mapping_changes(
			mapping_name=mapping_name,
			stored_entries=stored_entries,
			new_json_mapping=new_json_mapping,
			fetched_obj={},
			instance=instance
		)
		
		# Get the SelectLine data for this mapping, including new columns
		# for both added fields and sl_column changes.
		additional_fields_to_fetch: List[Dict] = list(preliminary_changes.get("fields_to_add", []))
		for structural_change in preliminary_changes.get("structural_changes", []):
			if structural_change.get("column_change") and structural_change.get("new_def"):
				additional_fields_to_fetch.append(structural_change["new_def"])

		id_data: Dict = parse_object_id(mapping_doc.selectline_id)
		fetched_obj: Optional[Dict] = fetch_source_data(
			instance=instance,
			mapping_doc=mapping_doc,
			id_data=id_data,
			new_fields=additional_fields_to_fetch
		)
		
		if not fetched_obj:
			raise Exception(f"Could not fetch source data for {mapping_doc.selectline_id}")
		
		# Detect changes again with actual fetched data
		changes: Dict = get_mapping_changes(
			mapping_name=mapping_name,
			stored_entries=stored_entries,
			new_json_mapping=new_json_mapping,
			fetched_obj=fetched_obj,
			instance=instance
		)
		
		# Validate dependencies for new fields
		if changes.get("fields_to_add"):
			dep_status: Dict = validate_dependencies(
				instance=instance,
				fields=changes["fields_to_add"],
				fetched_obj=fetched_obj
			)
			
			if not dep_status["valid"]:
				raise Exception(
					f"Dependency validation failed for mapping {mapping_name}: "
					f"Missing: {dep_status['missing_deps']}"
				)
		
		result: Dict = {
			"mapping_name": mapping_name,
			"selectline_id": mapping_doc.selectline_id,
			"dry_run": dry_run,
			"changes_detected": changes,
			"actions": {}
		}
		
		if not dry_run:
			# Apply changes
			
			# 1. Handle field removals (remove mapping entries and orphaned docs)
			if changes.get("fields_to_remove"):
				removal_result = apply_field_removals(
					mapping_name=mapping_name,
					fields_to_remove=changes["fields_to_remove"],
					instance=instance
				)
				result["actions"]["removals"] = removal_result
			
			# 2. Handle structural changes
			if changes.get("structural_changes"):
				struct_result = apply_structural_changes(
					instance=instance,
					mapping_name=mapping_name,
					structural_changes=changes["structural_changes"],
					fetched_obj=fetched_obj
				)
				result["actions"]["structural"] = struct_result
			
			# 3. Handle field additions
			if changes.get("fields_to_add"):
				fields_to_add = changes["fields_to_add"]
				make_log(
					f"Applying {len(fields_to_add)} field additions for {mapping_name}: "
					f"{[f.get('doctype') + '.' + f.get('fieldname') for f in fields_to_add]}",
					"DEBUG",
					APP_NAME
				)
				addition_result = apply_field_additions(
					instance=instance,
					mapping_name=mapping_name,
					fields_to_add=fields_to_add,
					fetched_obj=fetched_obj
				)
				result["actions"]["additions"] = addition_result

			# 4. Normalize child tables (barcode/uom) for mapped Item docs
			cleanup_result = normalize_item_child_tables(mapping_name=mapping_name)
			if cleanup_result.get("rows_removed") or cleanup_result.get("rows_merged"):
				result["actions"]["cleanup"] = cleanup_result
			
			# Update timestamp only (don't save parent doc to avoid overwriting child table)
			frappe.db.set_value("Sync Mapping", mapping_name, "last_update", frappe.utils.now())
			frappe.db.commit()
			make_log(
				f"Updated timestamp for {mapping_name} without saving child table",
				"DEBUG",
				APP_NAME
			)
		
		make_log(
			f"Reconciliation completed for {mapping_name} (dry_run={dry_run})",
			"INFO",
			APP_NAME
		)
		
		return result
		
	except Exception as e:
		make_log(
			f"Reconciliation failed for {mapping_name}: {e} {frappe.get_traceback()}",
			"ERROR",
			APP_NAME
		)
		return {
			"mapping_name": mapping_name,
			"status": "error",
			"error": str(e)
		}


def get_mapping_changes(
	mapping_name: str,
	stored_entries: List[Dict],
	new_json_mapping: List[Dict],
	fetched_obj: Dict,
	instance: str
) -> Dict:
	"""
	Compares stored mapping entries with new JSON mapping definition.
	
	Returns dict with:
	- fields_to_add: List of new field definitions
	- fields_to_remove: List of field info to remove from mapping
	- structural_changes: List of fields with changed mapping types
	"""
	
	# Flatten both structures for comparison
	new_fields: List[Dict] = get_flattened_fields(new_json_mapping)
	stored_fields: List[Dict] = get_flattened_entries(stored_entries)
	
	# Create lookup dicts
	new_fields_dict: Dict[str, Dict] = {}
	for field in new_fields:
		key = get_field_key(field)
		new_fields_dict[key] = field
	
	stored_fields_dict: Dict[str, Dict] = {}
	for field in stored_fields:
		key = get_field_key(field)
		stored_fields_dict[key] = field
	
	# Detect changes
	fields_to_add: List[Dict] = []
	fields_to_remove: List[Dict] = []
	structural_changes: List[Dict] = []
	
	# Fields to add (in new but not in stored)
	for key, field_def in new_fields_dict.items():
		if key not in stored_fields_dict:
			fields_to_add.append(field_def)
			make_log(
				f"Field to add: {key} ({field_def.get('doctype')}.{field_def.get('fieldname')})",
				"DEBUG",
				APP_NAME
			)
	
	# Fields to remove (in stored but not in new)
	for key, field_info in stored_fields_dict.items():
		if key not in new_fields_dict:
			fields_to_remove.append(field_info)
			make_log(
				f"Field to remove: {key} ({field_info.get('mapping_doctype')}.{field_info.get('fieldname')})",
				"DEBUG",
				APP_NAME
			)
	
	# Structural changes (same field key but different mapping type)
	for key in new_fields_dict:
		if key in stored_fields_dict:
			new_def = new_fields_dict[key]
			old_def = stored_fields_dict[key]
			
			# Check if mapping type changed
			new_type = get_mapping_type(new_def)
			old_type = get_mapping_type(old_def)
			
			if new_type != old_type:
				structural_changes.append({
					"field_key": key,
					"old_type": old_type,
					"new_type": new_type,
					"old_def": old_def,
					"new_def": new_def
				})
			# Check if source column changed (for sl_column types)
			elif new_type == "sl_column":
				new_col = new_def.get("sl_column")
				old_col = old_def.get("selectline_column")
				if new_col and old_col and new_col != old_col:
					structural_changes.append({
						"field_key": key,
						"old_type": old_type,
						"new_type": new_type,
						"old_def": old_def,
						"new_def": new_def,
						"column_change": True
					})
	
	make_log(
		f"Mapping changes for {mapping_name}: "
		f"fields_to_add={[f.get('doctype') + '.' + f.get('fieldname') for f in fields_to_add]}, "
		f"total_new={len(new_fields_dict)}, total_stored={len(stored_fields_dict)}",
		"DEBUG",
		APP_NAME
	)
	
	return {
		"fields_to_add": fields_to_add,
		"fields_to_remove": fields_to_remove,
		"structural_changes": structural_changes,
		"total_new_fields": len(new_fields_dict),
		"total_stored_fields": len(stored_fields_dict)
	}


def get_field_key(field_def: Dict) -> str:
	"""Generate unique key for a field definition."""
	doctype = field_def.get("doctype") or field_def.get("mapping_doctype", "")
	fieldname = field_def.get("fieldname", "")
	child_row = field_def.get("child_row_fieldname", "")
	source_column = field_def.get("sl_column") or field_def.get("selectline_column")
	default_value = field_def.get("default")
	
	if child_row:
		if source_column:
			return f"{doctype}:{fieldname}:{child_row}:src:{source_column}"
		if default_value is not None:
			return f"{doctype}:{fieldname}:{child_row}:default:{default_value}"
		return f"{doctype}:{fieldname}:{child_row}"
	return f"{doctype}:{fieldname}"


def get_mapping_type(field_def: Dict) -> str:
	"""Determine the mapping type from field definition."""
	if field_def.get("table_fields"):
		return "table_fields"
	elif field_def.get("selectline_column"):
		return "sl_column"
	elif field_def.get("sl_column"):
		return "sl_column"
	elif field_def.get("default") is not None:
		return "default"
	elif field_def.get("field_var"):
		return "field_var"
	elif field_def.get("mapped_value"):
		return "mapped_value"
	elif field_def.get("get_redis"):
		return "get_redis"
	return "unknown"


def apply_value_map(field_def: Dict, value: Any) -> Any:
	"""Apply value_map/value_map_default translation if configured."""
	if value is None:
		return value

	value_map = field_def.get("value_map")
	if not value_map or not isinstance(value_map, dict):
		return value

	return value_map.get(str(value), field_def.get("value_map_default", value))


def get_flattened_fields(json_mapping: List[Dict]) -> List[Dict]:
	"""
	Flattens nested JSON mapping structure for comparison.
	Includes parent fields and child table fields with paths.
	"""
	result: List[Dict] = []
	child_group_counter: Dict[str, int] = {}
	
	for doctype_def in json_mapping:
		doctype = doctype_def.get("doctype")
		
		for field in doctype_def.get("fields", []):
			fieldname = field.get("fieldname")
			field_def = {
				"doctype": doctype,
				"fieldname": fieldname,
				"sl_column": field.get("sl_column"),
				"value_map": field.get("value_map"),
				"value_map_default": field.get("value_map_default"),
				"default": field.get("default"),
				"field_var": field.get("field_var"),
				"mapped_value": field.get("mapped_value"),
				"alt_key": field.get("alt_key"),
				"force_str_type": field.get("force_str_type"),
				"reqd": field.get("reqd"),
				"table_fields": None,
				"child_row_fieldname": None,
				"child_row_doctype": None
			}
			
			# Handle child tables
			if field.get("table_fields"):
				field_def["table_fields"] = True
				
			table_fields = field.get("table_fields") or []
			if table_fields:
				group_key_base = f"{doctype}:{fieldname}"
				group_idx = child_group_counter.get(group_key_base, 0) + 1
				child_group_counter[group_key_base] = group_idx
				child_row_group_key = f"{group_key_base}:group:{group_idx}"
				child_group_sl_columns = [
					tf.get("sl_column") for tf in table_fields if tf.get("sl_column")
				]
				is_mq = field.get("multiple_query")
				for table_field in table_fields:
					child_def = {
						"doctype": doctype,
						"fieldname": fieldname,
						"child_row_fieldname": table_field.get("table_fieldname"),
						"sl_column": table_field.get("sl_column"),
						"value_map": table_field.get("value_map"),
						"value_map_default": table_field.get("value_map_default"),
						"default": table_field.get("default"),
						"field_var": table_field.get("field_var"),
						"mapped_value": table_field.get("mapped_value"),
						"get_redis": table_field.get("get_redis"),
						"alt_key": table_field.get("alt_key"),
						"force_str_type": table_field.get("force_str_type"),
						"reqd": table_field.get("reqd"),
						"child_row_group_key": child_row_group_key,
						"child_group_sl_columns": child_group_sl_columns,
						"multiple_query": is_mq,
						"multiple_query_table": field.get("multiple_query_table") if is_mq else None,
						"multiple_query_condition": field.get("multiple_query_condition") if is_mq else None,
						"table_fields": None,
						"child_row_doctype": None  # Will be resolved during application
					}
					result.append(child_def)
			else:
				result.append(field_def)
	
	return result


def get_flattened_entries(stored_entries: List[Dict]) -> List[Dict]:
	"""
	Flattens stored mapping entries for comparison.
	"""
	result: List[Dict] = []
	
	for entry in stored_entries:
		field_def = {
			"mapping_doctype": entry.get("mapping_doctype"),
			"fieldname": entry.get("fieldname"),
			"selectline_column": entry.get("selectline_column"),
			"child_row_fieldname": entry.get("child_row_fieldname"),
			"child_row_name": entry.get("child_row_name"),
			"child_row_doctype": entry.get("child_row_doctype"),
			"docname": entry.get("docname"),
			"parent": entry.get("parent")
		}
		result.append(field_def)
	
	return result


def validate_dependencies(
	instance: str,
	fields: List[Dict],
	fetched_obj: Dict
) -> Dict:
	"""
	Validates field_var and mapped_value dependencies.
	
	Returns:
		Dict with 'valid' (bool) and 'missing_deps' (list of failed dependencies)
	"""
	missing_deps: List[str] = []
	
	for field in fields:
		# Check field_var dependencies
		if field.get("field_var"):
			# field_var values come from FieldVars object
			# We'll check this at runtime, can't validate statically
			pass
		
		# Check mapped_value dependencies
		mapped_val = field.get("mapped_value")
		if mapped_val and isinstance(mapped_val, dict):
			table_name = mapped_val.get("table_name")
			sl_id_col = mapped_val.get("sl_id")
			
			if table_name and sl_id_col:
				# Check if referenced ID exists in fetched object
				ref_id = fetched_obj.get(sl_id_col)
				if ref_id:
					# Check if mapping exists for this reference
					ref_obj_id = controller.create_object_id(
						instance=instance,
						table_name=table_name,
						primary_key=str(ref_id)
					)
					mapping_exists = controller.check_mapping_exists(ref_obj_id)
					if not mapping_exists:
						missing_deps.append(
							f"mapped_value reference not found: {table_name}:{ref_id}"
						)
				else:
					missing_deps.append(
						f"mapped_value source column {sl_id_col} not in fetched data"
					)
	
	return {
		"valid": len(missing_deps) == 0,
		"missing_deps": missing_deps
	}


def _handle_multiple_query_group(
	instance: str,
	mapping_name: str,
	mapping_doc: Document,
	group_fields: List[Dict],
	fetched_obj: Dict,
	created_docs_cache: Dict[str, str],
	field_vars_obj: FieldVars,
) -> None:
	"""
	Handle multiple_query child table fields during reconciliation.
	Fetches data from the related table and creates/updates child rows.

	Args:
		instance: Sync Instance name
		mapping_name: Sync Mapping doc name
		mapping_doc: Sync Mapping document
		group_fields: Child field definitions belonging to one parent field
		fetched_obj: Parent row data from SelectLine (for placeholder replacement)
		created_docs_cache: Cache of docnames by doctype
		field_vars_obj: FieldVars for variable resolution
	"""
	first = group_fields[0]
	doctype = first.get("doctype")
	fieldname = first.get("fieldname")
	mq_table = first.get("multiple_query_table")
	mq_condition = first.get("multiple_query_condition")

	if not doctype or not fieldname or not mq_table or not mq_condition:
		raise Exception(f"Missing multiple_query metadata in field group: {first}")

	make_log(
		f"Handling multiple_query group: {doctype}.{fieldname} "
		f"from {mq_table} WHERE {mq_condition}",
		"INFO",
		APP_NAME,
	)

	# Get docname of the parent document
	docname = created_docs_cache.get(doctype)
	if not docname:
		existing = frappe.get_all(
			"Sync Mapping Entry",
			filters={"parent": mapping_name, "mapping_doctype": doctype},
			limit=1,
			pluck="docname",
		)
		if existing:
			docname = existing[0]
			created_docs_cache[doctype] = docname
		else:
			raise Exception(f"No document found for doctype {doctype} in mapping {mapping_name}")

	# Fetch rows from the related table
	schema = frappe.db.get_value("Sync Instance", instance, "schema") or ""
	source_rows = controller.fetch_multiple_rows(
		instance=instance,
		table=mq_table,
		condition=mq_condition,
		schema=schema,
		parent_data=fetched_obj,
	)

	if not source_rows:
		make_log(
			f"No rows returned from {mq_table} for {doctype}.{fieldname}",
			"WARNING",
			APP_NAME,
		)
		return

	make_log(
		f"Fetched {len(source_rows)} rows from {mq_table} for {doctype}.{fieldname}",
		"INFO",
		APP_NAME,
	)

	# Get child doctype from parent field options
	child_doctype = frappe.get_meta(doctype).get_field(fieldname).options
	if not child_doctype:
		raise Exception(f"Could not determine child doctype for {doctype}.{fieldname}")

	# Load parent document and existing child rows
	parent_doc = frappe.get_doc(doctype, docname)
	existing_rows = list(parent_doc.get(fieldname) or [])

	# Build case-insensitive lookup for source row columns.
	# fetch_multiple_rows returns column names in the database's native
	# casing (e.g. PascalCase on 4D), but the JSON mapping uses uppercase.
	def _get_col(row: Dict, col: str) -> Any:
		if col is None:
			return None
		if col in row:
			return row[col]
		upper = col.upper()
		for k, v in row.items():
			if k.upper() == upper:
				return v
		return None

	# Build lookup: child_fieldname → sl_column for matching existing rows
	sl_field_map = {
		f.get("child_row_fieldname"): f.get("sl_column")
		for f in group_fields
		if f.get("sl_column")
	}

	# Track which existing rows have been matched (to avoid reusing the same row
	# for multiple source rows).
	matched_row_names: set = set()

	for source_row in source_rows:
		# Pre-validate: resolve all field values and skip rows with empty required fields.
		# This prevents creating empty child rows when a multiple_query source row
		# has null values for required columns.
		resolved_values: Dict[str, Any] = {}
		row_has_data = False
		skip_row = False
		for field_def in group_fields:
			child_fn = field_def.get("child_row_fieldname")
			if field_def.get("sl_column"):
				value = _get_col(source_row, field_def["sl_column"])
				if field_def.get("force_str_type") == 1 and value is not None:
					value = str(value)
				value = apply_value_map(field_def, value)
			elif field_def.get("default") is not None:
				value = field_def["default"]
			elif field_def.get("get_redis"):
				value = field_vars_obj.get_field_var_value(field_def["get_redis"])
			else:
				continue
			resolved_values[child_fn] = value
			if value in ["", None] and field_def.get("reqd") == 1:
				make_log(
					f"Skipping {doctype}.{fieldname} row from {mq_table}: "
					f"required field {child_fn} is empty in source row {source_row}",
					"WARNING",
					APP_NAME,
				)
				skip_row = True
				break
			if value not in ["", None]:
				row_has_data = True

		if skip_row or not row_has_data:
			if not skip_row:
				make_log(
					f"Skipping {doctype}.{fieldname} row from {mq_table}: no data in source row {source_row}",
					"WARNING",
					APP_NAME,
				)
			continue

		# Try to find an existing child row with matching sl_column values
		existing_child_name = None
		if sl_field_map:
			for existing_row in existing_rows:
				if existing_row.name in matched_row_names:
					continue
				all_match = True
				for child_fn, sl_col in sl_field_map.items():
					expected = _get_col(source_row, sl_col)
					if expected is not None and str(existing_row.get(child_fn) or "") != str(expected):
						all_match = False
						break
				if all_match:
					existing_child_name = existing_row.name
					matched_row_names.add(existing_row.name)
					break

		if existing_child_name:
			# Reuse existing child row — update its values
			target_child_doctype = child_doctype
			target_child_name = existing_child_name
		else:
			# Create new child row as standalone (not via parent.save())
			# to avoid saving the entire parent doc which could overwrite
			# in-progress changes from other reconciliation steps.
			child_name = frappe.generate_hash(length=8)
			new_row = frappe.get_doc({
				"doctype": child_doctype,
				"parenttype": doctype,
				"parent": docname,
				"name": child_name,
				"parentfield": fieldname,
			})
			new_row.insert(ignore_permissions=True, ignore_mandatory=True)
			target_child_doctype = new_row.doctype
			target_child_name = new_row.name
			existing_rows.append(new_row)

		# Set child field values from source data
		for field_def in group_fields:
			child_fn = field_def.get("child_row_fieldname")
			value = resolved_values.get(child_fn)
			if value is None:
				continue
			if value not in ["", None]:
				frappe.db.set_value(
					target_child_doctype, target_child_name, child_fn, value
				)

			# Create mapping entry for trackable fields (has sl_column or get_redis)
			if field_def.get("sl_column"):
				existing_entry = frappe.db.exists(
					"Sync Mapping Entry",
					{
						"parent": mapping_name,
						"mapping_doctype": doctype,
						"docname": docname,
						"fieldname": fieldname,
						"child_row_fieldname": child_fn,
						"selectline_column": field_def["sl_column"],
					},
				)
				if not existing_entry:
					controller.insert_mapping_row(
						mapping_doc_name=mapping_name,
						data={
							"mapping_doctype": doctype,
							"docname": docname,
							"fieldname": fieldname,
							"child_row_fieldname": child_fn,
							"child_row_name": target_child_name,
							"child_row_doctype": target_child_doctype,
							"selectline_column": field_def["sl_column"],
						},
					)
					make_log(
						f"Created child mapping entry for {doctype}.{fieldname}.{child_fn} "
						f"(row: {target_child_name})",
						"DEBUG",
						APP_NAME,
					)

	# Commit per source row to keep transactions small
	frappe.db.commit()


def apply_field_additions(
	instance: str,
	mapping_name: str,
	fields_to_add: List[Dict],
	fetched_obj: Dict
) -> Dict:
	"""
	Adds new fields to existing mapping and updates ERPNext documents.
	"""
	added_count: int = 0
	failed_count: int = 0
	errors: List[str] = []
	
	# Get mapping doc for docname references
	mapping_doc: Document = frappe.get_doc("Sync Mapping", mapping_name)
	
	# Create field_vars object for this reconciliation
	field_vars_obj: FieldVars = FieldVars()
	
	# Track newly created documents to avoid recreating
	created_docs_cache: Dict[str, str] = {}
	# Track child rows per mapping block so table_fields in the same block
	# (e.g. uom + conversion_factor) are written to the same row.
	child_rows_cache: Dict[str, Dict] = {}

	# Separate multiple_query child table fields — these fetch data from a
	# related table (not from the parent row) and can produce multiple child rows.
	mq_field_defs = [f for f in fields_to_add if f.get("multiple_query") and f.get("child_row_fieldname")]
	regular_fields = [f for f in fields_to_add if not (f.get("multiple_query") and f.get("child_row_fieldname"))]

	if mq_field_defs:
		# Group by (doctype, fieldname) — all table_fields in one group share the
		# same parent field and query the same related table.
		mq_groups: Dict[str, List[Dict]] = {}
		for f in mq_field_defs:
			key = f"{f.get('doctype')}:{f.get('fieldname')}"
			if key not in mq_groups:
				mq_groups[key] = []
			mq_groups[key].append(f)

		for group_key, group_fields in mq_groups.items():
			try:
				_handle_multiple_query_group(
					instance=instance,
					mapping_name=mapping_name,
					mapping_doc=mapping_doc,
					group_fields=group_fields,
					fetched_obj=fetched_obj,
					created_docs_cache=created_docs_cache,
					field_vars_obj=field_vars_obj,
				)
				added_count += len(group_fields)
			except Exception as e:
				doctype = group_fields[0].get("doctype", "?")
				fieldname = group_fields[0].get("fieldname", "?")
				error_msg = f"multiple_query group {doctype}.{fieldname}: {e}"
				make_log(error_msg, "ERROR", APP_NAME, with_traceback=True)
				errors.append(error_msg)
				failed_count += 1

	# Process source-backed fields before default-only fields so default helpers
	# can attach to rows created for sl_column fields in the same group.
	sorted_fields_to_add = sorted(
		regular_fields,
		key=lambda f: 0 if (f.get("sl_column") or f.get("get_redis")) else 1,
	)

	for field_def in sorted_fields_to_add:
		try:
			doctype = field_def.get("doctype")
			fieldname = field_def.get("fieldname")
			child_row_fieldname = field_def.get("child_row_fieldname")
			
			# Validate required fields
			if not doctype or not fieldname:
				raise Exception(f"Field definition missing doctype or fieldname: {field_def}")
			
			# Debug logging
			make_log(
				f"Processing field addition: {doctype}.{fieldname} (child: {child_row_fieldname})",
				"DEBUG",
				APP_NAME
			)
			
			# Check if we have a cached docname for this doctype
			docname = created_docs_cache.get(doctype)
			
			if not docname:
				# Find the docname from existing mapping entries of same doctype
				existing_entries = frappe.get_all(
					"Sync Mapping Entry",
					filters={
						"parent": mapping_name,
						"mapping_doctype": doctype
					},
					limit=1,
					pluck="docname"
				)
				
				if existing_entries:
					docname = existing_entries[0]
					created_docs_cache[doctype] = docname
				else:
					# This is a new doctype that wasn't in the original mapping
					# We need to get or create the document first
					make_log(
						f"Creating new document for doctype {doctype} during reconciliation",
						"INFO",
						APP_NAME
					)
					
					# Get or create document with the field value
					new_doc = create_new_doc_for_reconciliation(
						doctype=doctype,
						field_def=field_def,
						fetched_obj=fetched_obj,
						instance=instance,
						field_vars_obj=field_vars_obj
					)
					
					if new_doc:
						docname = new_doc.name
						created_docs_cache[doctype] = docname
						# Don't continue here - we still need to create the mapping entry for this field
					else:
						raise Exception(f"Failed to create new document for doctype {doctype}")
			
			# Get the value based on mapping type
			field_value = get_field_value(
				field_def=field_def,
				fetched_obj=fetched_obj,
				instance=instance,
				field_vars_obj=field_vars_obj,
				mapping_name=mapping_name
			)
			
			# Determine whether this field has a trackable source column.
			# Fields with only "default" values are static and don't need a mapping entry
			# (they never change). Fields with sl_column OR get_redis DO need one.
			has_trackable_source = bool(field_def.get("sl_column") or field_def.get("get_redis"))
			
			# Handle child table fields
			if child_row_fieldname:
				make_log(
					f"Handling child table field: {doctype}.{fieldname}.{child_row_fieldname}",
					"DEBUG",
					APP_NAME
				)

				child_group_key = field_def.get("child_row_group_key")
				child_cache_key = (
					f"{doctype}:{docname}:{fieldname}:{child_group_key}" if child_group_key else None
				)
				
				# Find or create child row
				child_info = child_rows_cache.get(child_cache_key) if child_cache_key else None
				if not child_info:
					child_info = get_or_create_child_row(
						mapping_name=mapping_name,
						doctype=doctype,
						docname=docname,
						fieldname=fieldname,
						field_def=field_def,
						allow_create=has_trackable_source,
						resolved_value=field_value,
					)
					if child_cache_key and child_info:
						child_rows_cache[child_cache_key] = child_info
				
				if child_info:
					make_log(
						f"Got child info: {child_info}",
						"DEBUG",
						APP_NAME
					)
					
					# Update child row field
					frappe.db.set_value(
						child_info["child_doctype"],
						child_info["child_name"],
						child_row_fieldname,
						field_value
					)
					
					# Skip creating mapping entry for pure default fields (no sl_column, no get_redis)
					if not has_trackable_source:
						make_log(
							f"Skipping child mapping entry for {doctype}.{fieldname}.{child_row_fieldname}: no sl_column or get_redis (default/static value)",
							"DEBUG",
							APP_NAME
						)
						continue
					
					# Check if mapping entry already exists
					existing_entry = frappe.db.exists(
						"Sync Mapping Entry",
						{
							"parent": mapping_name,
							"mapping_doctype": doctype,
							"docname": docname,
							"fieldname": fieldname,
							"child_row_fieldname": child_row_fieldname,
							"selectline_column": field_def.get("sl_column")
						}
					)
					
					if not existing_entry:
						# Create mapping entry
						result = controller.insert_mapping_row(
							mapping_doc_name=mapping_name,
							data={
								"mapping_doctype": doctype,
								"docname": docname,
								"fieldname": fieldname,
								"child_row_fieldname": child_row_fieldname,
								"child_row_name": child_info["child_name"],
								"child_row_doctype": child_info["child_doctype"],
								"selectline_column": field_def.get("sl_column")
							}
						)
						make_log(
							f"Created child mapping entry for {doctype}.{fieldname}.{child_row_fieldname}: result={result}",
							"DEBUG",
							APP_NAME
						)
					else:
						make_log(
							f"Child mapping entry already exists: {existing_entry}",
							"DEBUG",
							APP_NAME
						)
				else:
					if not has_trackable_source:
						make_log(
							f"Skipping child default field {doctype}.{fieldname}.{child_row_fieldname}: "
							f"no existing mapped child row found",
							"DEBUG",
							APP_NAME
						)
						continue
					make_log(
						f"ERROR: Could not get or create child row for {doctype}.{fieldname}",
						"ERROR",
						APP_NAME
					)
					raise Exception(f"Failed to get or create child row for {doctype}.{fieldname}")
			else:
				# Update parent document field (even if None, to clear it if needed)
				frappe.db.set_value(doctype, docname, fieldname, field_value)
				
				# Skip creating mapping entry for pure default fields (no sl_column, no get_redis)
				# These are static values from JSON, not synced from SelectLine
				if not has_trackable_source:
					make_log(
						f"Skipping mapping entry for {doctype}.{fieldname}: no sl_column or get_redis (default/static value)",
						"DEBUG",
						APP_NAME
					)
					continue
				
				# Check if mapping entry already exists
				existing_entry = frappe.db.exists(
					"Sync Mapping Entry",
					{
						"parent": mapping_name,
						"mapping_doctype": doctype,
						"docname": docname,
						"fieldname": fieldname
					}
				)
				
				make_log(
					f"Field {doctype}.{fieldname}: existing_entry={existing_entry}, docname={docname}, field_value={field_value}",
					"DEBUG",
					APP_NAME
				)
				
				if not existing_entry:
					# Create mapping entry (ALWAYS create, even if value is None)
					# This ensures future updates will work when value changes from NULL to a value
					try:
						mapping_data = {
							"mapping_doctype": doctype,
							"docname": docname,
							"fieldname": fieldname,
							"selectline_column": field_def.get("sl_column")
						}
						make_log(
							f"Inserting mapping row for {doctype}.{fieldname} with data: {mapping_data}",
							"DEBUG",
							APP_NAME
						)
						result = controller.insert_mapping_row(
							mapping_doc_name=mapping_name,
							data=mapping_data
						)
						make_log(
							f"Created mapping entry for {doctype}.{fieldname}: result={result}",
							"DEBUG",
							APP_NAME
						)
					except Exception as insert_error:
						make_log(
							f"ERROR inserting mapping row for {doctype}.{fieldname}: {insert_error}",
							"ERROR",
							APP_NAME,
							with_traceback=True
						)
						raise
				else:
					make_log(
						f"Mapping entry already exists for {doctype}.{fieldname}: {existing_entry}",
						"DEBUG",
						APP_NAME
					)
			
			# Verify the mapping entry was created
			verify_entry = frappe.db.exists(
				"Sync Mapping Entry",
				{
					"parent": mapping_name,
					"mapping_doctype": doctype,
					"docname": docname,
					"fieldname": fieldname
				}
			)
			
			if not verify_entry:
				make_log(
					f"VERIFICATION FAILED: Mapping entry for {doctype}.{fieldname} not found after creation!",
					"ERROR",
					APP_NAME
				)
				raise Exception(f"Mapping entry verification failed for {doctype}.{fieldname}")
			else:
				make_log(
					f"VERIFIED: Mapping entry exists for {doctype}.{fieldname}: {verify_entry}",
					"DEBUG",
					APP_NAME
				)
			
			# Explicit commit after each field to ensure persistence
			frappe.db.commit()
			make_log(
				f"Committed transaction for {doctype}.{fieldname}",
				"DEBUG",
				APP_NAME
			)
			
			added_count += 1
			
		except Exception as e:
			failed_count += 1
			errors.append(f"{field_def.get('fieldname')}: {str(e)}")
			make_log(
				f"Failed to add field {field_def} to {mapping_name}: {e}",
				"ERROR",
				APP_NAME,
				with_traceback=True
			)
			continue
	
	frappe.db.commit()
	
	return {
		"added": added_count,
		"failed": failed_count,
		"errors": errors
	}


def normalize_item_child_tables(mapping_name: str) -> Dict:
	"""Cleanup duplicated/empty Item child rows and relink mapping entries."""
	rows_removed = 0
	rows_merged = 0
	errors: List[str] = []

	item_docnames = frappe.get_all(
		"Sync Mapping Entry",
		filters={
			"parent": mapping_name,
			"mapping_doctype": "Item",
			"docname": ["not in", ["", None]],
		},
		pluck="docname",
	)
	item_docnames = list(dict.fromkeys(item_docnames))

	for item_docname in item_docnames:
		try:
			# Barcode cleanup: remove empty rows, merge duplicate barcode values
			barcode_rows = frappe.get_all(
				"Item Barcode",
				filters={
					"parent": item_docname,
					"parenttype": "Item",
					"parentfield": "barcodes",
				},
				fields=["name", "barcode", "barcode_type", "idx"],
				order_by="idx asc",
			)
			barcode_survivors: Dict[str, Dict] = {}
			for row in barcode_rows:
				barcode_val = (row.get("barcode") or "").strip()
				if not barcode_val:
					delete_mapping_entries_for_child(
						mapping_name=mapping_name,
						docname=item_docname,
						fieldname="barcodes",
						child_row_name=row["name"],
					)
					frappe.delete_doc("Item Barcode", row["name"], ignore_permissions=True)
					rows_removed += 1
					continue

				if barcode_val not in barcode_survivors:
					barcode_survivors[barcode_val] = row
					continue

				survivor = barcode_survivors[barcode_val]
				candidate = row
				if (not survivor.get("barcode_type")) and candidate.get("barcode_type"):
					survivor, candidate = candidate, survivor
					barcode_survivors[barcode_val] = survivor

				relink_mapping_entries_for_child(
					mapping_name=mapping_name,
					docname=item_docname,
					fieldname="barcodes",
					old_child_row_name=candidate["name"],
					new_child_row_name=survivor["name"],
					new_child_doctype="Item Barcode",
				)
				frappe.delete_doc("Item Barcode", candidate["name"], ignore_permissions=True)
				rows_merged += 1

			# UOM cleanup: remove empty-uom rows, merge duplicate uom values
			uom_rows = frappe.get_all(
				"UOM Conversion Detail",
				filters={
					"parent": item_docname,
					"parenttype": "Item",
					"parentfield": "uoms",
				},
				fields=["name", "uom", "conversion_factor", "idx"],
				order_by="idx asc",
			)
			uom_survivors: Dict[str, Dict] = {}
			for row in uom_rows:
				uom_val = (row.get("uom") or "").strip()
				if not uom_val:
					delete_mapping_entries_for_child(
						mapping_name=mapping_name,
						docname=item_docname,
						fieldname="uoms",
						child_row_name=row["name"],
					)
					frappe.delete_doc("UOM Conversion Detail", row["name"], ignore_permissions=True)
					rows_removed += 1
					continue

				if uom_val not in uom_survivors:
					uom_survivors[uom_val] = row
					continue

				survivor = uom_survivors[uom_val]
				candidate = row
				if _score_conversion_factor(candidate.get("conversion_factor")) > _score_conversion_factor(
					survivor.get("conversion_factor")
				):
					survivor, candidate = candidate, survivor
					uom_survivors[uom_val] = survivor

				relink_mapping_entries_for_child(
					mapping_name=mapping_name,
					docname=item_docname,
					fieldname="uoms",
					old_child_row_name=candidate["name"],
					new_child_row_name=survivor["name"],
					new_child_doctype="UOM Conversion Detail",
				)
				frappe.delete_doc("UOM Conversion Detail", candidate["name"], ignore_permissions=True)
				rows_merged += 1

		except Exception as e:
			errors.append(f"{item_docname}: {e}")
			make_log(
				f"Failed to normalize child tables for item {item_docname} in {mapping_name}: {e}",
				"ERROR",
				APP_NAME,
				with_traceback=True,
			)

	return {
		"rows_removed": rows_removed,
		"rows_merged": rows_merged,
		"errors": errors,
	}


def relink_mapping_entries_for_child(
	mapping_name: str,
	docname: str,
	fieldname: str,
	old_child_row_name: str,
	new_child_row_name: str,
	new_child_doctype: str,
) -> None:
	entries = frappe.get_all(
		"Sync Mapping Entry",
		filters={
			"parent": mapping_name,
			"mapping_doctype": "Item",
			"docname": docname,
			"fieldname": fieldname,
			"child_row_name": old_child_row_name,
		},
		pluck="name",
	)
	for entry_name in entries:
		frappe.db.set_value("Sync Mapping Entry", entry_name, "child_row_name", new_child_row_name)
		frappe.db.set_value("Sync Mapping Entry", entry_name, "child_row_doctype", new_child_doctype)


def delete_mapping_entries_for_child(
	mapping_name: str,
	docname: str,
	fieldname: str,
	child_row_name: str,
) -> None:
	entries = frappe.get_all(
		"Sync Mapping Entry",
		filters={
			"parent": mapping_name,
			"mapping_doctype": "Item",
			"docname": docname,
			"fieldname": fieldname,
			"child_row_name": child_row_name,
		},
		pluck="name",
	)
	for entry_name in entries:
		frappe.delete_doc("Sync Mapping Entry", entry_name)


def _score_conversion_factor(value: Any) -> int:
	try:
		if value is None:
			return 0
		return 1 if float(value) != 0 else 0
	except Exception:
		return 0


def apply_field_removals(
	mapping_name: str,
	fields_to_remove: List[Dict],
	instance: str = ""
) -> Dict:
	"""
	Removes mapping entries for deleted fields.
	Also deletes documents if they're no longer referenced in any mapping.
	"""
	removed_count: int = 0
	errors: List[str] = []
	
	# Track which documents had all their fields removed
	docs_to_check: Dict[str, List[str]] = {}  # doctype -> [docnames]
	
	for field_info in fields_to_remove:
		try:
			doctype = field_info.get("mapping_doctype")
			fieldname = field_info.get("fieldname")
			child_row_fieldname = field_info.get("child_row_fieldname")
			docname = field_info.get("docname")
			
			# Track document for later check
			if doctype and docname:
				if doctype not in docs_to_check:
					docs_to_check[doctype] = []
				if docname not in docs_to_check[doctype]:
					docs_to_check[doctype].append(docname)
			
			# Find and delete mapping entry
			filters = {
				"parent": mapping_name,
				"mapping_doctype": doctype,
				"fieldname": fieldname
			}
			
			if child_row_fieldname:
				filters["child_row_fieldname"] = child_row_fieldname
			
			entries = frappe.get_all(
				"Sync Mapping Entry",
				filters=filters,
				pluck="name"
			)
			
			for entry_name in entries:
				frappe.delete_doc("Sync Mapping Entry", entry_name)
			
			removed_count += len(entries)
			
		except Exception as e:
			field_ref = field_info.get("fieldname", "unknown") if isinstance(field_info, dict) else "unknown"
			errors.append(f"{field_ref}: {str(e)}")
			make_log(
				f"Failed to remove field mapping {field_info} from {mapping_name}: {e}",
				"ERROR",
				APP_NAME,
				with_traceback=True
			)
			continue
	
	# Check for orphaned documents and delete them
	deleted_docs_count = 0
	for doctype, docnames in docs_to_check.items():
		for docname in docnames:
			try:
				# Check if document is still referenced in any other mapping
				other_mappings = frappe.get_all(
					"Sync Mapping Entry",
					filters={
						"mapping_doctype": doctype,
						"docname": docname,
						"parent": ["!=", mapping_name]  # Exclude current mapping
					},
					limit=1
				)
				
				if not other_mappings:
					# Document is not referenced anywhere else, safe to delete
					make_log(
						f"Document {doctype} '{docname}' is no longer referenced in any mapping. Deleting...",
						"INFO",
						APP_NAME
					)
					
					try:
						frappe.delete_doc(doctype, docname, ignore_permissions=True)
						deleted_docs_count += 1
						make_log(
							f"Successfully deleted orphaned document {doctype} '{docname}'",
							"INFO",
							APP_NAME
						)
					except Exception as delete_error:
						# Document might be linked to other documents (not through mappings)
						make_log(
							f"Could not delete {doctype} '{docname}': {delete_error}. Document may be linked elsewhere.",
							"WARNING",
							APP_NAME
						)
			except Exception as e:
				make_log(
					f"Error checking orphaned document {doctype} '{docname}': {e}",
					"ERROR",
					APP_NAME,
					with_traceback=True
				)
				continue
	
	frappe.db.commit()
	
	return {
		"removed": removed_count,
		"deleted_docs": deleted_docs_count,
		"errors": errors
	}


def apply_structural_changes(
	instance: str,
	mapping_name: str,
	structural_changes: List[Dict],
	fetched_obj: Dict
) -> Dict:
	"""
	Handles structural changes (e.g., sl_column → default, column changes).
	"""
	updated_count: int = 0
	errors: List[str] = []
	
	for change in structural_changes:
		try:
			new_def = change["new_def"]
			old_def = change["old_def"]
			
			doctype = new_def.get("doctype") or old_def.get("mapping_doctype")
			fieldname = new_def.get("fieldname")
			child_row_fieldname = new_def.get("child_row_fieldname") or old_def.get("child_row_fieldname")
			
			# Get new value
			field_vars_obj = FieldVars()
			new_value = get_field_value(
				field_def=new_def,
				fetched_obj=fetched_obj,
				instance=instance,
				field_vars_obj=field_vars_obj,
				mapping_name=mapping_name
			)
			
			# Handle child table fields differently
			if child_row_fieldname:
				# For child table fields, get the specific child row
				child_entries = frappe.get_all(
					"Sync Mapping Entry",
					filters={
						"parent": mapping_name,
						"mapping_doctype": doctype,
						"fieldname": fieldname,
						"child_row_fieldname": child_row_fieldname
					},
					fields=["docname", "child_row_name", "child_row_doctype"],
					limit=1
				)
				
				if not child_entries:
					raise Exception(f"No child row mapping entry found for {doctype}.{fieldname}.{child_row_fieldname}")
				
				child_info = child_entries[0]
				# Update child document directly
				if child_info.get("child_row_name") and child_info.get("child_row_doctype"):
					frappe.db.set_value(
						child_info["child_row_doctype"],
						child_info["child_row_name"],
						child_row_fieldname,
						new_value
					)
			else:
				# For parent fields, use the existing logic
				entries = frappe.get_all(
					"Sync Mapping Entry",
					filters={
						"parent": mapping_name,
						"mapping_doctype": doctype,
						"fieldname": fieldname
					},
					limit=1,
					pluck="docname"
				)
				
				if not entries:
					raise Exception(f"No mapping entry found for {doctype}.{fieldname}")
				
				docname = entries[0]
				# Update parent document field
				frappe.db.set_value(doctype, docname, fieldname, new_value)
			
			# Update mapping entry with new column reference if applicable
			if change.get("column_change"):
				# Find and update the mapping entry
				entry_filters = {
					"parent": mapping_name,
					"mapping_doctype": doctype,
					"fieldname": fieldname
				}
				if child_row_fieldname:
					entry_filters["child_row_fieldname"] = child_row_fieldname
				
				entry_name = frappe.db.exists("Sync Mapping Entry", entry_filters)
				if entry_name:
					frappe.db.set_value(
						"Sync Mapping Entry",
						entry_name,
						"selectline_column",
						new_def.get("sl_column")
					)
			
			updated_count += 1
			
		except Exception as e:
			errors.append(f"{change.get('field_key')}: {str(e)}")
			make_log(
				f"Failed to apply structural change {change} to {mapping_name}: {e}",
				"ERROR",
				APP_NAME,
				with_traceback=True
			)
			continue
	
	frappe.db.commit()
	
	return {
		"updated": updated_count,
		"errors": errors
	}


def get_field_value(
	field_def: Dict,
	fetched_obj: Dict,
	instance: str,
	field_vars_obj: FieldVars,
	mapping_name: str = ""
) -> Any:
	"""
	Gets the value for a field based on its mapping type.
	"""
	mapping_type = get_mapping_type(field_def)
	
	if mapping_type == "sl_column":
		col_name = field_def.get("sl_column")
		alt_key = field_def.get("alt_key")
		force_str = field_def.get("force_str_type") == 1
		fieldname = field_def.get("fieldname", "unknown")
		
		if alt_key and fetched_obj.get(alt_key):
			value = fetched_obj.get(alt_key)
		else:
			value = fetched_obj.get(col_name)
		
		make_log(
			f"get_field_value for {fieldname}: col={col_name}, alt_key={alt_key}, value={value}, type={type(value)}",
			"DEBUG",
			APP_NAME
		)
		
		value = apply_value_map(field_def, value)

		if force_str and value is not None:
			return str(value)
		return value
	
	elif mapping_type == "default":
		return apply_value_map(field_def, field_def.get("default"))
	
	elif mapping_type == "field_var":
		var_name = field_def.get("field_var")
		if var_name:
			return apply_value_map(field_def, field_vars_obj.get_field_var_value(var_name))
		return None
	
	elif mapping_type == "mapped_value":
		mapped_val = field_def.get("mapped_value")
		if not mapped_val or not isinstance(mapped_val, dict):
			return None
		
		table_name = mapped_val.get("table_name")
		sl_id_col = mapped_val.get("sl_id")
		target_doctype = mapped_val.get("doc_type")
		target_field = mapped_val.get("fieldname")
		force_str = field_def.get("force_str_type") == 1
		
		if not all([table_name, sl_id_col, target_doctype, target_field]):
			return None
		
		ref_id = fetched_obj.get(sl_id_col)
		if ref_id and table_name and target_doctype and target_field:
			ref_obj_id = controller.create_object_id(
				instance=instance,
				table_name=str(table_name),
				primary_key=str(ref_id)
			)
			value = controller.get_mapped_value(
				sl_id=ref_obj_id,
				doc_type=str(target_doctype),
				fieldname=str(target_field)
			)
			value = apply_value_map(field_def, value)

			if force_str and value is not None:
				return str(value)
			return value
		return None

	elif mapping_type == "get_redis":
		# get_redis resolves to a value that was set by a sibling doctype during import.
		# During reconcile there is no runtime redis_context, so we resolve the value
		# from the sibling doctype's mapping entry stored in the same Sync Mapping doc.
		# Example: link_name get_redis="erp_customer_id" → look up the Customer docname
		# from the mapping entries of the parent Sync Mapping.
		redis_key = field_def.get("get_redis")
		force_str = field_def.get("force_str_type") == 1
		if not redis_key or not mapping_name:
			return None

		# Find a mapping entry in the same Sync Mapping doc where the field was set
		# via set_redis with this key. We identify it by looking for the docname of
		# the sibling doctype — the convention is that set_redis stores the `name` field
		# of the sibling document. So we look for any non-skipped entry and return its docname.
		# The redis_key name (e.g. "erp_customer_id") tells us the context but not the column —
		# we resolve it by finding the mapping entry that originally wrote to `name`.
		sibling_entries = frappe.get_all(
			"Sync Mapping Entry",
			filters={
				"parent": mapping_name,
				"fieldname": "name",
				"docname": ["not in", ["", None]],
			},
			fields=["docname", "mapping_doctype"],
			limit=1
		)
		if sibling_entries:
			value = sibling_entries[0]["docname"]
			value = apply_value_map(field_def, value)
			if force_str and value is not None:
				return str(value)
			return value

		return None
	
	return None


def get_or_create_child_row(
	mapping_name: str,
	doctype: str,
	docname: str,
	fieldname: str,
	field_def: Dict,
	allow_create: bool = True,
	resolved_value: Any = None,
) -> Optional[Dict]:
	"""
	Finds or creates a child table row for adding new fields.
	Returns dict with child_doctype and child_name.
	"""
	try:
		# Get child doctype from field options
		meta = frappe.get_meta(doctype)
		child_doctype = meta.get_field(fieldname).options
		
		if not child_doctype:
			raise Exception(f"Could not determine child doctype for {doctype}.{fieldname}")
		
		# For source-mapped child fields, reuse the exact mapped child row
		# (same field + child field + source column). This keeps repeated mappings
		# like uoms/conversion_factor for GEBINDE_1, GEBINDE_2, ... separated.
		child_row_fieldname = field_def.get("child_row_fieldname")
		source_column = field_def.get("sl_column")
		if child_row_fieldname and source_column:
			existing_children = frappe.get_all(
				"Sync Mapping Entry",
				filters={
					"parent": mapping_name,
					"mapping_doctype": doctype,
					"fieldname": fieldname,
					"child_row_fieldname": child_row_fieldname,
					"selectline_column": source_column,
				},
				fields=["child_row_name", "child_row_doctype"],
				limit=1,
			)
			if existing_children and existing_children[0].get("child_row_name"):
				return {
					"child_doctype": existing_children[0]["child_row_doctype"],
					"child_name": existing_children[0]["child_row_name"],
				}

			# Fallback: no Sync Mapping Entry found for this sl_column child field,
			# but the child row may already exist on the document (e.g. mapping entry
			# was never stored during import, or was deleted). Check the actual
			# document to avoid creating a duplicate child row.
			if docname and resolved_value is not None:
				parent_doc = frappe.get_doc(doctype, docname)
				existing_child_rows = parent_doc.get(fieldname) or []
				for row in existing_child_rows:
					if str(row.get(child_row_fieldname) or "") == str(resolved_value):
						return {
							"child_doctype": row.doctype,
							"child_name": row.name,
						}

		# For default-only child fields (no mapping entry), try to reuse a row with the
		# same value to avoid creating duplicates on repeated reconciliation runs.
		default_value = field_def.get("default")
		if child_row_fieldname and default_value is not None:
			group_columns = field_def.get("child_group_sl_columns") or []
			if group_columns:
				sibling_entries = frappe.get_all(
					"Sync Mapping Entry",
					filters={
						"parent": mapping_name,
						"mapping_doctype": doctype,
						"docname": docname,
						"fieldname": fieldname,
						"selectline_column": ["in", group_columns],
						"child_row_name": ["not in", ["", None]],
					},
					fields=["child_row_name", "child_row_doctype"],
					limit=1,
				)
				if sibling_entries:
					return {
						"child_doctype": sibling_entries[0]["child_row_doctype"],
						"child_name": sibling_entries[0]["child_row_name"],
					}

			parent_doc = frappe.get_doc(doctype, docname)
			existing_child_rows = parent_doc.get(fieldname) or []
			for row in existing_child_rows:
				if row.get(child_row_fieldname) == default_value:
					return {
						"child_doctype": row.doctype,
						"child_name": row.name
					}
		
		# For get_redis fields (no sl_column, no default), try to find an existing
		# child row by matching the resolved value against the actual document.
		# This prevents duplicate child rows when reconciliation runs after import.
		if child_row_fieldname and resolved_value is not None and not source_column and default_value is None:
			parent_doc = frappe.get_doc(doctype, docname)
			existing_child_rows = parent_doc.get(fieldname) or []
			for row in existing_child_rows:
				if str(row.get(child_row_fieldname) or "") == str(resolved_value):
					return {
						"child_doctype": row.doctype,
						"child_name": row.name
					}

		# Do NOT reuse arbitrary existing child rows that have no mapping entry.
		# This preserves system/default/manual rows (e.g. Item default UOM) that are
		# not managed by Sync Mapping entries.
		if not allow_create:
			return None
		
		# Need to create a new child row
		child_name = frappe.generate_hash(length=8)
		
		new_child = frappe.get_doc({
			"doctype": child_doctype,
			"parenttype": doctype,
			"parent": docname,
			"name": child_name,
			"parentfield": fieldname
		})
		
		new_child.flags.name_set = True
		
		# Insert with ignore_mandatory=True to allow creating child rows
		# without all required fields initially. Fields will be set afterward.
		new_child.insert(
			ignore_permissions=True,
			ignore_mandatory=True
		)
		
		return {
			"child_doctype": child_doctype,
			"child_name": child_name
		}
		
	except Exception as e:
		make_log(
			f"Failed to get/create child row for {doctype}.{fieldname}: {e}",
			"ERROR",
			APP_NAME,
			with_traceback=True
		)
		return None


def parse_object_id(obj_id: str) -> Dict:
	"""
	Parses a Selectline object ID into components.
	Format: instance:table:primary_key
	"""
	parts = obj_id.split(":")
	if len(parts) != 3:
		raise Exception(f"Invalid object ID format: {obj_id}")
	
	return {
		"instance": parts[0],
		"table": parts[1],
		"primary_key": parts[2]
	}


def resolve_table_name_for_mapping(instance: str, mapping_doc: Document, table_from_id: str) -> str:
	"""Resolve the actual source table name for a mapping.

	Backwards compatibility: older selectline_id values may store "<type>_<table>"
	instead of the raw table name.
	"""
	# Modified by PIT Agent Dev 1 - 2026-03-30: Resolve legacy type-prefixed table names during reconciliation.
	instance_doc: Document = frappe.get_doc("Sync Instance", instance)
	candidates: List[str] = []
	for row in instance_doc.table_mapping:
		if row.type == mapping_doc.type and row.table_name:
			candidates.append(str(row.table_name))

	if not candidates:
		return table_from_id

	if table_from_id in candidates:
		return table_from_id

	if "_" in table_from_id:
		stripped = table_from_id.split("_", 1)[1]
		if stripped in candidates:
			make_log(
				f"Resolved legacy table name '{table_from_id}' to '{stripped}' for mapping {mapping_doc.name}",
				"INFO",
				APP_NAME,
			)
			return stripped

	resolved = candidates[0]
	if resolved != table_from_id:
		make_log(
			f"Resolved table name '{table_from_id}' to '{resolved}' for mapping {mapping_doc.name}",
			"INFO",
			APP_NAME,
		)
	return resolved


def get_table_columns(instance: str, table_name: str, driver: str) -> Optional[set]:
	"""
	Returns the set of column names that actually exist on a source table.
	Used to filter out stale/invalid columns before building a SQL query.
	Returns None if the schema cannot be determined (non-fatal: caller skips validation).
	"""
	try:
		if driver == "p4d":
			sql = f"SELECT COLUMN_NAME FROM _USER_COLUMNS WHERE TABLE_NAME = '{table_name}'"
		else:
			sql = f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{table_name}'"

		conn = controller.db_connect(instance=instance)
		if conn is None:
			return None

		try:
			cur = conn.cursor()
			cur.execute(sql)
			rows = cur.fetchall()
			cur.close()
		finally:
			try:
				conn.close()
			except Exception:
				pass

		# rows are tuples; first element is the column name
		return {row[0] for row in rows} if rows else None

	except Exception as e:
		make_log(
			f"Could not fetch column list for {table_name}: {e}",
			"WARNING",
			APP_NAME,
		)
		return None


def fetch_source_data(
	instance: str,
	mapping_doc: Document,
	id_data: Dict,
	new_fields: Optional[List[Dict]] = None
) -> Optional[Dict]:
	"""
	Fetches current data from SelectLine for a mapping.
	Includes columns from existing mapping AND new fields being added.
	"""
	try:
		# Get table name from id_data and resolve legacy type-prefixed names
		table_name_from_id = id_data.get("table")
		table_name = resolve_table_name_for_mapping(instance=instance, mapping_doc=mapping_doc, table_from_id=table_name_from_id)
		primary_key = id_data.get("primary_key")
		
		# Get primary key column from mapping
		primary_key_col = mapping_doc.primary_key_column
		if not primary_key_col:
			raise Exception(f"No primary key column in mapping {mapping_doc.name}")
		
		# Get DB schema
		schema = frappe.db.get_value("Sync Instance", instance, "schema") or ""
		schema_dot = "." if schema else ""
		
		# Get all columns we need from existing mapping entries
		# Exclude child table fields (child_row_fieldname set) - those come from a different table via multiple_query
		entries = controller.get_mapping_table_data(mapping_doc.name)
		columns = list(set([e.get("selectline_column") for e in entries if e.get("selectline_column") and not e.get("child_row_fieldname")]))
		
		# Add columns from new fields being added (for reconciliation)
		if new_fields:
			for field in new_fields:
				if field.get("sl_column"):
					columns.append(field["sl_column"])
		
		# Remove duplicates while preserving order
		columns = list(dict.fromkeys(columns))

		# Validate columns against the actual table schema and drop any that don't exist.
		# This protects against stale mapping entries referencing columns from a different
		# table (e.g. LIEFERANTENNR from Artikel_Lieferant stored on an Item mapping entry)
		# or columns that were removed / renamed in the source database.
		# Comparison is case-insensitive to handle mixed-case 4D column names.
		# SQL expressions (subqueries starting with '(', CAST expressions, etc.) are kept
		# as-is since they are valid SELECT expressions, not plain column names.
		driver = frappe.db.get_value("Sync Instance", instance, "driver") or "pymssql"
		valid_table_columns = get_table_columns(instance=instance, table_name=table_name, driver=driver)
		if valid_table_columns:
			valid_upper = {c.upper() for c in valid_table_columns}
			is_sql_expr = lambda c: c.strip().startswith("(") or c.strip().upper().startswith("CAST(")
			invalid = [c for c in columns if not is_sql_expr(c) and c.upper() not in valid_upper]
			if invalid:
				make_log(
					f"Skipping {len(invalid)} column(s) not present in {table_name}: {invalid}",
					"WARNING",
					APP_NAME,
				)
			columns = [c for c in columns if is_sql_expr(c) or c.upper() in valid_upper]
		
		# Add timestamp column from table mapping (not from Sync Instance)
		# Get the table mapping row for this mapping type
		instance_doc = frappe.get_doc("Sync Instance", instance)
		ts_col = None
		for table_mapping_row in instance_doc.table_mapping:
			if table_mapping_row.type == mapping_doc.type:
				ts_col = table_mapping_row.timestamp_column_name
				break
		
		if ts_col:
			columns.append(ts_col)
		
		if not columns:
			raise Exception(f"No columns to fetch for mapping {mapping_doc.name}")
		
		col_string = ",\n".join(columns)
		
		make_log(
			f"Fetching columns for {mapping_doc.name}: {columns}",
			"DEBUG",
			APP_NAME
		)
		
		# Build SQL using centralized helper function
		sql = controller.make_sql_string_single_row(
			instance=instance,
			table_name=table_name,
			columns=columns,
			primary_key_col=primary_key_col,
			primary_key_val=primary_key,
			schema=schema
		)
		
		# Modified by PIT Agent Dev 1 - 2026-03-30: Retry 4D fetches to handle transient driver failures under parallel reconcile jobs.
		# Modified by PIT Agent Dev 1 - 2026-04-15: Increased retry count to 5 and delay to 1.0s per attempt
		# to better handle connection saturation when many reconcile jobs run in parallel against the 4D server.
		result = None
		max_attempts = 5 if driver == "p4d" else 1
		for attempt in range(1, max_attempts + 1):
			result = controller.fetch_data(instance=instance, sql=sql)
			if result:
				break
			if attempt < max_attempts:
				make_log(
					f"Retry fetch ({attempt}/{max_attempts}) for {mapping_doc.selectline_id}",
					"WARNING",
					APP_NAME,
				)
				time.sleep(1.0 * attempt)
		
		make_log(
			f"Fetch result for {mapping_doc.name}: {result}",
			"DEBUG",
			APP_NAME
		)
		
		if not result or len(result) == 0:
			make_log(
				f"No data returned for {mapping_doc.selectline_id} - record may not exist in source database",
				"WARNING",
				APP_NAME
			)
			return None
		
		if len(result) > 1:
			raise Exception(f"Got {len(result)} rows when expecting 1")
		
		return result[0]
		
	except Exception as e:
		make_log(
			f"Failed to fetch source data for {mapping_doc.selectline_id}: {e}\nSQL: {sql}",
			"ERROR",
			APP_NAME,
			with_traceback=True
		)
		return None


def get_current_json_mapping(instance_doc: Document, mapping_type: str) -> Optional[List[Dict]]:
	"""
	Gets the current JSON mapping definition for a type from the instance.
	"""
	try:
		for row in instance_doc.table_mapping:
			if row.type == mapping_type:
				if row.mapping:
					return json.loads(row.mapping)
		return None
	except Exception as e:
		make_log(
			f"Failed to get JSON mapping for type {mapping_type}: {e}",
			"ERROR",
			APP_NAME
		)
		return None


def create_new_doc_for_reconciliation(
	doctype: str,
	field_def: Dict,
	fetched_obj: Dict,
	instance: str,
	field_vars_obj: FieldVars
) -> Optional[Document]:
	"""
	Creates a new document during reconciliation for doctypes that weren't in the original mapping.
	If document already exists (by name), returns the existing document instead.
	
	Args:
		doctype: The DocType to create
		field_def: Field definition for the first field
		fetched_obj: Data from SelectLine
		instance: Sync Instance name
		field_vars_obj: FieldVars object for variable resolution
	
	Returns:
		The newly created or existing Document, or None if failed
	"""
	try:
		# Get the field value first to determine document name
		fieldname = field_def.get("fieldname")
		field_value = get_field_value(
			field_def=field_def,
			fetched_obj=fetched_obj,
			instance=instance,
			field_vars_obj=field_vars_obj,
			mapping_name=""
		)
		
		# Check if document with this name already exists
		# For many DocTypes (like UOM), the name is the same as the field value
		potential_name = str(field_value) if field_value else None
		
		if potential_name:
			existing_doc = frappe.db.exists(doctype, potential_name)
			if existing_doc:
				make_log(
					f"Using existing {doctype} document '{potential_name}' during reconciliation",
					"INFO",
					APP_NAME
				)
				return frappe.get_doc(doctype, potential_name)
			
			# Also check if there's a document with this value in the specific field
			# This handles cases where name != field value
			existing_by_field = frappe.get_all(
				doctype,
				filters={fieldname: field_value},
				limit=1,
				pluck="name"
			)
			if existing_by_field:
				make_log(
					f"Using existing {doctype} document '{existing_by_field[0]}' with {fieldname}='{field_value}' during reconciliation",
					"INFO",
					APP_NAME
				)
				return frappe.get_doc(doctype, existing_by_field[0])
		
		# Create new document if not found
		new_doc = frappe.new_doc(doctype)
		
		# Set the field value
		new_doc.set(fieldname, field_value)
		
		# Set any default fields that are required
		meta = frappe.get_meta(doctype)
		for df in meta.fields:
			if df.reqd and not new_doc.get(df.fieldname):
				if df.default:
					new_doc.set(df.fieldname, df.default)
				elif df.fieldtype == "Data":
					new_doc.set(df.fieldname, f"{doctype} {fetched_obj.get('ID', 'Unknown')}")
		
		# Insert the document with ignore_if_duplicate just in case
		new_doc.insert(
			ignore_permissions=True,
			ignore_mandatory=True,
			ignore_links=True,
			ignore_if_duplicate=True
		)
		
		frappe.db.commit()
		
		make_log(
			f"Created new {doctype} document '{new_doc.name}' during reconciliation",
			"INFO",
			APP_NAME
		)
		
		return new_doc
		
	except Exception as e:
		make_log(
			f"Failed to create new {doctype} document during reconciliation: {e}",
			"ERROR",
			APP_NAME,
			with_traceback=True
		)
		return None
