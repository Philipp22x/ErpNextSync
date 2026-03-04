import json

import frappe
from frappe.model.document import Document

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync_selectline.scripts import controller
from pit_erpnextsync_selectline.scripts.classes.field_vars import FieldVars



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
    # get instance doc
    try:
        instance_doc: Document = frappe.get_doc("Selectline DB Instance", instance)
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

    # init field vars object
    field_vars_obj: FieldVars = FieldVars()

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

            for fetched_obj in fetched_data:

                # get new mapping id
                obj_id: str = controller.create_object_id(
                    instance=instance,
                    table_name=row.table_name,
                    primary_key=str(fetched_obj.get(row.primary_key))
                )

                # check if mapping already exists
                mapping_exists: str | None = controller.check_mapping_exists(obj_id)
                if mapping_exists:
                    make_log(f"Mapping {obj_id} already exists", "INFO", controller.APP_NAME)

                else:
                    # set background job for import object
                    frappe.enqueue(
                        "pit_erpnextsync_selectline.scripts.import.import_fetched_object",
                        queue="long",
                        timeout=600,
                        instance=instance,
                        fetched_obj=fetched_obj,
                        table_mapping_row=row,
                        field_vars_obj=field_vars_obj,
                        obj_id=obj_id
                    )

            if not fetched_data:
                raise Exception

        except Exception as e:
            make_log(f"Could not fetch data from {instance}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)


#* IMPORT #########################################################################################

# new object
def import_fetched_object(instance: str, fetched_obj: dict, table_mapping_row: dict, field_vars_obj: FieldVars, obj_id: str) -> None:

    try:
        # validate args
        if (
            not instance or
            not fetched_obj or
            not table_mapping_row or
            not field_vars_obj or
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

        # loop mapping table for every doctype ------------------------------------------------------------
        for mapped_doctype in mapping:

            # try to create doc and check result code
            try:
                new_doc_result: dict = create_doc(instance=instance, mapped_doctype=mapped_doctype, fetched_obj=fetched_obj, field_vars_obj=field_vars_obj)

            except Exception as e:
                make_log(f"Could not create new doc: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
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
        new_mapping_result: Document | None = create_mapping(
            instance=instance,
            new_mapping_data=obj_mapping_data,
            table_mapping_row=table_mapping_row,
            obj_id=obj_id,
            time_stamp=fetched_obj.get(table_mapping_row.timestamp_column_name)
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
            make_log(f"Could not delete doc {doc['dt'], doc['dn']}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
            continue

    frappe.db.commit()


# create doc
def create_doc(instance: str, mapped_doctype: dict, fetched_obj: dict, field_vars_obj: FieldVars) -> dict:

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

            # check if field value is empty and reqd
            if field_value in ["", None] and field.get("reqd") == 1:
                return {"code": 101} if doc_is_reqd in [0, None] else {"code": 102}
            else:
                new_doc.set(field["fieldname"], field_value)
                # special line for adding tags to doc
                if field["fieldname"] == "_user_tags":
                    doc_tags.append(str(fetched_obj[field["sl_column"]]))

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

        # field vars
        elif field.get("field_var"):
            var_value = field_vars_obj.get_field_var_value(field.get("field_var"))
            if var_value:
                new_doc.set(field["fieldname"], var_value)
            else:
                continue

        # tables
        elif field.get("table_fields"):

            try:

                # get child doctype from table field
                child_doctype: str = frappe.get_meta(mapped_doctype["doctype"]).get_field(field["fieldname"]).options
                if not child_doctype:
                    raise Exception(f"Could not get child doctype from {mapped_doctype['doctype'].get_field(field['fieldname'])}")

                child_name = frappe.generate_hash(length=8)

                new_child_row: Document = frappe.get_doc({
                    "doctype": child_doctype,
                    "parenttype": mapped_doctype["doctype"],
                    "name": child_name,
                    "parentfield": field.get("fieldname")
                })

                child_doc_list.append(new_child_row)

            except Exception as e:
                make_log(f"Could not create child doc: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
                continue

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

                elif table_field.get("default"):
                    new_child_row.set(table_field["table_fieldname"], table_field["default"])

                # field vars
                elif table_field.get("field_var"):
                    var_value = field_vars_obj.get_field_var_value(table_field.get("field_var"))
                    if var_value:
                        new_child_row.set(table_field["table_fieldname"], var_value)
                    else:
                        continue

    # insert new doc
    before_doc_insert_hook(new_doc=new_doc, fetched_obj=fetched_obj)

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
            child_doc.insert()

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
        make_log(f"{new_doc.doctype} {new_doc.name} already exists -> insert was skipped", "ERROR", controller.APP_NAME)
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

    # check for post field var
    doc_field_var_list: list | None = mapped_doctype.get("post_field_vars")
    if doc_field_var_list:
        for field_var in doc_field_var_list:
            field_var["value"] = new_doc.get(field_var.get("field_name"))
            field_vars_obj.add_field_var(field_var=field_var)

    make_log(f"{new_doc.doctype} {new_doc.name} inserted successfully", "INFO", controller.APP_NAME)

    return {
        "code": 100,
        "doc_mapping_data": doc_mapping_data,
        "created_doc": {"dt": new_doc.doctype, "dn": new_doc.name},
        "tags": doc_tags
    }


# create mapping for object
def create_mapping(instance: str, new_mapping_data: list, table_mapping_row: dict, obj_id: str, time_stamp: str = "") -> dict:

    try:
        # create new mapping doc with empty mapping
        new_mapping_doc: Document = controller.create_mapping_doc(instance=instance, primary_key_column=table_mapping_row.primary_key, mapping_obj_id=obj_id, mapping_type=table_mapping_row.type, db_time_stamp=time_stamp)
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



