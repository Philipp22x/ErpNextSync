import json
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
        timeout=600,
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

        # Filter out invalid/error columns (columns starting with _ are error codes)
        valid_columns = [
            d["selectline_column"] 
            for d in mapping_table_data 
            if d.get("selectline_column") and not d["selectline_column"].startswith("_")
        ]
        col_string = ",\n".join(dict.fromkeys(valid_columns))

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
        # Build columns list
        columns = [c.strip() for c in col_string.split(",") if c.strip()]
        if time_stamp_col_name:
            columns.append(time_stamp_col_name)
        
        # Build phone + value_map lookups from mapping JSON
        phone_field_lookup: dict = {}
        value_map_lookup: dict = {}
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

                # Also check table_fields for phone numbers
                if field.get("table_fields"):
                    for table_field in field.get("table_fields", []):
                        table_fieldname = table_field.get("table_fieldname")
                        table_sl_column = table_field.get("sl_column")
                        if table_field.get("is_phone_no") == 1:
                            # For child table fields, use child doctype
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

        # get db schema from instance
        schema: str = frappe.db.get_value("Sync Instance", instance, "schema") or ""

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
                # When selectline_column contains a SQL expression with an alias
                # (e.g. "(SELECT ...) AS EmailRechnung"), the database returns the
                # result under the alias name, not the full expression.
                col_key = row.selectline_column
                if ") AS " in col_key or ") as " in col_key:
                    # Extract alias from "... AS AliasName" or "... as AliasName"
                    col_key = col_key.rsplit(" AS ", 1)[-1].rsplit(" as ", 1)[-1].strip()
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
                    repaired_child = ensure_child_row_exists(mapping_name=mapping_name, mapping_row=row)
                    target_child_doctype = repaired_child.get("child_row_doctype")
                    target_child_name = repaired_child.get("child_row_name")

                    if not target_child_doctype or not target_child_name:
                        raise Exception(
                            f"Could not resolve child row for {mapping_name} "
                            f"{row.mapping_doctype}.{row.fieldname}.{row.child_row_fieldname}"
                        )

                    lookup_key = f"{target_child_doctype}:{row.child_row_fieldname}"
                    if lookup_key in phone_field_lookup and field_value:
                        field_value = format_phone_number(field_value, phone_field_lookup[lookup_key]["country_code"])
                    frappe.db.set_value(target_child_doctype, target_child_name, row.child_row_fieldname, field_value)
                    
                else:
                    lookup_key = f"{row.mapping_doctype}:{row.fieldname}"
                    if lookup_key in phone_field_lookup and field_value:
                        field_value = format_phone_number(field_value, phone_field_lookup[lookup_key]["country_code"])
                    frappe.db.set_value(row.mapping_doctype, row.docname, row.fieldname, field_value)

            except Exception as er:
                make_log(f"{er}", "ERROR", controller.APP_NAME, with_traceback=True)
                continue
        
        # Update timestamp and last_update on mapping doc
        if time_stamp_col_name:
            try:
                raw_timestamp = fetched_data[0].get(time_stamp_col_name)
                time_stamp_type = mapping_doc.time_stamp_type or "datetime"
                mapping_doc.db_time_stamp = controller.convert_timestamp_to_string(raw_timestamp, time_stamp_type)
            except Exception as ts_err:
                make_log(f"Could not update timestamp for {mapping_name}: {ts_err}", "ERROR", controller.APP_NAME)
        mapping_doc.last_update = datetime.datetime.now()
        mapping_doc.save()
        
        frappe.db.commit()
        make_log(f"Mapping {mapping_name} updated successfully", "INFO", controller.APP_NAME)
        
        # Update job counts
        controller.update_jobs(instance=instance)

    except Exception as e:
        make_log(f"Could not update mapping {mapping_name}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        # Update job counts even on error
        controller.update_jobs(instance=instance)
        return None


def ensure_child_row_exists(mapping_name: str, mapping_row: Document) -> dict:
    """Ensure mapped child row exists; recreate and re-link mapping entries if missing."""
    child_doctype = mapping_row.child_row_doctype
    child_row_name = mapping_row.child_row_name

    # Already valid
    if child_doctype and child_row_name and frappe.db.exists(child_doctype, child_row_name):
        return {
            "child_row_doctype": child_doctype,
            "child_row_name": child_row_name
        }

    # Determine child doctype from parent table field metadata as primary source
    meta = frappe.get_meta(mapping_row.mapping_doctype)
    child_table_field = meta.get_field(mapping_row.fieldname)
    resolved_child_doctype = child_doctype
    if child_table_field and child_table_field.options:
        resolved_child_doctype = child_table_field.options

    if not resolved_child_doctype:
        raise Exception(
            f"Could not determine child doctype for "
            f"{mapping_row.mapping_doctype}.{mapping_row.fieldname}"
        )

    new_child_name = frappe.generate_hash(length=8)
    new_child = frappe.get_doc({
        "doctype": resolved_child_doctype,
        "parenttype": mapping_row.mapping_doctype,
        "parent": mapping_row.docname,
        "parentfield": mapping_row.fieldname,
        "name": new_child_name,
    })
    new_child.flags.name_set = True
    new_child.insert(ignore_permissions=True, ignore_mandatory=True)

    # Re-link all mapping rows that pointed to the missing child row
    relink_filters = {
        "parent": mapping_name,
        "mapping_doctype": mapping_row.mapping_doctype,
        "docname": mapping_row.docname,
        "fieldname": mapping_row.fieldname,
    }
    if child_row_name:
        relink_filters["child_row_name"] = child_row_name

    entries_to_relink = frappe.get_all("Sync Mapping Entry", filters=relink_filters, pluck="name")
    if not entries_to_relink and mapping_row.name:
        entries_to_relink = [mapping_row.name]

    for entry_name in entries_to_relink:
        frappe.db.set_value("Sync Mapping Entry", entry_name, "child_row_name", new_child_name)
        frappe.db.set_value("Sync Mapping Entry", entry_name, "child_row_doctype", resolved_child_doctype)

    make_log(
        f"Repaired missing child row for mapping {mapping_name}: "
        f"{mapping_row.mapping_doctype}.{mapping_row.fieldname} "
        f"{child_row_name or '<empty>'} -> {new_child_name}",
        "WARNING",
        controller.APP_NAME,
    )

    return {
        "child_row_doctype": resolved_child_doctype,
        "child_row_name": new_child_name
    }


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
