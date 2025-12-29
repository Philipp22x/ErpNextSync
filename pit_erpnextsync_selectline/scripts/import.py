import json

import frappe
from frappe.model.document import Document

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync_selectline.scripts import controller



#* test ##############################################################################################
def test():
    start_import("test instance", types=["Customer"])

def test2():
    start_import("cobra test", types=[])


#* entry point for data import ##########################################################################
def start_import(instance: str, types: list = []) -> None:

    # get instance doc
    try:
        instance_doc: Document = frappe.get_doc("Selectline DB Instance", instance)
        if not instance_doc:
            raise Exception(f"Could not get instance doc {instance}")

    except Exception as e:
        make_log(f"Could not get instance doc {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return None

    types_rows_to_import: list = controller.get_types_to_import(instance=instance, types_args=types)
   
    # return function if no rows for import
    if not types_rows_to_import:
        make_log(f"Could not found any table mapping rows. Import aborted for instance {instance}!", "ERROR", controller.APP_NAME)
        return None

    # fetch db data for every row
    for row in types_rows_to_import:
        try:
            fetched_data: list = controller.fetch_data(
                instance=instance, sql=controller.make_sql_string(mapping_row_data=row, col_to_fetch=get_fields_to_import(json.loads(row.mapping)),
                top=2)
            )

            for fetched_obj in fetched_data:

                # set background job for every object
                frappe.enqueue(
                    "pit_erpnextsync_selectline.scripts.import.import_fetched_object",
                    queue="long",
                    timeout=600,
                    instance=instance,
                    fetched_obj=fetched_obj,
                    table_mapping_row=row
                )

            if not fetched_data:
                raise Exception

        except Exception as e:
            make_log(f"Could not fetch data from {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)


#* IMPORT #########################################################################################

# new object
def import_fetched_object(instance: str, fetched_obj: dict, table_mapping_row: list) -> None:

    try:
        # validate args
        if (
            not instance or
            not fetched_obj or
            not table_mapping_row
        ):
            raise Exception("Args invalid")

        # load mapping table json
        mapping: list = json.loads(table_mapping_row.mapping)

        # check reqd fields for obj
        missing_columns: list = check_obj_requirements(fetched_obj=fetched_obj, mapping=mapping)
        if missing_columns:
            raise Exception(f"Missing field values: {missing_columns}")

        # get new mapping id
        obj_id: str = controller.create_object_id(
            instance=instance,
            table_name=table_mapping_row.table_name,
            primary_key=str(fetched_obj.get(table_mapping_row.primary_key))
        )

        # check if mapping already exists
        mapping_exists: str | None = controller.check_mapping_exists(obj_id)
        if mapping_exists:
            raise Exception(f"Mapping {mapping_exists} already exists")

        # mapping data for whole mapping doc
        obj_mapping_data: list = []

        # list of all created docs
        created_docs: list = []

        # loop mapping table for every doctype ------------------------------------------------------------
        for mapped_doctype in mapping:
            
            # try to create doc and check result code
            try:
                new_doc_result: dict = create_doc(mapped_doctype=mapped_doctype, fetched_obj=fetched_obj)

            except Exception as e:
                raise Exception(e)
            
            if new_doc_result["code"] != 100:

                # if error code
                if new_doc_result["code"] in [101, 103]:
                    continue
                    
                if new_doc_result["code"] == 102:
                    
                    # delete docs if already inserted
                    if created_docs:
                        delete_docs(created_docs=created_docs)

                    raise Exception("Required Document could not be created")
                
            else:
                # add current doc mapping data to obj mapping data
                obj_mapping_data.append(new_doc_result["doc_mapping_data"])

                # add doc to created docs list
                created_docs.append(new_doc_result["created_doc"])

        # create new mapping doc --------------------------------------------------------------------------
        new_mapping_result: Document | None = create_mapping(
            instance=instance, 
            new_mapping_data=obj_mapping_data, 
            table_mapping_row=table_mapping_row, 
            obj_id=obj_id
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


# delete doc from doc list
def delete_docs(created_docs: list) -> None:
    for doc in created_docs:
        try:
            frappe.delete_doc(doc["dt"], doc["dn"])


        except Exception as e:
            make_log(f"Could not delete doc {doc["dt"], doc["dn"]}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
            continue
    
    frappe.db.commit()


# create doc
def create_doc(mapped_doctype: dict, fetched_obj: dict) -> dict:

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

    # set field values
    for field in mapped_doctype["fields"]:

        # fields
        if field.get("sl_column"):
            if field.get("alt_key"):
                field_value = str(fetched_obj[field["alt_key"]]) if field.get("force_str_type") == 1 else fetched_obj[field["alt_key"]]
            else:
                field_value = str(fetched_obj[field["sl_column"]]) if field.get("force_str_type") == 1 else fetched_obj[field["sl_column"]]

            # check if field value is empty and reqd
            if field_value in ["", None] and field.get("reqd") == 1:
                return {"code": 101} if doc_is_reqd in [0, None] else {"code": 102}
            else:
                new_doc.set(field["fieldname"], field_value)

            # create new mapping doc row data for every field
            data: dict = {
                "mapping_doctype": new_doc.doctype,
                "fieldname": field["fieldname"],
                "selectline_column": field["sl_column"],
            }
            doc_mapping_data.append(data)

        # default fields
        elif field.get("default"):
            new_doc.set(field["fieldname"], field["default"])
            
        # tables
        elif field.get("table_fields"):
            new_child_row = new_doc.append(field["fieldname"], {})

            # child row fields
            for table_field in field["table_fields"]:

                # fetched child row fields
                if table_field.get("sl_column"):
                    if field.get("alt_key"):
                        field_value = str(fetched_obj[table_field["alt_key"]]) if table_field.get("force_str_type") == 1 else fetched_obj[table_field["alt_key"]]
                    else:
                        field_value = str(fetched_obj[table_field["sl_column"]]) if table_field.get("force_str_type") == 1 else fetched_obj[table_field["sl_column"]]

                    # check if field value is empty and reqd
                    if field_value in ["", None] and field.get("reqd") == 1:
                        return {"code": 101} if doc_is_reqd in [0, None] else {"code": 102}
                    else:
                        new_child_row.set(table_field["table_fieldname"], field_value)
                
                    # create new mapping doc row data for every field
                    data: dict = {
                        "mapping_doctype": new_doc.doctype,
                        "fieldname": field["fieldname"],
                        "selectline_column": table_field["sl_column"],
                        "child_row_fieldname": table_field["table_fieldname"]
                    }
                    doc_mapping_data.append(data)

                    # remove empty row if no
                    if fetched_obj[table_field["sl_column"]] in ["", None]:
                        new_doc.remove(new_child_row)

                elif table_field.get("default"):
                    new_child_row.set(table_field["table_fieldname"], table_field["default"])
    
    # insert new doc
    before_doc_insert_hook(new_doc=new_doc, fetched_obj=fetched_obj)

    try:
        new_doc.insert(
            ignore_permissions=True,
            ignore_mandatory=True,
            ignore_links=True
        )

        mapping_doc_name: str = new_doc.name

        frappe.db.commit()

    except frappe.exceptions.DoesNotExistError:
        if doc_is_reqd:
            return {"code": 102}
        else:
            return {"code": 103}

    except frappe.exceptions.ValidationError:
        if doc_is_reqd:
            return {"code": 102}
        else:
            return {"code": 103}

    except frappe.exceptions.DuplicateEntryError:
        make_log(f"{new_doc.doctype} {new_doc.name} already exists -> insert was skipped", "WARNING", controller.APP_NAME)
        return {"code": 103}

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

    return {
        "code": 100,
        "doc_mapping_data": doc_mapping_data,
        "created_doc": {"dt": new_doc.doctype, "dn": new_doc.name}
    }


# create mapping for object
def create_mapping(instance: str, new_mapping_data: list, table_mapping_row: list, obj_id: str) -> dict:

    try:
        # create new mapping doc with empty mapping
        new_mapping_doc: Document = controller.create_mapping_doc(instance=instance, mapping_obj_id=obj_id, mapping_type=table_mapping_row.type)
        if not new_mapping_doc:
            raise Exception("Creating new mapping doc was aborted")
        
        # fill mapping table in mapping doc
        for doc_data in new_mapping_data:
            for data in doc_data:
                controller.insert_mapping_row(new_mapping_doc.name, data=data)

        # if mapping table in mapping doc is empty -> raise exeption
        if not mapping_doc_has_mapping_etries(parent=new_mapping_doc.name):
            raise Exception("No mapping entries")

        # if successfull
        make_log(f"New mapping {new_mapping_doc.name} {new_mapping_doc.selectline_id} created", "INFO", controller.APP_NAME)
        return {
            "mapping_doc": new_mapping_doc,
            "result": True
        }

    except Exception as e:
        make_log(f"Could not create mapping: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
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
def before_doc_insert_hook(new_doc: Document, fetched_obj: dict) -> None:
    match new_doc.doctype:
        case "Customer":
            new_doc.flags.name_set = True



#* UTILS #########################################################################################

# check if mapping has entries in mapping table
def mapping_doc_has_mapping_etries(parent: str) -> bool:
    entries_list: list = frappe.get_all(
        "Selectline Mapping Entry",
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



