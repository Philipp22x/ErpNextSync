import json
from pprint import pprint

import frappe
from frappe.model.document import Document

from pit_erpnextsync_selectline.scripts import controller
from pit_erpnext.scripts.logger import make_log


# test function
def test():
    run("test instance")


# entry point for import / update
def run(instance: str) -> None:

    # get pit_erpnextsync_selectline settings doc    
    settings_doc: Document = controller.get_settings_doc()

    # get table mapping from settings
    table_mapping: dict = settings_doc.table_mapping

    # check if table mapping exists
    if not table_mapping:
        make_log(f"Table mapping not found in settings", "ERROR", controller.APP_NAME)
        return

    # go through table mapping
    for row in table_mapping:

        # validate row
        if not row.type or not row.table_name or not row.primary_key or row.mapping == "null":
            make_log(f"Missing data in table mapping row #{row.idx} -- This row will be skipped!", "WARNING", controller.APP_NAME)
            continue

        # load mapping from table mapping row
        try:
            obj_mapping: list = json.loads(row.mapping)
            if not obj_mapping:
                make_log(f"Invalid mapping data in table mapping row #{row.idx} -- This row will be skipped!", "WARNING", controller.APP_NAME)
                raise Exception

        except Exception as e:
            make_log(f"Could not load mapping in table mapping row #{row.idx} -- This row will be skipped! -- {e}", "ERROR", controller.APP_NAME)
            continue

        try:
            data: list = controller.fetch_data(
                instance=instance,
                sql=create_sql_command(row.table_name, row.primary_key, obj_mapping)
            )

            if not data:
                raise Exception

        except Exception as e:
            make_log(f"Could not load data from selectline database column {row.tabel_name} -- This row will be skipped! -- {e}", "ERROR", controller.APP_NAME)
            continue

        for obj in data:
            print(obj)
            frappe.enqueue(
                "pit_erpnextsync_selectline.scripts.import.handle_object",
                queue="long",
                timeout=600,
                instance=instance,
                obj_data=obj,
                sl_table=row.table_name,
                primary_key=row.primary_key,
                mapping=obj_mapping
            )



# create or update objects(docs) and mappings
def handle_object(instance: str, obj_data: dict, sl_table: str, primary_key: str, mapping: list) -> None:

    # validate args
    if not instance or not obj_data or not sl_table or not primary_key:
        make_log(f"Abort handle object: Arguments not valid! -> instance: {instance}, obj_data: {obj_data}, sl_table: {sl_table}, primary_key: {primary_key}", "ERROR", controller.APP_NAME)
        return None

    # create selectline id string
    selectline_id: str = f"{instance.replace(" ", "_")}:{sl_table}:{primary_key}"

    existing_mapping: str = frappe.db.exists("Selectline Mapping", {"selectline_id": selectline_id})
    if existing_mapping:
        pass #? UPDATE

    else:
        pass #? NEW

        






# prepare sql command for fetching data from db
def create_sql_command(sl_table: str, primary_key: str, mapping: list[dict]) -> str | None:
    
    columns: list = [d["selectline_column"] for d in mapping]

    if not columns:
        return None

    columns_str: str = ",\n".join(columns)

    # sql command
    return f"""
    SELECT TOP (5) 
        {primary_key},
        {columns_str}
    FROM dbo.{sl_table} 
    ORDER BY {primary_key} 
    """








