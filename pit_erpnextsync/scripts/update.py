import json
from pprint import pprint
import frappe
import datetime
from frappe.model.document import Document

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller
from pit_erpnextsync.scripts.classes.field_vars import FieldVars


@frappe.whitelist()
def run_bulk_update(instance: str, types_str: str) -> None:

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

    # convert types str to a list
    arg_types_list: list = json.loads(types_str)

    types_list: list = []

    # if no types are given get all types from instance
    if arg_types_list == []:
        for row in instance_doc.table_mapping:
            types_list.append(row.type)
    
    else:
        types_list = arg_types_list

    # get all mappings linked to the given instance
    mappings_list: list = frappe.get_all(
        "Sync Mapping",
            filters={
            "selectline_db_instance": instance,
            "enable": 1,
            "type": ["in", types_list]
        },
        pluck="name"
    )

    # return if no mappings found
    if not mappings_list:
        make_log(f"No mapping for instance {instance} found", "ERROR", controller.APP_NAME)
        return

    # main loop for all mappings of the given instance
    for mapping_name in mappings_list:

        obj_id: str = frappe.db.get_value("Sync Mapping", mapping_name, "selectline_id")

        # verify obj_id
        if not obj_id:
            make_log(f"No object id in mapping {mapping_name}", "ERROR", controller.APP_NAME)
            continue

        id_data: dict = get_id_data(obj_id=obj_id)

        # verify id_data
        if not id_data:
            make_log(f"Could not get data from object id {obj_id}", "ERROR", controller.APP_NAME)
            continue

        frappe.enqueue(
            "pit_erpnextsync.scripts.update.check_timestamp",
            queue="long",
            timeout=600,
            instance=instance,
            id_data=id_data,
            mapping_name=mapping_name
        )

    return None


# fetch timespamp of db data object -> if changed call update
def check_timestamp(instance: str, id_data: dict, mapping_name: str) -> None:

    try:
        table_name: str = id_data.get("table")
        primary_key: str = id_data.get("primary_key")

        # validate id data
        if not instance or not table_name or not primary_key:
            make_log(f"Some id data is missing: {id_data}", "ERROR", controller.APP_NAME)
            return

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
            return "test2"

        # get the timestamp column type from mapping
        time_stamp_type: str = frappe.db.get_value("Sync Mapping", mapping_name, "time_stamp_type") or "datetime"

        # sql command for fetching timestamp from db
        sql: str = f"""
            SELECT {ts_col}
            FROM {schema}{shema_dot}{table_name}
            WHERE {primary_key_column} = {primary_key}
        """

        # result of fetching timestamp from db
        fetched_ts: list = controller.fetch_data(instance=instance, sql=sql)

        if not fetched_ts or type(fetched_ts) != list:
            raise Exception("Could not fetch valid timestamp data")

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
            return None
        else:
            frappe.enqueue(
                "pit_erpnextsync.scripts.update.update_mapping",
                queue="long",
                timeout=600,
                instance=instance,
                id_data=id_data,
                mapping_name=mapping_name
            )
            return None

    except Exception as e:
        make_log(f"Could not get timestamp from source db for {id_data}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        return None


# update single mapping / called from timestamp check
def update_mapping(instance: str, id_data: dict, mapping_name: str) -> None:
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

        col_string = ",\n".join(dict.fromkeys(
            d["selectline_column"] for d in mapping_table_data if d.get("selectline_column")
        ))

        # get timestamp column name from table mapping
        instance_doc = frappe.get_doc("Sync Instance", instance)
        time_stamp_col_name: str = None
        for table_mapping_row in instance_doc.table_mapping:
            if table_mapping_row.type == mapping_doc.type:
                time_stamp_col_name = table_mapping_row.timestamp_column_name
                break
        if not time_stamp_col_name:
            raise Exception(f"No time stamp column name found for: {mapping_name}")
        
        col_string += f", {time_stamp_col_name}"

        # get db schema from instance
        schema: str = frappe.db.get_value("Sync Instance", instance, "schema") or ""
        shema_dot: str = "." if schema else ""

        # get name of primary key column from mapping doc
        primary_key_col: str = mapping_doc.primary_key_column
        if not primary_key_col:
            raise Exception("Could not get primary key column name from mapping doc")

        # sql command
        sql: str = f"""
        SELECT {col_string}
        FROM {schema}{shema_dot}{id_data.get("table")}
        WHERE {primary_key_col} = {id_data.get("primary_key")}
        """

        # validate fetched data
        fetched_data: list = controller.fetch_data(instance=instance, sql=sql)
        if not fetched_data:
            raise Exception(f"Could not fetch data: {fetched_data}")

        if len(fetched_data) > 1:
            raise Exception(f"Got {len(fetched_data)} rows when fetching data from table:{id_data.get('table')} Key:{primary_key_col} ID:{id_data.get('primary_key')}")
        
        # go through mapping table and set new values in the docs
        for row in mapping_doc.mapping_table:
            try:
                # validate mapping row
                if not row.mapping_doctype or not row.docname or not row.fieldname:
                    raise Exception(f"Row data validation failed: {row.mapping_doctype}, {row.docname}, {row.fieldname}")

                if row.child_row_fieldname:
                    frappe.db.set_value(row.child_row_doctype, row.child_row_name, row.child_row_fieldname, fetched_data[0].get(row.selectline_column))
                    
                else:
                    frappe.db.set_value(row.mapping_doctype, row.docname, row.fieldname, fetched_data[0].get(row.selectline_column))

                # Convert and store timestamp based on column type
                raw_timestamp = fetched_data[0].get(time_stamp_col_name)
                time_stamp_type = mapping_doc.time_stamp_type or "datetime"
                mapping_doc.db_time_stamp = controller.convert_timestamp_to_string(raw_timestamp, time_stamp_type)
                mapping_doc.last_update = datetime.datetime.now()
                mapping_doc.save()

            except Exception as er:
                make_log(f"{er}", "ERROR", controller.APP_NAME, with_traceback=True)
                continue
        
        frappe.db.commit()
        make_log(f"Mapping {mapping_name} updated successfully", "INFO", controller.APP_NAME)


    except Exception as e:
        make_log(f"Could not update mapping {mapping_name}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
        return None


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

        db_table_name: str = get_id_data(mapping_doc.selectline_id)["table"]

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

