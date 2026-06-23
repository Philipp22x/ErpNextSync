import json
import uuid
import os
import time

import frappe
from frappe.model.document import Document
from frappe.utils.background_jobs import get_job_status

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller


#* phone number formatting ##########################################################################
def format_phone_number(phone_number: str, country_code: str = "AT") -> str:
    """Format a phone number to Frappe's standard format.
    
    Args:
        phone_number: Raw phone number string from source
        country_code: ISO country code (default: AT for Austria)
    
    Returns:
        str: Formatted phone number with + prefix and country code
    """
    if not phone_number:
        return ""
    
    # Remove all non-numeric characters except +
    cleaned = "".join(char for char in str(phone_number) if char.isdigit() or char == "+")
    
    # Remove leading zeros after +
    if cleaned.startswith("+"):
        return cleaned
    
    # Handle numbers starting with 00 (international prefix)
    if cleaned.startswith("00"):
        return "+" + cleaned[2:]
    
    # Handle numbers starting with 0 (national format)
    if cleaned.startswith("0"):
        country_prefix = {
            "AT": "43",  # Austria
            "DE": "49",  # Germany
            "CH": "41",  # Switzerland
            "US": "1",   # USA
            "GB": "44",  # UK
        }.get(country_code, "43")  # Default to Austria
        
        return f"+{country_prefix}{cleaned[1:]}"
    
    # If no prefix, assume it's already in international format without +
    if len(cleaned) > 8:
        return f"+{cleaned}"
    
    return cleaned


#* test ##############################################################################################
def test():
    start_import("test instance",top=3, types_str="Customer")

def test2():
    start_import("cobra test",top=3, types_str="")

def test3():
    print(controller.get_mapped_value(
        sl_id="cobra test:ADDRESSES A1:41231",
        doc_type="Lead",
        fieldname="city"
    ))


#* repair broken address links ########################################################################
@frappe.whitelist()
def repair_address_customer_links(instance: str, dry_run: bool = True) -> dict:
    """Fix Address Dynamic Link rows where link_doctype='Customer' but link_name is empty.

    Finds addresses where the address_title matches a Customer's customer_name
    and updates the empty link_name to the customer's name (ID).

    Args:
        instance: Sync Instance name (used for logging context only)
        dry_run: If True, only report what would be fixed without making changes

    Returns:
        dict with counts: fixed, skipped, errors
    """
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes")

    make_log(
        f"repair_address_customer_links started for instance={instance}, dry_run={dry_run}",
        "INFO",
        controller.APP_NAME
    )

    # Find all Dynamic Link rows for Address with empty or null link_name
    broken_links = frappe.get_all(
        "Dynamic Link",
        filters=[
            ["parenttype", "=", "Address"],
            ["link_doctype", "=", "Customer"],
            ["link_name", "in", ["", None]],
        ],
        fields=["name", "parent", "link_doctype", "link_name"],
        limit=0,
    )

    fixed = 0
    skipped = 0
    errors = 0

    for dl in broken_links:
        try:
            address_title = frappe.db.get_value("Address", dl["parent"], "address_title")
            if not address_title:
                skipped += 1
                continue

            # Find a Customer where customer_name matches address_title
            customer_names = frappe.get_all(
                "Customer",
                filters={"customer_name": address_title},
                pluck="name",
                limit=1
            )
            if not customer_names:
                make_log(
                    f"No Customer found with customer_name='{address_title}' for Address {dl['parent']}",
                    "WARNING",
                    controller.APP_NAME
                )
                skipped += 1
                continue

            customer_id = customer_names[0]

            if dry_run:
                make_log(
                    f"[DRY RUN] Would fix Dynamic Link {dl['name']} on Address {dl['parent']}: "
                    f"link_name='' -> '{customer_id}'",
                    "INFO",
                    controller.APP_NAME
                )
            else:
                frappe.db.set_value(
                    "Dynamic Link",
                    dl["name"],
                    "link_name",
                    customer_id,
                    update_modified=False
                )
                make_log(
                    f"Fixed Dynamic Link {dl['name']} on Address {dl['parent']}: "
                    f"link_name='' -> '{customer_id}'",
                    "INFO",
                    controller.APP_NAME
                )
            fixed += 1

        except Exception as e:
            make_log(
                f"Error processing Dynamic Link {dl.get('name')} for Address {dl.get('parent')}: {e}",
                "ERROR",
                controller.APP_NAME,
                with_traceback=True
            )
            errors += 1

    if not dry_run:
        frappe.db.commit()

    result = {"fixed": fixed, "skipped": skipped, "errors": errors, "dry_run": dry_run}
    make_log(f"repair_address_customer_links completed: {result}", "INFO", controller.APP_NAME)
    return result


#* entry point for data import ##########################################################################
@frappe.whitelist()
def start_import(instance: str, top: int, types_str: str = "") -> str:
    """Entry point - enqueues the actual import as a long-running background job.

    Returns:
        str: The job_id of the enqueued background job.
    """
    job_id = f"pes_import:{instance}:{uuid.uuid4().hex[:8]}"
    frappe.enqueue(
        "pit_erpnextsync.scripts.data_import._run_import",
        queue="long",
        timeout=3600,
        job_id=job_id,
        instance=instance,
        top=top,
        types_str=types_str
    )
    return job_id


def _run_import(instance: str, top: int, types_str: str = "") -> None:
    """Actual import logic - runs as a long background job."""

    # before import hooks
    controller.trigger_hooks(instance=instance, before_after="before", import_update="import")

    # get instance doc
    try:
        instance_doc: Document = frappe.get_doc("Sync Instance", instance)
        if not instance_doc:
            raise Exception(f"Could not get instance doc {instance}")

    except Exception as e:
        make_log(f"Could not get instance doc {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return None

    # convert types str to a list (handles JSON arrays, CSV strings, None, and "")
    types: list = controller.parse_types_input(types_str)

    types_rows_to_import: list = controller.get_types_to_import(instance=instance, types_args=types)

    # return function if no rows for import
    if not types_rows_to_import:
        make_log(f"Could not found any table mapping rows. Import aborted for instance {instance}!", "ERROR", controller.APP_NAME)
        return None

    all_job_ids: list = []

    # fetch db data for every row - sequential by idx to prevent race conditions
    for row in types_rows_to_import:
        try:
            fetched_data: list = controller.fetch_data(
                instance=instance,
                sql=controller.make_sql_string(
                    instance=instance,
                    db_ts_col_name=row.timestamp_column_name,
                    mapping_row_data=row,
                    col_to_fetch=get_fields_to_import(json.loads(row.mapping)),
                    top=top
                )
            )

            if not fetched_data: 
                make_log(f"No data fetched: {fetched_data}", "ERROR", controller.APP_NAME)
                continue

            make_log(
                f"Fetched {len(fetched_data)} rows for {row.type} from {row.table_name}",
                "INFO",
                controller.APP_NAME,
            )

            # Cache the runs value and batch size - avoid repeated DB queries for every row
            instance_values = frappe.get_value('Sync Instance', instance, ['runs', 'import_batch_size'], as_dict=True)
            instance_runs = instance_values.get('runs')
            batch_size: int = max(int(instance_values.get('import_batch_size') or 10), 1)

            # collect items to import, then enqueue in batches
            current_batch: list[dict] = []
            type_job_ids: list = []

            for idx, fetched_obj in enumerate(fetched_data):
                
                # get new mapping id
                obj_id: str = controller.create_object_id(
                    instance=instance,
                    table_name=row.table_name,
                    primary_key=str(fetched_obj.get(row.primary_key)),
                    mapping_type=row.type
                )

                # check if mapping already exists
                mapping_exists: str | None = controller.check_mapping_exists(obj_id)
                if mapping_exists:
                    continue

                # add to current batch
                current_batch.append({"fetched_obj": fetched_obj, "obj_id": obj_id})

                # enqueue batch when full
                if len(current_batch) >= batch_size:
                    job_id = f"pes:{instance_runs}:{uuid.uuid4().hex[:16]}"
                    frappe.enqueue(
                        "pit_erpnextsync.scripts.data_import.import_fetched_batch",
                        queue="long",
                        timeout=600 * batch_size,
                        job_id=job_id,
                        instance=instance,
                        batch_items=current_batch,
                        table_mapping_row=row
                    )
                    type_job_ids.append(job_id)
                    current_batch = []

                # Log progress every 1000 rows
                if (idx + 1) % 1000 == 0:
                    make_log(f"Processed {idx + 1}/{len(fetched_data)} rows for {row.type}", "INFO", controller.APP_NAME)

            # enqueue remaining items in the last partial batch
            if current_batch:
                job_id = f"pes:{instance_runs}:{uuid.uuid4().hex[:16]}"
                frappe.enqueue(
                    "pit_erpnextsync.scripts.data_import.import_fetched_batch",
                    queue="long",
                    timeout=600 * len(current_batch),
                    job_id=job_id,
                    instance=instance,
                    batch_items=current_batch,
                    table_mapping_row=row
                )
                type_job_ids.append(job_id)

            make_log(
                f"Enqueued {len(type_job_ids)} batch jobs for {row.type} (batch_size={batch_size})",
                "INFO",
                controller.APP_NAME,
            )

            all_job_ids.extend(type_job_ids)

            # Wait for all jobs of this type to complete before processing the next type
            # This ensures sequential processing by idx order (e.g. Item Attribute before ItemVarParent)
            if type_job_ids:
                make_log(
                    f"Waiting for {len(type_job_ids)} jobs of type {row.type} to complete before next type...",
                    "INFO",
                    controller.APP_NAME,
                )
                controller.wait_for_jobs(type_job_ids)
                make_log(
                    f"All jobs for type {row.type} completed",
                    "INFO",
                    controller.APP_NAME,
                )

            if not fetched_data:
                raise Exception

        except Exception as e:
            make_log(f"Could not fetch data from {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)

    # Commit to close the current transaction so the after-hook sees data committed
    # by batch jobs (which run in separate RQ workers with their own transactions).
    # Without this, REPEATABLE READ isolation keeps the stale snapshot from before
    # the batch jobs ran, and e.g. frappe.get_all() in hook scripts returns nothing.
    frappe.db.commit()

    # after import hooks - trigger once after ALL types have been processed sequentially
    controller.trigger_hooks(instance=instance, before_after="after", import_update="import")
    make_log(f"Import completed for instance {instance}", "INFO", controller.APP_NAME)


#* IMPORT #########################################################################################

# batch import - processes multiple rows in a single background job
def import_fetched_batch(instance: str, batch_items: list[dict], table_mapping_row: dict) -> None:
    """Process a batch of fetched objects in a single background job.

    Each item in batch_items is a dict with keys: fetched_obj, obj_id.
    Rows are committed individually for error isolation.
    update_jobs is called only once at the end of the batch.
    """
    for item in batch_items:
        try:
            import_fetched_object(
                instance=instance,
                fetched_obj=item["fetched_obj"],
                table_mapping_row=table_mapping_row,
                obj_id=item["obj_id"],
                skip_job_update=True
            )
        except Exception as e:
            make_log(
                f"Batch item {item['obj_id']} failed: {e}",
                "ERROR",
                controller.APP_NAME,
                with_traceback=True
            )
            continue

    # update job counts once for the entire batch
    # skip_hooks=True because _run_import handles after-hooks after all types complete
    controller.update_jobs(instance=instance, skip_hooks=True)


# new object
def import_fetched_object(instance: str, fetched_obj: dict, table_mapping_row: dict, obj_id: str, skip_job_update: bool = False) -> None:

    make_log(f"Job {obj_id} - PID: {os.getpid()} - Time: {time.time()}", "INFO", controller.APP_NAME)

    try:
        # validate args
        if (
            not instance or
            not fetched_obj or
            not table_mapping_row or
            not obj_id
        ):
            raise Exception("Args invalid")

        # load mapping table json
        mapping: list = json.loads(table_mapping_row.mapping)

        # check reqd fields for obj
        missing_columns: list = check_obj_requirements(fetched_obj=fetched_obj, mapping=mapping)
        if missing_columns:
            raise Exception(f"Missing field values: {missing_columns}")

        # mapping data for whole mapping doc
        obj_mapping_data: list = []

        # list of all created docs
        created_docs: list = []

        # count docs created with no_mapping flag (no mapping entries, but valid docs)
        no_mapping_count: int = 0

        # local context for set_redis/get_redis - scoped to this object to prevent
        # cross-contamination between objects in the same batch or concurrent workers
        redis_context: dict = {}

        # loop mapping table for every doctype ------------------------------------------------------------
        for mapped_doctype in mapping:

            # try to create doc and check result code
            try:
                new_doc_result: dict = create_doc(instance=instance, mapped_doctype=mapped_doctype, fetched_obj=fetched_obj, table_mapping_row=table_mapping_row, redis_context=redis_context)

            except Exception as e:
                make_log(f"Could not create new doc: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
                raise Exception(e)

            if new_doc_result["code"] != 100:

                # if error code
                if new_doc_result["code"] in [101, 103]:
                    # Log that this doctype was skipped but don't abort whole import
                    make_log(
                        f"Skipping {mapped_doctype['doctype']} creation for {obj_id} due to validation/error (code {new_doc_result['code']})",
                        "WARNING",
                        controller.APP_NAME
                    )
                    # Add a placeholder mapping entry so we don't retry this record indefinitely
                    obj_mapping_data.append([{
                        "mapping_doctype": mapped_doctype["doctype"],
                        "fieldname": "_skipped",
                        "selectline_column": "_error_code_" + str(new_doc_result["code"]),
                        "error": True
                    }])
                    continue

                if new_doc_result["code"] == 102:

                    # delete docs if already inserted
                    if created_docs:
                        delete_docs(created_docs=created_docs)

                    raise Exception("Required Document could not be created")

            else:

                # check if this doctype should skip mapping creation
                if mapped_doctype.get("no_mapping"):
                    no_mapping_count += 1
                    make_log(
                        f"Skipping mapping for {mapped_doctype['doctype']} (no_mapping flag set)",
                        "INFO",
                        controller.APP_NAME
                    )
                else:
                    # add current doc mapping data to obj mapping data
                    obj_mapping_data.append(new_doc_result["doc_mapping_data"])

                # add doc to created docs list (skip pre-existing docs to avoid deleting them on rollback)
                if not new_doc_result.get("existed"):
                    created_docs.append(new_doc_result["created_doc"])

                # add tags from tag list
                doc_tags: list = new_doc_result["tags"]
                if doc_tags:
                    try:
                        cur_doc: Document = frappe.get_doc(new_doc_result["created_doc"]["dt"], new_doc_result["created_doc"]["dn"])
                        cur_doc.db_set("_user_tags", "")
                        for tag in doc_tags:
                            cur_doc.add_tag(tag)

                    except Exception as e:
                        make_log(f"Could not add tags: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        
        # Check if any real (non-skipped) mapping data exists; if all doctypes failed
        # validation, don't create a dead mapping that would block re-import forever.
        has_real_entries = any(
            not all(row.get("error") for row in doc_data)
            for doc_data in obj_mapping_data
        ) if obj_mapping_data else False
        
        # Also consider no_mapping doctypes as valid entries — they created docs but intentionally have no mapping
        if not has_real_entries and no_mapping_count == 0:
            raise Exception("All doctypes were skipped — no documents created for this SelectLine object")

        # If all successful doctypes had no_mapping, skip creating the mapping doc entirely
        if not has_real_entries and no_mapping_count > 0:
            make_log(
                f"All doctypes for {obj_id} had no_mapping flag — skipping mapping creation",
                "INFO",
                controller.APP_NAME
            )
            frappe.db.commit()
            return

        # create new mapping doc --------------------------------------------------------------------------
        # Get timestamp value and convert it based on column type
        timestamp_col_name = table_mapping_row.timestamp_column_name
        timestamp_col_type = getattr(table_mapping_row, 'timestamp_column_type', 'datetime')
        raw_timestamp = fetched_obj.get(timestamp_col_name)
        time_stamp = controller.convert_timestamp_to_string(raw_timestamp, timestamp_col_type)
        
        new_mapping_result: Document | None = create_mapping(
            instance=instance,
            new_mapping_data=obj_mapping_data,
            table_mapping_row=table_mapping_row,
            obj_id=obj_id,
            time_stamp=time_stamp,
            time_stamp_type=timestamp_col_type
        )
        
        # if mapping not created -> delete all docs in mapping
        if new_mapping_result["result"] == False:

            # if in case that resutl is False but given a not deleted mapping doc -> delete mapping doc
            failed_mapping_doc: Document = new_mapping_result.get("mapping_doc")
            if failed_mapping_doc and type(failed_mapping_doc) == Document:
                frappe.delete_doc(failed_mapping_doc.doctype, failed_mapping_doc.name)

            # delete docs if already inserted
            if created_docs:
                delete_docs(created_docs=created_docs)

            frappe.db.commit()

            raise Exception("Could not create mapping")

        frappe.db.commit()

        # Validate variant items have attributes
        if table_mapping_row.type == "ItemVarChild":
            _validate_variant_attributes(instance, obj_id, created_docs)

    except Exception as e:
        make_log(f"Could not import fetched oject: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        raise

    finally:
        if not skip_job_update:
            # skip_hooks=True because _run_import handles after-hooks after all types complete
            controller.update_jobs(instance=instance, skip_hooks=True)


def _validate_variant_attributes(instance: str, obj_id: str, created_docs: list) -> None:
    """Validate that imported variant items have attributes. Log warning if empty."""
    try:
        item_doc_info = next((d for d in created_docs if d.get("dt") == "Item"), None)
        if not item_doc_info:
            return
        
        item_doc = frappe.get_doc("Item", item_doc_info["dn"])
        if not item_doc.attributes:
            make_log(
                f"WARNING: Variant item {item_doc.name} (ID: {obj_id}) has empty attributes table. "
                f"Variant of: {item_doc.variant_of}. "
                f"This may indicate missing ARTVARI data in SelectLine.",
                "WARNING",
                controller.APP_NAME,
            )
    except Exception:
        pass  # Don't fail import for validation errors


# delete doc from doc list
def delete_docs(created_docs: list) -> None:
    for doc in created_docs:
        try:
            frappe.delete_doc(doc["dt"], doc["dn"])


        except Exception as e:
            make_log(f"Could not delete doc {doc['dt'], doc['dn']}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
            continue

    frappe.db.commit()


# create doc
def create_doc(instance: str, mapped_doctype: dict, fetched_obj: dict, table_mapping_row: dict, redis_context: dict | None = None) -> dict:

    #? _____return codes:_____
    #
    #? 100: success
    #? 101: field reqd error
    #? 102: obj reqd error
    #? 103: error -> skip

    # create doc without fields
    new_doc: Document = frappe.new_doc(mapped_doctype["doctype"])

    # check if doc is reqd
    doc_is_reqd: int | None = mapped_doctype.get("reqd")

    # will contain all mapping data
    doc_mapping_data: list = []

    # list for doc tags
    doc_tags: list = []

    # child row list
    child_doc_list: list = []

    # maps original child hash name -> child doc object, so we can fix up
    # doc_mapping_data after insert (Frappe may rename children during parent insert)
    child_name_map: dict[str, Document] = {}

    # set field values
    for field in mapped_doctype["fields"]:

        # fields
        if field.get("sl_column"):
            if field.get("alt_key"):
                field_value = str(fetched_obj[field["alt_key"]]) if field.get("force_str_type") == 1 else fetched_obj[field["alt_key"]]
            else:
                field_value = str(fetched_obj[field["sl_column"]]) if field.get("force_str_type") == 1 else fetched_obj[field["sl_column"]]

            # check for mapped value
            if field.get("mapped_value"):
                mapped_value: any = controller.get_mapped_value(
                    sl_id=f"{instance}:{field.get('mapped_value').get('table_name')}:{fetched_obj[field['mapped_value']['sl_id']]}",
                    doc_type=field.get("mapped_value").get("doc_type"),
                    fieldname=field.get("mapped_value").get("fieldname")
                )
                field_value = str(mapped_value) if field.get("force_str_type") == 1 else mapped_value

            # check for get_redis - retrieve value from local context instead
            if field.get("get_redis") and redis_context is not None:
                redis_key = field["get_redis"]
                cached_value = redis_context.get(redis_key)
                if cached_value is not None:
                    field_value = str(cached_value) if field.get("force_str_type") == 1 else cached_value

            # value_map - translate source values to target values
            if field.get("value_map") and field_value is not None:
                field_value = field["value_map"].get(str(field_value), field.get("value_map_default", field_value))

            # is_phone_no - format phone number for Frappe
            if field.get("is_phone_no") == 1 and field_value is not None:
                country_code = field.get("phone_country_code", "AT")
                field_value = format_phone_number(field_value, country_code)

            # check if field value is empty and reqd
            if field_value in ["", None] and field.get("reqd") == 1:
                return {"code": 101} if doc_is_reqd in [0, None] else {"code": 102}
            else:
                if field["fieldname"] == "_user_tags":
                    if field_value:
                        doc_tags.append(str(field_value))
                else:
                    new_doc.set(field["fieldname"], field_value)

            # set_redis - store value in local context for later use within the same object
            if field.get("set_redis") and field_value not in ["", None] and redis_context is not None:
                redis_context[field["set_redis"]] = str(field_value)

            # create new mapping doc row data for every field
            data: dict = {
                "mapping_doctype": new_doc.doctype,
                "fieldname": field["fieldname"],
                "selectline_column": field["sl_column"],
            }
            doc_mapping_data.append(data)

        # get_redis standalone - retrieve value purely from local context (no sl_column needed)
        elif field.get("get_redis") and not field.get("sl_column"):
            redis_key = field["get_redis"]
            field_value = None
            if redis_context is not None:
                cached_value = redis_context.get(redis_key)
                if cached_value is not None:
                    field_value = str(cached_value) if field.get("force_str_type") == 1 else cached_value

            if field_value in ["", None] and field.get("reqd") == 1:
                return {"code": 101} if doc_is_reqd in [0, None] else {"code": 102}
            elif field_value not in ["", None]:
                new_doc.set(field["fieldname"], field_value)

        # default fields
        elif field.get("default"):
            new_doc.set(field["fieldname"], field["default"])

        # tables
        elif field.get("table_fields"):

            try:
                # get child doctype from table field
                child_doctype: str = frappe.get_meta(mapped_doctype["doctype"]).get_field(field["fieldname"]).options
                if not child_doctype:
                    raise Exception(f"Could not get child doctype from {mapped_doctype['doctype']}.{field['fieldname']}")

                # check if this is a multiple child rows field
                if field.get("multiple_query"):
                    # fetch multiple rows from different table
                    multiple_table = field.get("multiple_query_table")
                    multiple_condition = field.get("multiple_query_condition")
                    
                    if multiple_table and multiple_condition:
                        # get schema from instance
                        schema: str = frappe.db.get_value("Sync Instance", instance, "schema") or ""
                        
                        # Extract column names from table_fields to avoid SELECT * on
                        # tables with blob columns (which fail on 4D).
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
                        
                        # fetch multiple rows with parent data for placeholder replacement
                        multiple_rows = controller.fetch_multiple_rows(
                            instance=instance,
                            table=multiple_table,
                            condition=multiple_condition,
                            schema=schema,
                            parent_data=fetched_obj,
                            columns=mq_columns if mq_columns else None,
                        )
                        
                        make_log(
                            f"Fetched {len(multiple_rows)} child rows for {mapped_doctype['doctype']}.{field['fieldname']} from {multiple_table} (condition: {multiple_condition})",
                            "INFO",
                            controller.APP_NAME,
                        )
                        
                        if not multiple_rows:
                            make_log(
                                f"WARNING: No child rows returned for {mapped_doctype['doctype']}.{field['fieldname']} - item may have empty {field['fieldname']} table. Parent data keys: {list(fetched_obj.keys())}",
                                "WARNING",
                                controller.APP_NAME,
                            )
                        
                        # Track unique values to prevent duplicates (only if deduplicate is enabled)
                        seen_values = set()
                        deduplicate_field = field.get("deduplicate_on")
                        
                        # create child row for each fetched row
                        for row_data in multiple_rows:
                            # Check for duplicates if deduplication is enabled
                            if deduplicate_field:
                                dedup_value = row_data.get(deduplicate_field)
                                # Convert to string for consistent comparison (handles int/Decimal types)
                                dedup_value_str = str(dedup_value) if dedup_value is not None else None
                                if dedup_value_str in seen_values:
                                    make_log(
                                        f"Skipping duplicate row with {deduplicate_field}={dedup_value}",
                                        "INFO",
                                        controller.APP_NAME,
                                    )
                                    continue  # Skip duplicate
                                if dedup_value_str:
                                    seen_values.add(dedup_value_str)
                            
                            child_name = frappe.generate_hash(length=8)
                            
                            new_child_row: Document = frappe.get_doc({
                                "doctype": child_doctype,
                                "parenttype": mapped_doctype["doctype"],
                                "name": child_name,
                                "parentfield": field.get("fieldname")
                            })
                            
                            # process table fields for this child row
                            row_has_data = False
                            for table_field in field["table_fields"]:
                                # fetched child row fields
                                if table_field.get("sl_column"):
                                    if table_field.get("alt_key"):
                                        field_value = str(row_data[table_field["alt_key"]]) if table_field.get("force_str_type") == 1 else row_data[table_field["alt_key"]]
                                    else:
                                        field_value = str(row_data[table_field["sl_column"]]) if table_field.get("force_str_type") == 1 else row_data[table_field["sl_column"]]

                                    if table_field.get("mapped_value"):
                                        mapped_value: any = controller.get_mapped_value(
                                            sl_id=f"{instance}:{table_field.get('mapped_value').get('table_name')}:{row_data[table_field['mapped_value']['sl_id']]}",
                                            doc_type=table_field.get("mapped_value").get("doc_type"),
                                            fieldname=table_field.get("mapped_value").get("fieldname")
                                        )
                                        field_value = str(mapped_value) if table_field.get("force_str_type") == 1 else mapped_value

                                    # check for get_redis - retrieve value from local context instead
                                    if table_field.get("get_redis") and redis_context is not None:
                                        redis_key = table_field["get_redis"]
                                        cached_value = redis_context.get(redis_key)
                                        if cached_value is not None:
                                            field_value = str(cached_value) if table_field.get("force_str_type") == 1 else cached_value

                                    # value_map - translate source values to target values
                                    if table_field.get("value_map") and field_value is not None:
                                        field_value = table_field["value_map"].get(str(field_value), table_field.get("value_map_default", field_value))

                                    # is_phone_no - format phone number for Frappe
                                    if table_field.get("is_phone_no") == 1 and field_value is not None:
                                        country_code = table_field.get("phone_country_code", "AT")
                                        field_value = format_phone_number(field_value, country_code)

                                    # check if field value is empty and reqd — skip this ROW, not the whole doc
                                    if field_value in ["", None] and table_field.get("reqd") == 1:
                                        make_log(
                                            f"Skipping child row for {mapped_doctype['doctype']}.{field['fieldname']}: "
                                            f"required table field '{table_field['table_fieldname']}' (sl_column: {table_field.get('sl_column')}) is empty",
                                            "WARNING",
                                            controller.APP_NAME,
                                        )
                                        row_has_data = False
                                        break
                                    else:
                                        new_child_row.set(table_field["table_fieldname"], field_value)
                                        if field_value not in ["", None]:
                                            row_has_data = True

                                    # set_redis - store value in local context for later use within the same object
                                    if table_field.get("set_redis") and field_value not in ["", None] and redis_context is not None:
                                        redis_context[table_field["set_redis"]] = str(field_value)

                                    # create new mapping doc row data for every field
                                    data: dict = {
                                        "mapping_doctype": new_doc.doctype,
                                        "fieldname": field["fieldname"],
                                        "selectline_column": table_field["sl_column"],
                                        "child_row_fieldname": table_field["table_fieldname"],
                                        "child_row_name": new_child_row.name,
                                        "child_row_doctype": new_child_row.doctype
                                    }
                                    doc_mapping_data.append(data)

                                # get_redis standalone for child table fields
                                elif table_field.get("get_redis") and not table_field.get("sl_column"):
                                    redis_key = table_field["get_redis"]
                                    field_value = None
                                    if redis_context is not None:
                                        cached_value = redis_context.get(redis_key)
                                        if cached_value is not None:
                                            field_value = str(cached_value) if table_field.get("force_str_type") == 1 else cached_value

                                    # skip this ROW if reqd field is empty, not the whole doc
                                    if field_value in ["", None] and table_field.get("reqd") == 1:
                                        make_log(
                                            f"Skipping child row for {mapped_doctype['doctype']}.{field['fieldname']}: "
                                            f"required table field '{table_field['table_fieldname']}' (get_redis: {redis_key}) is empty",
                                            "WARNING",
                                            controller.APP_NAME,
                                        )
                                        row_has_data = False
                                        break
                                    elif field_value not in ["", None]:
                                        new_child_row.set(table_field["table_fieldname"], field_value)
                                        row_has_data = True

                                elif table_field.get("default"):
                                    new_child_row.set(table_field["table_fieldname"], table_field["default"])
                                    row_has_data = True
                            
                            # only add child row if it has data
                            if row_has_data:
                                child_doc_list.append(new_child_row)
                                child_name_map[new_child_row.name] = new_child_row
                            else:
                                make_log(
                                    f"Skipping child row with no data for {mapped_doctype['doctype']}.{field['fieldname']} (row keys: {list(row_data.keys())})",
                                    "WARNING",
                                    controller.APP_NAME,
                                )
                    
                else:
                    # original single child row logic
                    child_name = frappe.generate_hash(length=8)

                    new_child_row: Document = frappe.get_doc({
                        "doctype": child_doctype,
                        "parenttype": mapped_doctype["doctype"],
                        "name": child_name,
                        "parentfield": field.get("fieldname")
                    })

                    child_doc_list.append(new_child_row)
                    child_name_map[new_child_row.name] = new_child_row

                    row_has_data = False
                    pending_mapping_entries: list = []

                    # child row fields
                    for table_field in field["table_fields"]:

                        # fetched child row fields
                        if table_field.get("sl_column"):
                            if table_field.get("alt_key"):
                                field_value = str(fetched_obj[table_field["alt_key"]]) if table_field.get("force_str_type") == 1 else fetched_obj[table_field["alt_key"]]
                            else:
                                field_value = str(fetched_obj[table_field["sl_column"]]) if table_field.get("force_str_type") == 1 else fetched_obj[table_field["sl_column"]]

                            if table_field.get("mapped_value"):
                                mapped_value: any = controller.get_mapped_value(
                                    sl_id=f"{instance}:{table_field.get('mapped_value').get('table_name')}:{fetched_obj[table_field['mapped_value']['sl_id']]}",
                                    doc_type=table_field.get("mapped_value").get("doc_type"),
                                    fieldname=table_field.get("mapped_value").get("fieldname")
                                )
                                field_value = str(mapped_value) if table_field.get("force_str_type") == 1 else mapped_value

                            # check for get_redis - retrieve value from local context instead
                            if table_field.get("get_redis") and redis_context is not None:
                                redis_key = table_field["get_redis"]
                                cached_value = redis_context.get(redis_key)
                                if cached_value is not None:
                                    field_value = str(cached_value) if table_field.get("force_str_type") == 1 else cached_value

                            # value_map - translate source values to target values
                            if table_field.get("value_map") and field_value is not None:
                                field_value = table_field["value_map"].get(str(field_value), table_field.get("value_map_default", field_value))

                            # is_phone_no - format phone number for Frappe
                            if table_field.get("is_phone_no") == 1 and field_value is not None:
                                country_code = table_field.get("phone_country_code", "AT")
                                field_value = format_phone_number(field_value, country_code)

                            # check if field value is empty and reqd — skip this
                            # child row only (not the entire doctype), matching
                            # the multiple_query path's behavior.
                            if field_value in ["", None] and table_field.get("reqd") == 1:
                                make_log(
                                    f"Skipping child row for {mapped_doctype['doctype']}.{field['fieldname']}: "
                                    f"required table field '{table_field['table_fieldname']}' is empty",
                                    "WARNING",
                                    controller.APP_NAME,
                                )
                                row_has_data = False
                                break
                            else:
                                new_child_row.set(table_field["table_fieldname"], field_value)

                            if field_value not in ["", None]:
                                row_has_data = True

                            # set_redis - store value in local context for later use within the same object
                            if table_field.get("set_redis") and field_value not in ["", None] and redis_context is not None:
                                redis_context[table_field["set_redis"]] = str(field_value)

                            # collect mapping entry — only committed if row_has_data at the end
                            pending_mapping_entries.append({
                                "mapping_doctype": new_doc.doctype,
                                "fieldname": field["fieldname"],
                                "selectline_column": table_field["sl_column"],
                                "child_row_fieldname": table_field["table_fieldname"],
                                "child_row_name": new_child_row.name,
                                "child_row_doctype": new_child_row.doctype
                            })

                        # get_redis standalone for child table fields
                        elif table_field.get("get_redis") and not table_field.get("sl_column"):
                            redis_key = table_field["get_redis"]
                            field_value = None
                            if redis_context is not None:
                                cached_value = redis_context.get(redis_key)
                                if cached_value is not None:
                                    field_value = str(cached_value) if table_field.get("force_str_type") == 1 else cached_value

                            if field_value in ["", None] and table_field.get("reqd") == 1:
                                return {"code": 101} if doc_is_reqd in [0, None] else {"code": 102}
                            elif field_value not in ["", None]:
                                new_child_row.set(table_field["table_fieldname"], field_value)
                                row_has_data = True

                        elif table_field.get("default"):
                            new_child_row.set(table_field["table_fieldname"], table_field["default"])
                            row_has_data = True

                    # Only keep the child row if it has actual data
                    if not row_has_data:
                        child_doc_list.remove(new_child_row)
                        child_name_map.pop(new_child_row.name, None)
                        make_log(
                            f"Skipping child row with no data for {mapped_doctype['doctype']}.{field['fieldname']}",
                            "WARNING",
                            controller.APP_NAME,
                        )
                    else:
                        doc_mapping_data.extend(pending_mapping_entries)

            except Exception as e:
                make_log(f"Could not create child doc: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
                continue

    # set doctype flags
    set_doctype_flags(doc=new_doc, mapped_doctype=mapped_doctype)

    # insert new doc
    before_doc_insert_hook(new_doc=new_doc, fetched_obj=fetched_obj, table_mapping_row=table_mapping_row)

    # Attach child rows to parent before insert so doctypes that validate
    # children during insert (e.g. Stock Reconciliation) see them.
    # Frappe's Document.insert() will auto-insert attached children.
    for child_doc in child_doc_list:
        new_doc.append(child_doc.parentfield, child_doc)

    try:
        new_doc.insert(
            ignore_permissions=True,
            ignore_mandatory=True,
            ignore_links=True
        )
        
        mapping_doc_name: str = new_doc.name

        # Frappe may have renamed child rows during insert (set_new_name).
        # Fix up doc_mapping_data entries that reference old child hash names.
        for entry in doc_mapping_data:
            old_name = entry.get("child_row_name")
            if old_name and old_name in child_name_map:
                entry["child_row_name"] = child_name_map[old_name].name

        frappe.db.commit()


    except frappe.exceptions.DoesNotExistError as e:
        make_log(f"Could not insert document: {e}", "ERROR", controller.APP_NAME, with_traceback=True)

        if doc_is_reqd:
            return {"code": 102}
        else:
            return {"code": 103}

    except frappe.exceptions.ValidationError as e:
        make_log(f"Could not insert document: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        if doc_is_reqd:
            return {"code": 102}
        else:
            return {"code": 103}

    except frappe.exceptions.DuplicateEntryError:
        make_log(f"{new_doc.doctype} {new_doc.name} already exists -> using existing", "INFO", controller.APP_NAME)
        # Document already exists in ERPNext - treat as success and map to the existing doc
        existing_name = new_doc.name

        # Insert child rows into the existing document if it has no children yet,
        # or update existing Dynamic Link rows that have an empty link_name.
        if child_doc_list:
            try:
                existing_doc = frappe.get_doc(new_doc.doctype, existing_name)
                for child_doc in child_doc_list:
                    # Check if this child table already has rows
                    existing_children = existing_doc.get(child_doc.parentfield) or []
                    if not existing_children:
                        child_doc.parent = existing_name
                        child_doc.flags.name_set = True
                        child_doc.insert(
                            ignore_permissions=True,
                            ignore_mandatory=True,
                            ignore_links=True
                        )
                    elif child_doc.doctype == "Dynamic Link":
                        # For Dynamic Link rows: if an existing row has the same link_doctype
                        # but an empty link_name, update it with the correct value.
                        new_link_name = child_doc.get("link_name")
                        new_link_doctype = child_doc.get("link_doctype")
                        if new_link_name and new_link_doctype:
                            for existing_child in existing_children:
                                if (
                                    existing_child.get("link_doctype") == new_link_doctype
                                    and not existing_child.get("link_name")
                                ):
                                    frappe.db.set_value(
                                        "Dynamic Link",
                                        existing_child.name,
                                        "link_name",
                                        new_link_name,
                                        update_modified=False
                                    )
                                    make_log(
                                        f"Updated empty link_name on Dynamic Link {existing_child.name} "
                                        f"for {new_doc.doctype} {existing_name} -> {new_link_name}",
                                        "INFO",
                                        controller.APP_NAME
                                    )
                    else:
                        # For non-Dynamic-Link child tables that already have rows:
                        # insert the new child row alongside existing ones instead
                        # of silently dropping it (which would leave orphaned mapping
                        # entries pointing to a child_row_name that was never inserted).
                        child_doc.parent = existing_name
                        child_doc.flags.name_set = True
                        child_doc.insert(
                            ignore_permissions=True,
                            ignore_mandatory=True,
                            ignore_links=True
                        )
                        make_log(
                            f"Added child row {child_doc.doctype} {child_doc.name} "
                            f"to existing {new_doc.doctype} {existing_name} "
                            f"(field: {child_doc.parentfield}, existing rows: {len(existing_children)})",
                            "INFO",
                            controller.APP_NAME
                        )
                frappe.db.commit()
                make_log(f"Added child rows to existing {new_doc.doctype} {existing_name}", "INFO", controller.APP_NAME)
            except Exception as e:
                make_log(f"Could not add child rows to existing {new_doc.doctype} {existing_name}: {e}", "ERROR", controller.APP_NAME)

        # Fix up child_row_name in mapping data (Frappe may have renamed children
        # during the failed parent insert's set_new_name pass)
        for entry in doc_mapping_data:
            old_name = entry.get("child_row_name")
            if old_name and old_name in child_name_map:
                entry["child_row_name"] = child_name_map[old_name].name
            entry["docname"] = existing_name
        return {
            "code": 100,
            "doc_mapping_data": doc_mapping_data,
            "created_doc": {"dt": new_doc.doctype, "dn": existing_name},
            "tags": doc_tags,
            "existed": True
        }

    except Exception as e:
        make_log(f"Could not insert document: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        if doc_is_reqd:
            return {"code": 102}
        else:
            return {"code": 103}

    # add doc name to mapping entries
    for entry in doc_mapping_data:
        entry["docname"] = mapping_doc_name

    make_log(f"{new_doc.doctype} {new_doc.name} inserted successfully", "INFO", controller.APP_NAME)
    
    after_doc_insert_hook(new_doc=new_doc, fetched_obj=fetched_obj, table_mapping_row=table_mapping_row)

    return {
        "code": 100,
        "doc_mapping_data": doc_mapping_data,
        "created_doc": {"dt": new_doc.doctype, "dn": new_doc.name},
        "tags": doc_tags
    }


# create mapping for object
def create_mapping(instance: str, new_mapping_data: list, table_mapping_row: dict, obj_id: str, time_stamp: str = "", time_stamp_type: str = "datetime") -> dict:

    try:
        # create new mapping doc with empty mapping
        new_mapping_doc: Document = controller.create_mapping_doc(instance=instance, primary_key_column=table_mapping_row.primary_key, mapping_obj_id=obj_id, mapping_type=table_mapping_row.type, db_time_stamp=time_stamp, time_stamp_type=time_stamp_type)
        if not new_mapping_doc:
            raise Exception("Creating new mapping doc was aborted")

        # fill mapping table in mapping doc
        for doc_data in new_mapping_data:
            for data in doc_data:
                controller.insert_mapping_row(new_mapping_doc.name, data=data)

        # if mapping table in mapping doc is empty -> raise exeption
        if not mapping_doc_has_mapping_etries(parent=new_mapping_doc.name):
            raise Exception(f"No mapping entries: {frappe.get_traceback()}")

        # if successfull
        make_log(f"New mapping {new_mapping_doc.name} {new_mapping_doc.selectline_id} created", "INFO", controller.APP_NAME)
        return {
            "mapping_doc": new_mapping_doc,
            "result": True
        }

    except Exception as e:
        make_log(f"Could not create mapping: {e}", "ERROR", controller.APP_NAME, with_traceback=True)

        if new_mapping_doc:
            frappe.delete_doc(new_mapping_doc.doctype, new_mapping_doc.name)
            frappe.db.commit()
        
        return {
            "result": False
        }


# check if required level 2 fields are fetched
def check_obj_requirements(fetched_obj: dict, mapping: list) -> list:

    reqd_columns: list = []

    # get all reqd columns
    for doc in mapping:
        for field in doc["fields"]:
            if field.get("table_fields"):
                for table_field in field["table_fields"]:
                    if table_field.get("reqd") == 2 and table_field.get("default") == None:
                        reqd_columns.append(table_field.get("sl_column") if table_field.get("alt_key") == None else table_field.get("alt_key"))

            else:
                if field.get("reqd") == 2 and field.get("default") == None:
                    reqd_columns.append(field.get("sl_column") if field.get("alt_key") == None else field.get("alt_key"))

    missing_columns: list = []

    # check with fetched object
    for col in reqd_columns:
        if not fetched_obj[col]:
            missing_columns.append(col)

    return missing_columns


#* HOOKS #########################################################################################
def before_doc_insert_hook(new_doc: Document, fetched_obj: dict, table_mapping_row: dict) -> None:
    match new_doc.doctype:
        case "Customer":
            new_doc.flags.name_set = True
        case "Supplier":
            new_doc.flags.name_set = True
        case "Item":
            new_doc.flags.name_set = True


def after_doc_insert_hook(new_doc: Document, fetched_obj: dict, table_mapping_row: dict) -> None:
    pass
    

#* UTILS #########################################################################################
# set doctype flags
def set_doctype_flags(doc: Document, mapped_doctype: dict) -> None:
    try:
        doctype_flags = mapped_doctype.get("doctype_flags")

        if not doctype_flags:
            return
        
        if type(doctype_flags) != list:
            make_log(f"Invalid doctype flags: not a list", "ERROR", controller.APP_NAME, with_traceback=True)
            return
        
        for flag in doctype_flags:
            key, value = next(iter(flag.items()))
            setattr(doc.flags, key, value)

    except Exception as e:
        make_log(f"Could not set doctype flag: {e}", "ERROR", controller.APP_NAME, with_traceback=True)


# check if mapping has entries in mapping table
def mapping_doc_has_mapping_etries(parent: str) -> bool:
    entries_list: list = frappe.get_all(
        "Sync Mapping Entry",
        filters={
            "parent": parent
        },
        pluck="name"
    )

    if entries_list:
        return True
    else:
        return False


# delete mapping and all docs if something fails
def revert_mapping(new_mapping_doc: Document) -> None:
    new_mapping_doc.on_delete_mapping()
    frappe.delete_doc(new_mapping_doc.doctype, new_mapping_doc.name)


# get all mendatory fields from a doctype
def get_mendatory_fields(doctype: str) -> list:
    try:
        meta = frappe.get_meta(doctype)
        mandatory: list = [df.fieldname for df in meta.get("fields") if df.reqd]
        return mandatory
    except Exception as e:
        make_log(f"Could not get mendatory fields for doctype {doctype}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return []


# return a list with all sl_columns from table mapping row
def get_fields_to_import(mapping: list) -> list:
    result: list = []

    try:
        # fetch sl_columns from mapping
        for element in mapping:
            for field in element["fields"]:
                if field.get("table_fields"):
                    # skip table_fields if multiple_query is set - those columns come from a different table
                    if field.get("multiple_query"):
                        continue
                    for x in field["table_fields"]:
                        y_field: str | None = x.get("sl_column")
                        if y_field:
                            result.append(y_field)
                else:
                    x_field: str | None = field.get("sl_column")
                    if x_field:
                        result.append(x_field)

        # convert to set to remove doubled items in list
        final_result: set = set(result)

        # convert result back to list and return
        return list(final_result)

    except Exception as e:
        make_log(f"Could not get fields for import: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)


