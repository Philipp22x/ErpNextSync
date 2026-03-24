import json
import uuid
import os
import time

import frappe
from frappe.model.document import Document
from frappe.utils.background_jobs import get_job_status

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller



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


#* entry point for data import ##########################################################################
@frappe.whitelist()
def start_import(instance: str, top: int, types_str: str = "") -> None:
    """Entry point - enqueues the actual import as a long-running background job."""
    frappe.enqueue(
        "pit_erpnextsync.scripts.data_import._run_import",
        queue="long",
        timeout=3600,
        job_id=f"pes_import:{instance}:{uuid.uuid4().hex[:8]}",
        instance=instance,
        top=top,
        types_str=types_str
    )


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

    # convert types str to a list
    types: list = json.loads(types_str)

    types_rows_to_import: list = controller.get_types_to_import(instance=instance, types_args=types)

    # return function if no rows for import
    if not types_rows_to_import:
        make_log(f"Could not found any table mapping rows. Import aborted for instance {instance}!", "ERROR", controller.APP_NAME)
        return None

    job_ids: list = []

    # fetch db data for every row
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

            for idx, fetched_obj in enumerate(fetched_data):
                
                # get new mapping id
                obj_id: str = controller.create_object_id(
                    instance=instance,
                    table_name=row.table_name,
                    primary_key=str(fetched_obj.get(row.primary_key))
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
                    job_ids.append(job_id)
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
                job_ids.append(job_id)

            make_log(
                f"Enqueued {len(job_ids)} batch jobs for {row.type} (batch_size={batch_size})",
                "INFO",
                controller.APP_NAME,
            )

            if not fetched_data:
                raise Exception

        except Exception as e:
            make_log(f"Could not fetch data from {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)


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
    controller.update_jobs(instance=instance)


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
                        for tag in doc_tags:
                            cur_doc.add_tag(tag)

                    except Exception as e:
                        make_log(f"Could not add tags: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        
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

    except Exception as e:
        make_log(f"Could not import fetched oject: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        raise

    finally:
        if not skip_job_update:
            controller.update_jobs(instance=instance)


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

            # check if field value is empty and reqd
            if field_value in ["", None] and field.get("reqd") == 1:
                return {"code": 101} if doc_is_reqd in [0, None] else {"code": 102}
            else:
                new_doc.set(field["fieldname"], field_value)
                # special line for adding tags to doc
                if field["fieldname"] == "_user_tags":
                    doc_tags.append(str(fetched_obj[field["sl_column"]]))

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
                        
                        # fetch multiple rows with parent data for placeholder replacement
                        multiple_rows = controller.fetch_multiple_rows(
                            instance=instance,
                            table=multiple_table,
                            condition=multiple_condition,
                            schema=schema,
                            parent_data=fetched_obj
                        )
                        
                        make_log(
                            f"Fetched {len(multiple_rows)} child rows for {mapped_doctype['doctype']}.{field['fieldname']} from {multiple_table}",
                            "INFO",
                            controller.APP_NAME,
                        )
                        
                        # Track unique attribute values to prevent duplicates
                        seen_attributes = set()
                        
                        # create child row for each fetched row
                        for row_data in multiple_rows:
                            # Check for duplicates based on the first table field (usually 'attribute')
                            first_field = field["table_fields"][0] if field["table_fields"] else None
                            if first_field and first_field.get("sl_column"):
                                attr_value = row_data.get(first_field["sl_column"])
                                if attr_value in seen_attributes:
                                    continue  # Skip duplicate
                                seen_attributes.add(attr_value)
                            
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

                                    # check if field value is empty and reqd
                                    if field_value in ["", None] and table_field.get("reqd") == 1:
                                        if doc_is_reqd in [0, None]:
                                            return {"code": 101}
                                        else:
                                            return {"code": 102}
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

                                    if field_value in ["", None] and table_field.get("reqd") == 1:
                                        if doc_is_reqd in [0, None]:
                                            return {"code": 101}
                                        else:
                                            return {"code": 102}
                                    elif field_value not in ["", None]:
                                        new_child_row.set(table_field["table_fieldname"], field_value)
                                        row_has_data = True

                                elif table_field.get("default"):
                                    new_child_row.set(table_field["table_fieldname"], table_field["default"])
                                    row_has_data = True
                            
                            # only add child row if it has data
                            if row_has_data:
                                child_doc_list.append(new_child_row)
                    
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

                            # check if field value is empty and reqd
                            if field_value in ["", None] and field.get("reqd") == 1:
                                return {"code": 101} if doc_is_reqd in [0, None] else {"code": 102}
                            else:
                                new_child_row.set(table_field["table_fieldname"], field_value)

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

                            # remove empty row if no
                            if table_field.get("sl_column"):
                                if table_field.get("alt_key"):
                                    if fetched_obj[table_field["alt_key"]] in ["", None]:
                                        child_doc_list.remove(new_child_row)
                                else:
                                    if fetched_obj[table_field["sl_column"]] in ["", None]:
                                        child_doc_list.remove(new_child_row)

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

                        elif table_field.get("default"):
                            new_child_row.set(table_field["table_fieldname"], table_field["default"])

            except Exception as e:
                make_log(f"Could not create child doc: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
                continue

    # set doctype flags
    set_doctype_flags(doc=new_doc, mapped_doctype=mapped_doctype)

    # insert new doc
    before_doc_insert_hook(new_doc=new_doc, fetched_obj=fetched_obj, table_mapping_row=table_mapping_row)
    
    try:
        new_doc.insert(
            ignore_permissions=True,
            ignore_mandatory=True,
            ignore_links=True
        )
        
        mapping_doc_name: str = new_doc.name

        for child_doc in child_doc_list:
            child_doc.parent = new_doc.name
            child_doc.flags.name_set = True
            child_doc.insert(
                ignore_permissions=True,
                ignore_mandatory=True,
                ignore_links=True
            )

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
        for entry in doc_mapping_data:
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


