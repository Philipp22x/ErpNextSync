import json
import re
import uuid
from pprint import pprint
import frappe
import datetime
from frappe.model.document import Document

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller
from pit_erpnextsync.scripts.classes.field_vars import FieldVars
from pit_erpnextsync.scripts.data_import import format_phone_number


@frappe.whitelist()
def run_bulk_update(instance: str, types_str: str, ignore_ts = False) -> str:
    """Entry point - enqueues the actual update as a long-running background job.

    Returns:
        str: The job_id of the enqueued background job.
    """
    job_id = f"pes_update_main:{uuid.uuid4().hex[:8]}"
    frappe.enqueue(
        "pit_erpnextsync.scripts.update._run_bulk_update",
        queue="long",
        timeout=3600,
        job_id=job_id,
        instance=instance,
        types_str=types_str,
        ignore_ts=ignore_ts
    )
    return job_id


def _run_bulk_update(instance: str, types_str: str, ignore_ts = False) -> None:
    """Actual update logic - runs as a long background job."""
    # Convert ignore_ts to boolean (Frappe may pass it as string)
    if isinstance(ignore_ts, str):
        ignore_ts = ignore_ts.lower() in ('true', '1', 'yes')
    else:
        ignore_ts = bool(ignore_ts)
    
    make_log(f"run_bulk_update called with ignore_ts={ignore_ts} (type: {type(ignore_ts)})", "INFO", controller.APP_NAME)

    # before import hooks
    controller.trigger_hooks(instance=instance, before_after="before", import_update="update")

    # get instance doc
    try:
        instance_doc: Document = frappe.get_doc("Sync Instance", instance)
        if not instance_doc:
            raise Exception()

    except Exception as e:
        make_log(f"Could not get instance doc {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return None

    # convert types str to a list (handles JSON arrays, CSV strings, None, and "")
    arg_types_list: list = controller.parse_types_input(types_str)

    types_list: list = []

    # if no types are given get all types from instance
    if arg_types_list == []:
        for row in instance_doc.table_mapping:
            types_list.append(row.type)
    else:
        types_list = arg_types_list

    # Get the current runs value and batch size
    instance_values = frappe.get_value("Sync Instance", instance, ["runs", "import_batch_size"], as_dict=True)
    run_number = instance_values.get("runs") or 1
    batch_size: int = max(int(instance_values.get("import_batch_size") or 10), 1)

    all_job_ids: list = []

    for current_type in types_list:
        mappings_list: list = frappe.get_all(
            "Sync Mapping",
            filters={
                "selectline_db_instance": instance,
                "enable": 1,
                "type": current_type
            },
            pluck="name"
        )

        if not mappings_list:
            continue

        # Collect valid (mapping_name, id_data) pairs
        mapping_items: list = []
        for mapping_name in mappings_list:
            obj_id: str = frappe.db.get_value("Sync Mapping", mapping_name, "selectline_id")
            if not obj_id:
                make_log(f"No object id in mapping {mapping_name}", "ERROR", controller.APP_NAME)
                continue
            id_data: dict = get_id_data(obj_id=obj_id)
            if not id_data:
                make_log(f"Could not get data from object id {obj_id}", "ERROR", controller.APP_NAME)
                continue
            mapping_items.append({"mapping_name": mapping_name, "id_data": id_data})

        # Split into batches and enqueue one job per batch
        type_job_ids: list = []
        for i in range(0, len(mapping_items), batch_size):
            batch = mapping_items[i:i + batch_size]
            job_id = f"pes:{run_number}:{uuid.uuid4().hex[:16]}"
            frappe.enqueue(
                "pit_erpnextsync.scripts.update.update_batch",
                queue="long",
                timeout=600 * len(batch),
                job_id=job_id,
                instance=instance,
                batch_items=batch,
                run_number=run_number,
                ignore_ts=ignore_ts
            )
            type_job_ids.append(job_id)

        make_log(
            f"Enqueued {len(type_job_ids)} batch jobs for type {current_type} "
            f"({len(mapping_items)} mappings, batch_size={batch_size}, run_number={run_number})",
            "INFO",
            controller.APP_NAME,
        )

        all_job_ids.extend(type_job_ids)

    make_log(
        f"Enqueued {len(all_job_ids)} total batch jobs for instance {instance} (run_number={run_number})",
        "INFO",
        controller.APP_NAME,
    )

    # Wait for all batch jobs to complete before triggering after-hooks,
    # mirroring _run_import's wait_for_jobs behavior.
    if all_job_ids:
        make_log(
            f"Waiting for {len(all_job_ids)} update batch jobs to complete...",
            "INFO",
            controller.APP_NAME,
        )
        controller.wait_for_jobs(all_job_ids)
        make_log(
            f"All update batch jobs completed for instance {instance}",
            "INFO",
            controller.APP_NAME,
        )

    # Commit to close the current transaction so the after-hook sees data committed
    # by batch jobs (REPEATABLE READ isolation would otherwise keep a stale snapshot).
    frappe.db.commit()

    # after update hooks
    controller.trigger_hooks(instance=instance, before_after="after", import_update="update")
    make_log(f"Update dispatch completed for instance {instance}", "INFO", controller.APP_NAME)

    return None


def update_batch(instance: str, batch_items: list, run_number: int, ignore_ts: bool = False) -> None:
    """Background job: processes a batch of mappings serially.
    Each item in batch_items is a dict with keys: mapping_name, id_data.
    """
    for item in batch_items:
        check_timestamp(
            instance=instance,
            id_data=item["id_data"],
            mapping_name=item["mapping_name"],
            run_number=run_number,
            skip_job_update=True,
            ignore_ts=ignore_ts
        )
    controller.update_jobs(instance=instance, skip_hooks=True)


# fetch timespamp of db data object -> if changed call update
def check_timestamp(instance: str, id_data: dict, mapping_name: str, run_number: int = None, skip_job_update: bool = False, ignore_ts = False) -> None:
    # Convert ignore_ts to boolean (Frappe may pass it as string from job queue)
    if isinstance(ignore_ts, str):
        ignore_ts = ignore_ts.lower() in ('true', '1', 'yes')
    else:
        ignore_ts = bool(ignore_ts)
    
    make_log(f"check_timestamp called for {mapping_name} with ignore_ts={ignore_ts} (type: {type(ignore_ts)})", "INFO", controller.APP_NAME)

    try:
        table_name_from_id: str = id_data.get("table")
        table_name: str = resolve_table_name_for_mapping(
            instance=instance,
            mapping_name=mapping_name,
            table_from_id=table_name_from_id,
        )
        primary_key: str = id_data.get("primary_key")

        # validate id data
        if not instance or not table_name or not primary_key:
            make_log(f"Some id data is missing: {id_data}", "ERROR", controller.APP_NAME)
            return

        # If ignore_ts is True, skip timestamp check and directly update
        if ignore_ts:
            make_log(f"Timestamp check ignored for {mapping_name}, proceeding with update", "INFO", controller.APP_NAME)
            if skip_job_update:
                # Already inside a batch job — call directly to stay within the batch
                update_mapping(instance=instance, id_data=id_data, mapping_name=mapping_name, run_number=run_number)
            else:
                # Called standalone — enqueue as its own job
                job_id = f"pes:{run_number}:{uuid.uuid4().hex[:16]}" if run_number else None
                frappe.enqueue(
                    "pit_erpnextsync.scripts.update.update_mapping",
                    queue="long",
                    timeout=600,
                    job_id=job_id,
                    instance=instance,
                    id_data=id_data,
                    mapping_name=mapping_name,
                    run_number=run_number
                )
                controller.update_jobs(instance=instance, skip_hooks=True)
            return None

        # get db schema from instance
        schema: str = frappe.db.get_value("Sync Instance", instance, "schema")
        shema_dot: str = "." if schema else ""

        # get the column name of the primary key
        primary_key_column: str = frappe.db.get_value("Sync Mapping", mapping_name, "primary_key_column")
        if not primary_key_column:
            return "test1"

        # get the column name where the timestamp is stored on db from table mapping
        mapping_type: str = frappe.db.get_value("Sync Mapping", mapping_name, "type")
        instance_doc = frappe.get_doc("Sync Instance", instance)
        ts_col: str = None
        for table_mapping_row in instance_doc.table_mapping:
            if table_mapping_row.type == mapping_type:
                ts_col = table_mapping_row.timestamp_column_name
                break
        if not ts_col:
            make_log(f"No timestamp column configured for {mapping_name}, proceeding with update", "INFO", controller.APP_NAME)
            job_id = f"pes:{run_number}:{uuid.uuid4().hex[:16]}" if run_number else None
            frappe.enqueue(
                "pit_erpnextsync.scripts.update.update_mapping",
                queue="long",
                timeout=600,
                job_id=job_id,
                instance=instance,
                id_data=id_data,
                mapping_name=mapping_name,
                run_number=run_number
            )
            if not skip_job_update:
                controller.update_jobs(instance=instance, skip_hooks=True)
            return None

        # get the timestamp column type from mapping
        time_stamp_type: str = frappe.db.get_value("Sync Mapping", mapping_name, "time_stamp_type") or "datetime"

        # Build SQL using helper function
        sql: str = controller.make_sql_string_single_row(
            instance=instance,
            table_name=table_name,
            columns=[ts_col],
            primary_key_col=primary_key_column,
            primary_key_val=primary_key,
            schema=schema
        )

        # result of fetching timestamp from db
        try:
            fetched_ts: list = controller.fetch_data(instance=instance, sql=sql)
        except Exception as fetch_err:
            make_log(f"SQL execution failed for {mapping_name}: {fetch_err}\nSQL: {sql}", "ERROR", controller.APP_NAME)
            raise

        if not fetched_ts:
            make_log(f"DEBUG: fetched_ts is empty or None: {fetched_ts}, type: {type(fetched_ts)}", "ERROR", controller.APP_NAME)
            raise Exception(f"Could not fetch valid timestamp data - fetched_ts is empty or None: {fetched_ts}")
        
        if type(fetched_ts) != list:
            make_log(f"DEBUG: fetched_ts is not a list: {type(fetched_ts)}", "ERROR", controller.APP_NAME)
            raise Exception(f"Could not fetch valid timestamp data - fetched_ts is not a list: {type(fetched_ts)}")
        
        # Debug: log the keys in the first row
        if fetched_ts and len(fetched_ts) > 0:
            make_log(f"DEBUG: First row keys: {list(fetched_ts[0].keys()) if fetched_ts[0] else 'empty'}", "INFO", controller.APP_NAME)
            make_log(f"DEBUG: Looking for ts_col='{ts_col}' in row: {fetched_ts[0]}", "INFO", controller.APP_NAME)

        if len(fetched_ts) > 1:
            raise Exception("Got more than one timestamp")

        # convert timestamp value based on column type
        raw_timestamp = fetched_ts[0].get(ts_col)
        timestamp_str: str = controller.convert_timestamp_to_string(raw_timestamp, time_stamp_type)
        
        if not timestamp_str:
            raise Exception(f"Invalid timestamp result: {timestamp_str} (raw: {raw_timestamp}, type: {time_stamp_type})")

        # get stored timestamp in mapping
        mapped_timestamp = frappe.db.get_value("Sync Mapping", mapping_name, "db_time_stamp")
        if not mapped_timestamp:
            raise Exception(f"No timestamp in mapping {mapping_name}")

        # check timestamp strings
        if timestamp_str == mapped_timestamp:
            make_log(f"Mapping {mapping_name} up to date", "INFO", controller.APP_NAME)
            if not skip_job_update:
                controller.update_jobs(instance=instance, skip_hooks=True)
            return None
        else:
            job_id = f"pes:{run_number}:{uuid.uuid4().hex[:16]}" if run_number else None
            frappe.enqueue(
                "pit_erpnextsync.scripts.update.update_mapping",
                queue="long",
                timeout=600,
                job_id=job_id,
                instance=instance,
                id_data=id_data,
                mapping_name=mapping_name,
                run_number=run_number
            )
            if not skip_job_update:
                controller.update_jobs(instance=instance, skip_hooks=True)
            return None

    except Exception as e:
        make_log(f"Could not get timestamp from source db for {id_data}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        if not skip_job_update:
            controller.update_jobs(instance=instance)
        return None


# update single mapping / called from timestamp check
def update_mapping(instance: str, id_data: dict, mapping_name: str, run_number: int = None) -> None:
    make_log(f"run update_mapping()", "ERROR", controller.APP_NAME)
    try:
        # get mapping doc
        mapping_doc: Document = frappe.get_doc("Sync Mapping", mapping_name)
        if not mapping_doc:
            raise Exception(f"mapping_doc is {mapping_doc}")

        # get mapping table data
        mapping_table_data: list = controller.get_mapping_table_data(mapping_name=mapping_name)
        if not mapping_table_data:
            raise Exception("Could not get mapping table data")

        # get timestamp column name from table mapping and load mapping JSON
        instance_doc = frappe.get_doc("Sync Instance", instance)
        time_stamp_col_name: str = None
        mapping_json: list = []
        table_mapping_row = None
        for tm_row in instance_doc.table_mapping:
            if tm_row.type == mapping_doc.type:
                time_stamp_col_name = tm_row.timestamp_column_name
                mapping_json = json.loads(tm_row.mapping)
                table_mapping_row = tm_row
                break

        # Build set of sl_columns that belong to multiple_query child table
        # definitions — these come from a separate source table, NOT from the
        # parent table, so they must be excluded from the parent SQL query.
        # Keyed by column name (not fieldname) so that a non-mq definition
        # sharing the same fieldname as an mq definition is not wrongly excluded.
        mq_sl_columns: set = set()
        for mapped_doctype in mapping_json:
            for field in mapped_doctype.get("fields", []):
                if field.get("multiple_query") and field.get("table_fields"):
                    for tf in field.get("table_fields", []):
                        if tf.get("sl_column"):
                            mq_sl_columns.add(tf["sl_column"])
                        if tf.get("alt_key"):
                            mq_sl_columns.add(tf["alt_key"])
                        if tf.get("mapped_value") and tf["mapped_value"].get("sl_id"):
                            mq_sl_columns.add(tf["mapped_value"]["sl_id"])

        # Remove columns that are also used by non-multiple_query fields (parent
        # fields and non-mq child table fields). These columns come from the
        # parent source table and must remain in the parent SQL even if the same
        # column is also used by an mq child field (which fetches separately from
        # the child source table). Without this, a parent field sharing a column
        # name with an mq child field would have its column excluded from the
        # parent SQL, causing fetched_data[0].get(col) to return None and
        # overwriting the ERPNext field with None.
        non_mq_sl_columns: set = set()
        for mapped_doctype in mapping_json:
            for field in mapped_doctype.get("fields", []):
                if field.get("multiple_query"):
                    continue
                if field.get("sl_column"):
                    non_mq_sl_columns.add(field["sl_column"])
                if field.get("mapped_value") and field["mapped_value"].get("sl_id"):
                    non_mq_sl_columns.add(field["mapped_value"]["sl_id"])
                for tf in field.get("table_fields", []):
                    if tf.get("sl_column"):
                        non_mq_sl_columns.add(tf["sl_column"])
                    if tf.get("mapped_value") and tf["mapped_value"].get("sl_id"):
                        non_mq_sl_columns.add(tf["mapped_value"]["sl_id"])
        mq_sl_columns -= non_mq_sl_columns

        # Filter out invalid/error columns (columns starting with _ are error codes)
        # and multiple_query child columns (those come from a different source table).
        # Non-multiple_query child columns ARE included (they come from the parent table).
        valid_columns = [
            d["selectline_column"]
            for d in mapping_table_data
            if d.get("selectline_column")
            and not d["selectline_column"].startswith("_")
            and d["selectline_column"] not in mq_sl_columns
        ]
        col_string = ",\n".join(dict.fromkeys(valid_columns))
        # Build columns list
        columns = [c.strip() for c in col_string.split(",") if c.strip()]
        if time_stamp_col_name:
            columns.append(time_stamp_col_name)

        # Ensure the parent row contains every column referenced by multiple_query
        # child conditions ({Placeholder} syntax) plus the primary key. Otherwise
        # fetch_multiple_rows cannot replace the placeholder and the raw "{...}"
        # ends up in the child SQL, causing a syntax error.
        mq_condition_columns: set = set()
        for mapped_doctype in mapping_json:
            for field in mapped_doctype.get("fields", []):
                mq_condition = field.get("multiple_query_condition")
                if field.get("multiple_query") and mq_condition:
                    mq_condition_columns.update(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", mq_condition))
        primary_key_col_name: str = mapping_doc.primary_key_column
        for needed_col in mq_condition_columns | ({primary_key_col_name} if primary_key_col_name else set()):
            if needed_col and needed_col not in columns:
                columns.append(needed_col)


        # Build phone + value_map + mapped_value lookups from mapping JSON
        phone_field_lookup: dict = {}
        value_map_lookup: dict = {}
        mapped_value_lookup: dict = {}
        for mapped_doctype in mapping_json:
            doctype = mapped_doctype.get("doctype")
            for field in mapped_doctype.get("fields", []):
                fieldname = field.get("fieldname")
                if field.get("is_phone_no") == 1:
                    key = f"{doctype}:{fieldname}"
                    phone_field_lookup[key] = {
                        "country_code": field.get("phone_country_code", "AT")
                    }

                if field.get("value_map") and field.get("sl_column"):
                    key = f"{doctype}:{fieldname}:{field.get('sl_column')}"
                    value_map_lookup[key] = {
                        "map": field.get("value_map") or {},
                        "default": field.get("value_map_default")
                    }

                if field.get("mapped_value") and field.get("sl_column"):
                    mv = field.get("mapped_value")
                    key = f"{doctype}:{fieldname}:{field.get('sl_column')}"
                    mapped_value_lookup[key] = {
                        "table_name": mv.get("table_name"),
                        "sl_id": mv.get("sl_id"),
                        "doc_type": mv.get("doc_type"),
                        "fieldname": mv.get("fieldname"),
                    }

                # Also check table_fields for phone numbers, value_maps, mapped_values, defaults
                if field.get("table_fields"):
                    for table_field in field.get("table_fields", []):
                        table_fieldname = table_field.get("table_fieldname")
                        table_sl_column = table_field.get("sl_column")
                        if table_field.get("is_phone_no") == 1:
                            try:
                                child_doctype = frappe.get_meta(doctype).get_field(fieldname).options
                                key = f"{child_doctype}:{table_fieldname}"
                                phone_field_lookup[key] = {
                                    "country_code": table_field.get("phone_country_code", "AT")
                                }
                            except:
                                pass

                        if table_field.get("value_map") and table_sl_column:
                            try:
                                child_doctype = frappe.get_meta(doctype).get_field(fieldname).options
                                key = f"{child_doctype}:{table_fieldname}:{table_sl_column}"
                                value_map_lookup[key] = {
                                    "map": table_field.get("value_map") or {},
                                    "default": table_field.get("value_map_default")
                                }
                            except:
                                pass

                        if table_field.get("mapped_value") and table_sl_column:
                            try:
                                child_doctype = frappe.get_meta(doctype).get_field(fieldname).options
                                mv = table_field.get("mapped_value")
                                key = f"{child_doctype}:{table_fieldname}:{table_sl_column}"
                                mapped_value_lookup[key] = {
                                    "table_name": mv.get("table_name"),
                                    "sl_id": mv.get("sl_id"),
                                    "doc_type": mv.get("doc_type"),
                                    "fieldname": mv.get("fieldname"),
                                }
                            except:
                                pass

        # get db schema from instance
        schema: str = frappe.db.get_value("Sync Instance", instance, "schema") or ""

        # Add mapped_value.sl_id columns needed for cross-reference resolution.
        # These are parent-table columns that provide the SelectLine ID used
        # to look up the corresponding ERPNext document name.
        for mv_config in mapped_value_lookup.values():
            sl_id_col = mv_config.get("sl_id")
            if sl_id_col and sl_id_col not in columns and sl_id_col not in mq_sl_columns:
                columns.append(sl_id_col)

        # get name of primary key column from mapping doc
        primary_key_col: str = mapping_doc.primary_key_column
        primary_key_val: str = id_data.get("primary_key")
        if not primary_key_col:
            raise Exception("Could not get primary key column name from mapping doc")

        resolved_table_name = resolve_table_name_for_mapping(
            instance=instance,
            mapping_name=mapping_name,
            table_from_id=id_data.get("table"),
        )

        # Build SQL using helper function
        sql: str = controller.make_sql_string_single_row(
            instance=instance,
            table_name=resolved_table_name,
            columns=columns,
            primary_key_col=primary_key_col,
            primary_key_val=primary_key_val,
            schema=schema
        )

        # validate fetched data
        try:
            fetched_data: list = controller.fetch_data(instance=instance, sql=sql)
        except Exception as fetch_err:
            make_log(f"SQL execution failed for {mapping_name}: {fetch_err}\nSQL: {sql}", "ERROR", controller.APP_NAME)
            raise Exception(f"Could not fetch data: {fetch_err}")
        
        if not fetched_data:
            make_log(f"DEBUG update_mapping: fetched_data is empty or None: {fetched_data}", "ERROR", controller.APP_NAME)
            raise Exception(f"Could not fetch data: no rows returned")
        
        # Debug: log the keys in the first row
        if fetched_data and len(fetched_data) > 0:
            make_log(f"DEBUG update_mapping: First row keys: {list(fetched_data[0].keys()) if fetched_data[0] else 'empty'}", "INFO", controller.APP_NAME)

        if len(fetched_data) > 1:
            raise Exception(
                f"Got {len(fetched_data)} rows when fetching data from table:{resolved_table_name} "
                f"Key:{primary_key_col} ID:{id_data.get('primary_key')}"
            )
        
        # Fetch multiple_query child table data so child rows can be updated.
        # Maps child_row_name -> {COLUMN: value, ...} from the source child table.
        mq_child_data: dict[str, dict] = {}
        for mapped_doctype in mapping_json:
            doctype_name = mapped_doctype.get("doctype")
            for field in mapped_doctype.get("fields", []):
                if not field.get("multiple_query") or not field.get("table_fields"):
                    continue

                mq_table = field.get("multiple_query_table")
                mq_condition = field.get("multiple_query_condition")
                if not mq_table or not mq_condition:
                    continue

                # Determine the match key between source rows and ERPNext child rows.
                # Preferred: match_key_column from the mapping JSON — a stable source
                # column (e.g. rowid__) stored as source_row_key on the mapping entries.
                # Fallback (legacy): first reqd sl_column matched against the current
                # ERPNext value — breaks when that value itself changes in the source.
                match_key_col: str = field.get("match_key_column")

                # Extract explicit column names to avoid SELECT * (4D blob column failures)
                mq_columns: list = []
                for tf in field.get("table_fields", []):
                    if tf.get("sl_column") and tf["sl_column"] not in mq_columns:
                        mq_columns.append(tf["sl_column"])
                    if tf.get("alt_key") and tf["alt_key"] not in mq_columns:
                        mq_columns.append(tf["alt_key"])
                    if tf.get("mapped_value") and tf["mapped_value"].get("sl_id"):
                        sl_id = tf["mapped_value"]["sl_id"]
                        if sl_id not in mq_columns:
                            mq_columns.append(sl_id)
                if match_key_col and match_key_col not in mq_columns:
                    mq_columns.append(match_key_col)

                source_rows = controller.fetch_multiple_rows(
                    instance=instance,
                    table=mq_table,
                    condition=mq_condition,
                    schema=schema,
                    parent_data=fetched_data[0],
                    columns=mq_columns if mq_columns else None,
                )

                if not source_rows:
                    continue

                # Build case-insensitive column lookup (4D returns PascalCase)
                def _get_col(row_data: dict, col: str):
                    if col in row_data:
                        return row_data[col]
                    upper = col.upper()
                    for k, v in row_data.items():
                        if k.upper() == upper:
                            return v
                    return None

                # Legacy match field: first reqd sl_column
                match_sl_col = None
                match_child_fieldname = None
                for tf in field.get("table_fields", []):
                    if tf.get("sl_column") and tf.get("reqd") == 1:
                        match_sl_col = tf["sl_column"]
                        match_child_fieldname = tf["table_fieldname"]
                        break

                if not match_key_col and (not match_sl_col or not match_child_fieldname):
                    # No key field — can't match source rows to child rows
                    continue

                fieldname = field.get("fieldname")
                child_doctype = None
                try:
                    child_doctype = frappe.get_meta(doctype_name).get_field(fieldname).options
                except Exception:
                    pass
                if not child_doctype:
                    continue

                # Group mapping entries of this child table by child_row_name
                entries_by_child: dict = {}
                for mrow in mapping_doc.mapping_table:
                    if (
                        mrow.mapping_doctype == doctype_name
                        and mrow.fieldname == fieldname
                        and mrow.child_row_name
                    ):
                        entries_by_child.setdefault(mrow.child_row_name, []).append(mrow)

                # Build source lookups
                source_by_key: dict = {}
                source_by_legacy: dict = {}
                for srow in source_rows:
                    if match_key_col:
                        key_val = _get_col(srow, match_key_col)
                        if key_val is not None:
                            source_by_key[str(key_val)] = srow
                    if match_sl_col:
                        legacy_val = _get_col(srow, match_sl_col)
                        if legacy_val is not None:
                            source_by_legacy[str(legacy_val)] = srow
                if not match_key_col:
                    source_by_key = source_by_legacy

                # Match existing child rows to source rows
                matched_keys: set = set()
                for crn, entries in entries_by_child.items():
                    if not frappe.db.exists(child_doctype, crn):
                        continue
                    matched_source = None
                    matched_key = None
                    stored_key = entries[0].get("source_row_key") if match_key_col else None
                    if stored_key and stored_key in source_by_key:
                        matched_source = source_by_key[stored_key]
                        matched_key = stored_key
                    if not matched_source and match_child_fieldname:
                        # Legacy match via current ERPNext value — also used to backfill
                        # source_row_key on entries created before match_key_column existed
                        current_val = frappe.db.get_value(child_doctype, crn, match_child_fieldname)
                        if current_val is not None:
                            matched_source = source_by_legacy.get(str(current_val))
                            if matched_source and match_key_col:
                                key_val = _get_col(matched_source, match_key_col)
                                matched_key = str(key_val) if key_val is not None else None
                    if not matched_source:
                        continue
                    mq_child_data[crn] = matched_source
                    if matched_key:
                        matched_keys.add(matched_key)
                    if match_key_col and matched_key and not stored_key:
                        for e in entries:
                            frappe.db.set_value("Sync Mapping Entry", e.name, "source_row_key", matched_key, update_modified=False)

                if mq_child_data:
                    make_log(
                        f"Fetched {len(source_rows)} child rows from {mq_table}, "
                        f"matched {len(mq_child_data)} to existing child docs",
                        "INFO",
                        controller.APP_NAME,
                    )

                if not match_key_col:
                    # Legacy mode: update values only, no structural sync
                    continue

                # Delete child rows whose source row no longer exists
                for crn, entries in entries_by_child.items():
                    if crn in mq_child_data:
                        continue
                    if frappe.db.exists(child_doctype, crn):
                        frappe.db.delete(child_doctype, {"name": crn})
                        make_log(
                            f"Deleted {child_doctype} row {crn} (source row removed from {mq_table})",
                            "INFO",
                            controller.APP_NAME,
                        )
                    for e in entries:
                        frappe.delete_doc("Sync Mapping Entry", e.name, ignore_permissions=True, force=True)

                # Create child rows for source rows without a matching child row
                new_keys = [k for k in source_by_key if k not in matched_keys]
                if not new_keys:
                    continue

                parent_docname = next(
                    (e.docname for el in entries_by_child.values() for e in el if e.docname),
                    None,
                ) or next(
                    (m.docname for m in mapping_doc.mapping_table if m.mapping_doctype == doctype_name and m.docname),
                    None,
                )
                if not parent_docname:
                    continue

                parent_docstatus = frappe.db.get_value(doctype_name, parent_docname, "docstatus") or 0
                last_idx_row = frappe.get_all(
                    child_doctype,
                    filters={"parent": parent_docname, "parentfield": fieldname},
                    fields=["idx"],
                    order_by="idx desc",
                    limit=1,
                )
                next_idx = (last_idx_row[0].idx if last_idx_row else 0) + 1

                for key in new_keys:
                    srow = source_by_key[key]
                    resolved: dict = {}
                    skip_row = False
                    for tf in field.get("table_fields", []):
                        tfn = tf.get("table_fieldname")
                        if not tfn:
                            continue
                        if tf.get("sl_column"):
                            if tf.get("alt_key") and _get_col(srow, tf["alt_key"]) not in (None, ""):
                                value = _get_col(srow, tf["alt_key"])
                            else:
                                value = _get_col(srow, tf["sl_column"])
                            if tf.get("force_str_type") == 1 and value is not None:
                                value = str(value)
                            lookup_key = f"{child_doctype}:{tfn}:{tf['sl_column']}"
                            if lookup_key in value_map_lookup and value is not None:
                                map_data = value_map_lookup[lookup_key]
                                value_map = map_data.get("map") or {}
                                map_default = map_data.get("default")
                                value = value_map.get(str(value), map_default if map_default is not None else value)
                            if tf.get("mapped_value") and value is not None:
                                mv = tf["mapped_value"]
                                sl_id_val = _get_col(srow, mv.get("sl_id"))
                                if sl_id_val is not None:
                                    resolved_mv = controller.get_mapped_value(
                                        sl_id=f"{instance}:{mv.get('table_name')}:{sl_id_val}",
                                        doc_type=mv.get("doc_type"),
                                        fieldname=mv.get("fieldname"),
                                    )
                                    if resolved_mv:
                                        value = resolved_mv
                            phone_key = f"{child_doctype}:{tfn}"
                            if phone_key in phone_field_lookup and value:
                                value = format_phone_number(value, phone_field_lookup[phone_key]["country_code"])
                        elif tf.get("default") is not None:
                            value = tf["default"]
                        else:
                            continue
                        if value in ["", None] and tf.get("reqd") == 1:
                            make_log(
                                f"Skipping new {child_doctype} row from {mq_table}: required field {tfn} is empty",
                                "WARNING",
                                controller.APP_NAME,
                            )
                            skip_row = True
                            break
                        resolved[tfn] = value
                    if skip_row or not resolved:
                        continue

                    child_name = frappe.generate_hash(length=8)
                    new_row = frappe.get_doc({
                        "doctype": child_doctype,
                        "parenttype": doctype_name,
                        "parent": parent_docname,
                        "name": child_name,
                        "parentfield": fieldname,
                        "idx": next_idx,
                        "docstatus": parent_docstatus,
                    })
                    new_row.insert(ignore_permissions=True, ignore_mandatory=True)
                    next_idx += 1

                    for tfn, value in resolved.items():
                        if value not in ["", None]:
                            frappe.db.set_value(child_doctype, child_name, tfn, value)

                    for tf in field.get("table_fields", []):
                        if tf.get("sl_column"):
                            controller.insert_mapping_row(
                                mapping_doc_name=mapping_name,
                                data={
                                    "mapping_doctype": doctype_name,
                                    "docname": parent_docname,
                                    "fieldname": fieldname,
                                    "child_row_fieldname": tf.get("table_fieldname"),
                                    "child_row_name": child_name,
                                    "child_row_doctype": child_doctype,
                                    "selectline_column": tf["sl_column"],
                                    "source_row_key": key,
                                },
                            )
                    make_log(
                        f"Created {child_doctype} row {child_name} for new source row ({match_key_col}={key})",
                        "INFO",
                        controller.APP_NAME,
                    )

        # go through mapping table and set new values in the docs
        for row in mapping_doc.mapping_table:
            try:
                # Skip entries that are error markers (fieldnames starting with _ except _user_tags)
                if row.fieldname and row.fieldname.startswith("_") and row.fieldname != "_user_tags":
                    continue
                
                # validate mapping row - skip if essential data is missing
                if not row.mapping_doctype or not row.docname or not row.fieldname:
                    make_log(f"Skipping invalid mapping row for {mapping_name}: doctype={row.mapping_doctype}, docname={row.docname}, fieldname={row.fieldname}", "WARNING", controller.APP_NAME)
                    continue

                # Skip rows without a source column (e.g. get_redis fields like link_name).
                # These are resolved at import time from sibling doctypes and are not
                # re-fetched from the source database during updates.
                if not row.selectline_column:
                    continue

                # Get value from fetched data.
                # For multiple_query child rows, use child data from the source child table.
                # For parent fields and non-multiple_query child fields, use parent data.
                col_key = row.selectline_column
                if " AS " in col_key or " as " in col_key:
                    # Extract alias from "... AS AliasName" or "... as AliasName"
                    col_key = col_key.rsplit(" AS ", 1)[-1].rsplit(" as ", 1)[-1].strip()

                if row.child_row_name and row.child_row_name in mq_child_data:
                    # multiple_query child row — look up value from child table data
                    child_source = mq_child_data[row.child_row_name]
                    field_value = child_source.get(col_key)
                    # Case-insensitive fallback (4D returns PascalCase)
                    if field_value is None:
                        upper = col_key.upper()
                        for k, v in child_source.items():
                            if k.upper() == upper:
                                field_value = v
                                break
                else:
                    field_value = fetched_data[0].get(col_key)

                # Apply value_map translation if configured in mapping JSON
                if row.child_row_fieldname:
                    value_map_key = f"{row.child_row_doctype}:{row.child_row_fieldname}:{row.selectline_column}"
                else:
                    value_map_key = f"{row.mapping_doctype}:{row.fieldname}:{row.selectline_column}"

                if value_map_key in value_map_lookup and field_value is not None:
                    map_data = value_map_lookup[value_map_key]
                    value_map = map_data.get("map") or {}
                    map_default = map_data.get("default")
                    field_value = value_map.get(str(field_value), map_default if map_default is not None else field_value)

                # Apply mapped_value cross-reference resolution if configured.
                # This translates a raw SelectLine ID into the corresponding
                # ERPNext document name (e.g. KUNDENNR "4711" -> "ACC-CUST-001").
                if value_map_key in mapped_value_lookup and field_value is not None:
                    mv_config = mapped_value_lookup[value_map_key]
                    sl_id_col = mv_config.get("sl_id")
                    # Get the sl_id value from the appropriate fetched data
                    if row.child_row_name and row.child_row_name in mq_child_data:
                        sl_id_value = mq_child_data[row.child_row_name].get(sl_id_col)
                        if sl_id_value is None:
                            upper = sl_id_col.upper()
                            for k, v in mq_child_data[row.child_row_name].items():
                                if k.upper() == upper:
                                    sl_id_value = v
                                    break
                    else:
                        sl_id_value = fetched_data[0].get(sl_id_col)
                    if sl_id_value is not None:
                        resolved = controller.get_mapped_value(
                            sl_id=f"{instance}:{mv_config.get('table_name')}:{sl_id_value}",
                            doc_type=mv_config.get("doc_type"),
                            fieldname=mv_config.get("fieldname"),
                        )
                        if resolved:
                            field_value = str(resolved) if row.child_row_fieldname and row.child_row_doctype else resolved

                # Handle _user_tags - add/remove tags instead of set_value
                if row.fieldname == "_user_tags":
                    try:
                        doc = frappe.get_doc(row.mapping_doctype, row.docname)
                        doc.db_set("_user_tags", "")
                        if field_value not in ["", None, 0, False, "0", "False", "false"]:
                            doc.add_tag(str(field_value))
                        elif value_map_key in value_map_lookup:
                            value_map = value_map_lookup[value_map_key].get("map") or {}
                            managed_tag = next(iter(value_map.values()), None) if value_map else None
                            if managed_tag:
                                doc.remove_tag(managed_tag)
                    except Exception:
                        pass
                    continue

                # Check if this is a phone field and apply formatting
                if row.child_row_fieldname:
                    # Skip when source has no value — don't clear existing fields.
                    if field_value is None or field_value == "":
                        continue

                    # Resolve child doctype from mapping entry or meta
                    target_child_doctype = row.child_row_doctype
                    if not target_child_doctype:
                        try:
                            target_child_doctype = frappe.get_meta(row.mapping_doctype).get_field(row.fieldname).options
                        except Exception:
                            pass

                    target_child_name = row.child_row_name

                    # Update ONLY updates existing child rows. Never creates.
                    # If the child row is missing, skip — reconcile will fix it.
                    if not target_child_doctype or not target_child_name:
                        continue
                    if not frappe.db.exists(target_child_doctype, target_child_name):
                        continue

                    lookup_key = f"{target_child_doctype}:{row.child_row_fieldname}"
                    if lookup_key in phone_field_lookup and field_value:
                        field_value = format_phone_number(field_value, phone_field_lookup[lookup_key]["country_code"])
                    frappe.db.set_value(target_child_doctype, target_child_name, row.child_row_fieldname, field_value)
                    
                else:
                    # Skip when source has no value — don't clear existing fields.
                    if field_value is None or field_value == "":
                        continue
                    lookup_key = f"{row.mapping_doctype}:{row.fieldname}"
                    if lookup_key in phone_field_lookup and field_value:
                        field_value = format_phone_number(field_value, phone_field_lookup[lookup_key]["country_code"])
                    frappe.db.set_value(row.mapping_doctype, row.docname, row.fieldname, field_value)

            except Exception as er:
                make_log(f"{er}", "ERROR", controller.APP_NAME, with_traceback=True)
                continue
        
        # Update timestamp and last_update on mapping doc — use db.set_value
        # to skip validation of all child table entries (major performance gain
        # for mappings with 30-45 Sync Mapping Entry rows).
        if time_stamp_col_name:
            try:
                raw_timestamp = fetched_data[0].get(time_stamp_col_name)
                time_stamp_type = mapping_doc.time_stamp_type or "datetime"
                ts_str = controller.convert_timestamp_to_string(raw_timestamp, time_stamp_type)
                frappe.db.set_value("Sync Mapping", mapping_name, "db_time_stamp", ts_str, update_modified=False)
            except Exception as ts_err:
                make_log(f"Could not update timestamp for {mapping_name}: {ts_err}", "ERROR", controller.APP_NAME)
        frappe.db.set_value("Sync Mapping", mapping_name, "last_update", datetime.datetime.now(), update_modified=False)

        frappe.db.commit()
        make_log(f"Mapping {mapping_name} updated successfully", "INFO", controller.APP_NAME)
        
        # Update job counts (skip hooks — after-hooks are managed by _run_bulk_update)
        controller.update_jobs(instance=instance, skip_hooks=True)

    except Exception as e:
        make_log(f"Could not update mapping {mapping_name}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        # Update job counts even on error
        controller.update_jobs(instance=instance, skip_hooks=True)
        return None


# Modified by PIT Agent Dev 1 - 2026-03-30: Resolve legacy type-prefixed table names for update SQL queries.
def resolve_table_name_for_mapping(instance: str, mapping_name: str, table_from_id: str) -> str:
    """Resolve source table name from object id with backward compatibility."""
    if not table_from_id:
        return table_from_id

    try:
        mapping_type: str = frappe.db.get_value("Sync Mapping", mapping_name, "type")
        if not mapping_type:
            return table_from_id

        instance_doc: Document = frappe.get_doc("Sync Instance", instance)
        candidates: list = [
            str(row.table_name)
            for row in instance_doc.table_mapping
            if row.type == mapping_type and row.table_name
        ]

        if not candidates:
            return table_from_id

        if table_from_id in candidates:
            return table_from_id

        if "_" in table_from_id:
            stripped = table_from_id.split("_", 1)[1]
            if stripped in candidates:
                make_log(
                    f"Resolved legacy table name '{table_from_id}' to '{stripped}' for mapping {mapping_name}",
                    "INFO",
                    controller.APP_NAME,
                )
                return stripped

        resolved = candidates[0]
        if resolved != table_from_id:
            make_log(
                f"Resolved table name '{table_from_id}' to '{resolved}' for mapping {mapping_name}",
                "INFO",
                controller.APP_NAME,
            )
        return resolved

    except Exception as e:
        make_log(
            f"Could not resolve table name for mapping {mapping_name} from '{table_from_id}': {e}",
            "WARNING",
            controller.APP_NAME,
        )
        return table_from_id


# split object id into data dict
def get_id_data(obj_id: str) -> dict:
    if not obj_id:
        return {}

    id_data: list = obj_id.split(":")

    if len(id_data) != 3:
        return {}

    return {
        "instance": id_data[0],
        "table": id_data[1],
        "primary_key": id_data[2]
    }


# update mappings if json mapping changes
def update_mapping_rows(mapping_name: str) -> None:

    try:
        mapping_doc: Document = frappe.get_doc("Sync Mapping", mapping_name)

        instance_name: str = mapping_doc.selectline_db_instance
        instance_doc: Document = frappe.get_doc("Sync Instance", instance_name)

        mapping_type: str = mapping_doc.type
        primary_key_column: str = mapping_doc.primary_key_column
        instance_table_mapping = instance_doc.table_mapping

        db_table_name_raw: str = get_id_data(mapping_doc.selectline_id)["table"]
        db_table_name: str = resolve_table_name_for_mapping(
            instance=instance_name,
            mapping_name=mapping_name,
            table_from_id=db_table_name_raw,
        )

        mapping_json = {}

        # get the table mapping rows to check for changes
        for row in instance_table_mapping:
            if not row.type == mapping_type or not row.primary_key == primary_key_column or not row.table_name == db_table_name:
                continue
            else:
                mapping_json: list = json.loads(row.mapping)
                break

        if not mapping_json:
            raise Exception("No mapping json")

        # iterate through the mapping json and check if row is existing in table mapping
        for map_doctype in mapping_json:
            for map_field in map_doctype.get("fields"):
                
                if not map_field.get("fieldname") and not map_field.get("table_fields"):
                    continue

                



    except Exception as e:
        make_log(f"Could not update mapping rows for mapping {mapping_name}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        return None



#! TEST ----------------------------------------------------------------------------
