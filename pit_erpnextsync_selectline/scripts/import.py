import json
from pprint import pprint

import frappe
from frappe.model.document import Document
from frappe.model.meta import Meta

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync_selectline.scripts import controller



def test():
    start_import("test instance")


# entry point for data import ##########################################################################
def start_import(instance: str, types: list = []) -> None:

    # get instance doc
    try:
        instance_doc: Document = frappe.get_doc("Selectline DB Instance", instance)
        if not instance_doc:
            raise Exception(f"Could not get instance doc {instance}")
        
    except Exception as e:
        make_log(f"Could not get instance doc {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return None
    
    # check wich type (doctypes) has to import | if types arg is empty, import all types
    types_args = types
    types_rows_to_import: list = []
    existing_type_rows: list = instance_doc.get_table_mapping()
    if not types_args:
        types_rows_to_import = existing_type_rows
    else:
        # check if given types are exists in instance table mapping
        for arg_type in types_args:
            existing_type: dict = next(
                (t for t in existing_type_rows if t.get("type") == arg_type), None)
            
            if not existing_type:
                make_log(f"Type {arg_type} is not existing in instance {instance} table mapping. Import for this type aborted!", "WARNING", controller.APP_NAME)
                continue
            else:
                types_rows_to_import.append(existing_type)

    # return function if no rows for import
    if not types_rows_to_import:
        make_log(f"Could not found any table mapping rows. Import aborted for instance {instance}!", "ERROR", controller.APP_NAME)
        return None

    # fetch db data for every row
    for row in types_rows_to_import:
        try:
            fetched_data: list = controller.fetch_data(
                instance=instance, sql=make_sql_string(mapping_row_data=row, col_to_fetch=get_fields_to_import(json.loads(row.mapping)),
                top=2)
            )

            for fetched_obj in fetched_data:
                create_new_doc(
                    instance=instance,
                    fetched_obj=fetched_obj,
                    table_mapping_row=row
                )

            if not fetched_data:
                raise Exception

        except Exception as e:
            make_log(f"Could not fetch data from {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)



# IMPORT #########################################################################################

# new doc
def create_new_doc(instance: str, fetched_obj: dict, table_mapping_row: list) -> str | None:

    try:
        # validate args
        if (
            not instance or
            not fetched_obj or
            not table_mapping_row
        ):
            raise Exception("Args invalid")
        
        mapping: list = json.loads(table_mapping_row.mapping)
        new_mapping_doc_data: list = []
        
        for doc_map in mapping:
            try:
                #### create new doc

                new_doc: Document = frappe.new_doc(doc_map["doctype"])
                new_doc_childs = []

                # get list of mendatory fields to check for missing one
                mendatory_fields: list = get_mendatory_fields(doctype=doc_map["doctype"])

                # set fields
                for field in doc_map["fields"]:

                    # child tables
                    if field.get("table_fields"):

                        table_fields: list = field["table_fields"]

                        # get doctype of child table field
                        meta: Meta = frappe.get_meta(new_doc.doctype)
                        df = meta.get_field(field["fieldname"])
                        child_table_docname = df.options

                        # create child table row
                        new_child: Document = frappe.new_doc(child_table_docname)
                        
                        for t_field in table_fields:
                            new_child.parenttype = new_doc.doctype
                            new_child.parent = new_doc.name
                            new_child.parentfield = field["fieldname"]
                            new_child.set(t_field.get("table_fieldname"), fetched_obj.get("sl_column"))

                            # make entries for new mapping doc
                            new_mapping_doc_data.append({
                                "mapping_doctype": new_doc.doctype or "",
                                "docname": new_doc.name or "",
                                "fieldname": field.get("fieldname") or "",
                                "child_row_fieldname": t_field.get("table_fieldname") or "",
                                "selectline_column": field.get("sl_column") or "",
                                "default_value": field.get("default") or ""
                            })

                        new_doc_childs.append(new_child)

                        make_log(f"{new_doc_childs}", "INFO", controller.APP_NAME)

                    # normal docfield
                    else:
                        new_doc.set(field.get("fieldname"), fetched_obj.get(field.get("sl_column")))

                        # make entries for new mapping doc
                        new_mapping_doc_data.append({
                            "mapping_doctype": new_doc.doctype or "",
                            "docname": new_doc.name or "",
                            "fieldname": field.get("fieldname") or "",
                            "child_row_fieldname": "",
                            "selectline_column": field.get("sl_column") or "",
                            "default_value": field.get("default") or ""
                        })

                    # if current field is a mendatory field, remove it from the mendatory fields list
                    if field.get("fieldname") and field.get("fieldname") in mendatory_fields:
                        mendatory_fields.remove(field.get("fieldname"))

                # insert new doc
                new_doc.insert(
                    ignore_permissions=True,
                    ignore_mandatory=True,
                    ignore_links=True
                )

                # insert child rows for new doc
                for child in new_doc_childs:
                    child.insert(
                        ignore_permissions=True,
                        ignore_mandatory=True,
                        ignore_links=True
                    )

                # if fields in mendatory fields list left, give warning logs
                if mendatory_fields:
                    make_log(f"Missing mendatory values for {doc_map["doctype"]} {new_doc.name}: {mendatory_fields}", "WARNING", controller.APP_NAME)

                make_log(f"New {doc_map["doctype"]} {new_doc.name} created successfully", "INFO", controller.APP_NAME)


            # exception if doc already exists
            except frappe.exceptions.DuplicateEntryError:
                make_log(f"{doc_map["doctype"]} {new_doc.name} already exists", "WARNING", controller.APP_NAME)

            # generall exception
            except Exception as e:
                frappe.db.rollback()
                make_log(f"Could not create new doc: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
                continue


        #### create mapping

        # get new mapping id
        obj_id: str = controller.create_object_id(
            instance=instance,
            table_name=table_mapping_row.table_name,
            primary_key=str(fetched_obj.get(table_mapping_row.primary_key))
        )

        if controller.check_mapping_exists(obj_id):
            raise Exception(f"Mapping with id {obj_id} already exists. Creating doc and mapping aborted!")

        new_mapping: dict = controller.create_mapping(
            instance=instance,
            mapping_obj_id=obj_id,
            mapping_data=new_mapping_doc_data
        )

        new_mapping_doc: Document = new_mapping["mapping_doc"]
        new_mapping_childs: list = new_mapping["mapping_childs"]


        # insert new mapping doc
        new_mapping_doc.insert(
            ignore_permissions=True,
            ignore_mandatory=True,
            ignore_links=True
        )

        # insert new mapping doc childs
        for child in new_mapping_childs:
            child.insert(
                ignore_permissions=True,
                ignore_mandatory=True,
                ignore_links=True
            )

        frappe.db.commit()
    
    except Exception as e:
        frappe.db.rollback()
        make_log(f"Error on creating new docs from fetched object: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return
    



# UTILS #########################################################################################

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


# make the sql command str
def make_sql_string(mapping_row_data: Document, col_to_fetch: list, top: int = 0) -> str:

    top_str: str = ""
    if top > 0:
        top_str = f"TOP ({top})"

    col_string: str = ",\n".join(col_to_fetch)

    # sql command
    fetch_sql: str = f"""
    SELECT {top_str} {mapping_row_data.primary_key},
    {col_string}
    FROM dbo.{mapping_row_data.table_name} 
    ORDER BY {mapping_row_data.primary_key} 
    """

    return fetch_sql



