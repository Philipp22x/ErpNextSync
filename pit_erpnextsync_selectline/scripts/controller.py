
import json
import pymssql
from pprint import pprint

import frappe
from frappe.model.document import Document

from pit_erpnext.scripts.logger import make_log


# constants
APP_NAME: str = "pit_erpnextsync_selectline"
DEBUG_LOG_NAME: str = f"{APP_NAME}_DEBUG"



#*## CONNECTION ##################################################################################

# create connection to db
def db_connect(instance: str) -> pymssql.Connection | None:
    """Connects to a SQL database

    Args:
        instance (str): Name of the Selectline DB Instance doc

    Returns:
        pymysql.Connection | None: Database connection or None if fails
    """

    db_cred: dict = get_instance_data(instance=instance)

    if not db_cred:
        make_log(f"Database credentials for instance {instance} not valid", "ERROR", APP_NAME)
        return None

    try:
        conn: pymssql.Connection = pymssql.connect(
            server=db_cred["server"],
            user=db_cred["user"],
            password=db_cred["password"],
            database=db_cred["database"],
            port=int(db_cred["port"]),
            login_timeout=30,
            timeout=30
        )
        return conn

    except pymssql.Error as e:
        make_log(f"Could not connect to instance {instance}: {e}", "ERROR", APP_NAME)
        return None


# connection test from db instance
@frappe.whitelist()
def connection_test(instance: str) -> bool:
    """Checks the connection to the db instance

    Args:
        instance (str): Name of the Selectline DB Instance doc

    Returns:
        bool: success = True, fail = False
    """

    conn: pymssql.Connection | None = None
    conn = db_connect(instance=instance)

    if conn is None:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            make_log(f"Connection successfully tested for instance: {instance}", "INFO", APP_NAME)
        return True

    except pymssql.Error as e:
        make_log(f"Connection test failed for {instance}: {e}", "ERROR", APP_NAME)
        return False

    finally:
        try:
            conn.close()
        except Exception:
            pass


#*## GET DATA ##################################################################################

# fetch data from db
def fetch_data(instance: str, sql: str) -> list:

    conn: pymssql.Connection | None = None
    conn = db_connect(instance=instance)

    if conn is None:
        return None

    fetched: list = []

    try:
        with conn.cursor(as_dict=True) as cur:
            cur.execute(sql)

            while True:
                rows = cur.fetchall()
                if not rows:
                    break
                for r in rows:
                    fetched.append(r)

        return fetched

    except pymssql.Error as e:
        make_log(f"Fetching Data failed for {instance}: {e} {frappe.get_traceback()}", "ERROR", APP_NAME)
        return None

    finally:
        try:
            conn.close()
        except Exception:
            pass


#*## MAPPING ##################################################################################

# check if mapping exists
def check_mapping_exists(selectline_id: str) -> str | None:
    """Checks if mapping already exists.

    Args:
        selectline_id (str): Selectline id (<tablename>:<row id>)

    Returns:
        str | None: name of the Selectline Mapping doc or None if not exists
    """

    result: list = frappe.get_all(
        "Selectline Mapping",
        filters={
            "selectline_id": selectline_id
        },
        limit=1,
        pluck="name"
    )

    if result:
        return result[0]
    else:
        return None


# create new mapping
def create_mapping_doc(instance: str, primary_key_column: str, mapping_obj_id: str, mapping_type: str, db_time_stamp: str = "") -> Document | None:
    
    try:
        new_mapping_doc: Document = frappe.get_doc({
            "doctype": "Selectline Mapping",
            "selectline_db_instance": instance,
            "selectline_id": mapping_obj_id,
            "type": mapping_type,
            "db_time_stamp": db_time_stamp,
            "primary_key_column": primary_key_column
        })

        new_mapping_doc.insert(
            ignore_permissions=True,
            ignore_mandatory=True,
            ignore_links=True
        )

        frappe.db.commit()
        return new_mapping_doc

    except frappe.exceptions.DuplicateEntryError:
        make_log(f"Mapping id {mapping_obj_id} already exists! Creating new mapping aborted", "ERROR", APP_NAME)
        return None

    except Exception as e:
        make_log(f"Could not create new mapping doc: {e} {frappe.get_traceback()}", "ERROR", APP_NAME)
        return None
    

# create new selectline mapping entry
def insert_mapping_row(mapping_doc_name: str, data: dict) -> str | None:

    try:
        new_mapping_row: Document = frappe.new_doc("Selectline Mapping Entry")

        new_mapping_row.set("parenttype", "Selectline Mapping")
        new_mapping_row.set("parent", mapping_doc_name)
        new_mapping_row.set("parentfield", "mapping_table")

        for key, value in data.items():
            new_mapping_row.set(key, value)

        new_mapping_row.insert(
            ignore_permissions=True,
            ignore_mandatory=True,
            ignore_links=True
        )

        frappe.db.commit()
        return new_mapping_row.name
    
    except Exception as e:
        make_log(f"Could not create new Selectline Mapping Entry: {e} {frappe.get_traceback()}", "ERROR", APP_NAME)
        return None


# change all mapping ids instance name
def change_mapping_id_bulk(old_instance_name: str, new_instance_name: str) -> str:
    
    # validate args
    if not type(old_instance_name) == str or not type(new_instance_name) == str:
        _msg = f"Handle bulk change mapping id failed: no valid arguments -> {old_instance_name}, {new_instance_name}"
        make_log(_msg, "ERROR", APP_NAME, with_traceback=True)
        return _msg
    
    old_converted_name: str = old_instance_name.replace(" ", "_")
    
    instance_mapping_list: list = frappe.get_all(
        "Selectline Mapping",
        filters={
            "selectline_id": ["like", f"%{old_converted_name}%"]
        },
        pluck="name"
    )

    for mapping_doc_name in instance_mapping_list:
        sliced_mapping_id: list = frappe.db.get_value("Selectline Mapping", mapping_doc_name, "selectline_id").split(":")
        sliced_mapping_id[0] = new_instance_name.replace(" ", "_")
        new_mapping_id = ":".join(sliced_mapping_id)
        
        frappe.enqueue(
            "pit_erpnextsync_selectline.scripts.controller.change_mapping_id",
            queue="long",
            timeout=600,
            mapping_doc_name=mapping_doc_name,
            new_id=new_mapping_id
        )

    return "Renaming mappings is queued"

        
#get data of mapping doc as dict
def get_mapping_table_data(mapping_name: str) -> list:
    data: list = frappe.get_all(
        "Selectline Mapping Entry",
        filters={
            "parenttype": "Selectline Mapping",
            "parentfield": "mapping_table",
            "parent": mapping_name
        },
        fields=[
            "mapping_doctype",
            "docname",
            "fieldname",
            "selectline_column",
            "child_row_fieldname",
            "parent",
            "parenttype"
        ]
    )

    return data


# change single mapping id
def change_mapping_id(mapping_doc_name: str, new_id: str) -> None:
    try:
        mapping_doc: Document = frappe.get_doc("Selectline Mapping", mapping_doc_name)
    except:
        make_log(f"Failed to get Selectline Mapping {mapping_doc_name} for renaming mapping_id", "ERROR", APP_NAME, with_traceback=True)
        return

    if not mapping_doc.selectline_id:
        return

    mapping_doc.selectline_id = new_id
    mapping_doc.save()
    frappe.db.commit()


# def update_mapping() -> None:
#     pass

# def delete_mapping() -> None:
#     pass


#*## UTILS ##################################################################################

# create object mapping id
def create_object_id(instance: str, table_name: str, primary_key: str) -> str:
    return f"{instance.replace(chr(32), chr(95))}:{table_name.replace(chr(32), chr(95))}:{primary_key.replace(chr(32), chr(95))}"


# get db credentials from instance doc
def get_instance_data(instance: str) -> dict | None:
    """Gives the data / credentials for db connection

    Args:
        instance (str): Name of the Selectline DB Instance doc

    Returns:
        dict | None: Dict of the DB credentials fetched from the Selectline DB Instance doc
    """

    # get instace doc
    instance_doc: Document = frappe.get_doc("Selectline DB Instance", instance)

    if not instance_doc:
        return

    data: dict = {
        "server": instance_doc.server,
        "database": instance_doc.database,
        "user": instance_doc.user,
        "password": instance_doc.password,
        "port": int(instance_doc.port)
    }

    # validate instance data
    if (
        not data.get("server") or
        not data.get("database") or
        not data.get("user") or
        not data.get("password") or
        not data.get("port")
    ):
        return
    else:
        return data


# get settings doc
def get_settings_doc() -> Document | None:
    try:
        return frappe.get_single("Pit ERPNextSync - SelectLine Settings")

    except Exception as e:
        make_log(f"Could not get settings doc: {e}", "ERROR", APP_NAME)
        return None


# load table mapping json
@frappe.whitelist()
def load_table_mapping(instance: str) -> str| None:

    try:
        instance_doc: Document = frappe.get_doc("Selectline DB Instance", instance)

        # load json data
        file_url: str | None = instance_doc.mapping_json_file

        if not file_url:
            make_log(f"Loading table mapping aborted because file is missing", "WARNING", APP_NAME)
            return None
        
        file_path: str = frappe.get_site_path(file_url.lstrip("/"))

        with open(file_path, "r") as f:
            data = json.loads(f.read())

        if not data:
            make_log(f"Could not load table mapping: Invalid data", "ERROR", APP_NAME)
            return None
        
        instance_doc.table_mapping = []
        instance_doc.save()
        
        # load to table
        for row in data:
            new_mapping_row: Document = frappe.new_doc("Selectline Table Mapping")
            new_mapping_row.parenttype = "Selectline DB Instance"
            new_mapping_row.parent = instance
            new_mapping_row.parentfield = "table_mapping"

            for key, value in row.items():
                if key in ["mapping", "query_filter"]:
                    new_mapping_row.set(key, json.dumps(value, indent=4))
                else:
                    new_mapping_row.set(key, value)

            new_mapping_row.insert(ignore_permissions=True)
            frappe.db.commit()

            make_log(f"Created table mapping entry for Selectline DB Instance {instance} successfully", "INFO", APP_NAME)
        
        return "success"
            
    except Exception as e:
        make_log(f"Could not load table mapping: {e}", "ERROR", APP_NAME)
        return None
    

# make the sql command str
def make_sql_string(instance: str, db_ts_col_name: str, mapping_row_data: Document, col_to_fetch: list, top: int = 0) -> str:

    # add primary key if not in columns to fetch
    if not mapping_row_data.primary_key in col_to_fetch:
        col_to_fetch.append(mapping_row_data.primary_key)

    # add order_by columns if not already in coumns to fetch
    if mapping_row_data.order_by and mapping_row_data.order_by not in col_to_fetch:
        col_to_fetch.append(mapping_row_data.order_by)

    if db_ts_col_name:
        col_to_fetch.append(db_ts_col_name)

    # set amount to fetch
    top_str: str = ""
    if top > 0:
        top_str = f"TOP ({top})"

    # handle filters if exists in mapping
    query_filter: str = mapping_row_data.get("query_filter")
    query_filter_command: str = ""
    if query_filter and type(query_filter) == str:
        query_filter_command = f"WHERE {query_filter.replace(chr(34), '')}"

    # convert columns to fetch list to str
    col_string: str = ",\n".join(col_to_fetch)

    # get db schema from instance
    schema: str = frappe.db.get_value("Selectline DB Instance", instance, "schema") or ""
    shema_dot: str = "." if schema else ""

    # set order by string
    order_by: str = mapping_row_data.primary_key
    if mapping_row_data.order_by:
        order_by = mapping_row_data.order_by

    # sql command
    fetch_sql: str = f"""
    SELECT {top_str} {col_string}
    FROM {schema}{shema_dot}{mapping_row_data.table_name}
    {query_filter_command}
    ORDER BY {order_by}
    """

    make_log(f"SQL string:{fetch_sql}", "INFO", APP_NAME)
    return fetch_sql


# check if types are given and if given types are existing in mapping table
def get_types_to_import(instance: str, types_args: list) -> list:
    instance_doc: Document = frappe.get_doc("Selectline DB Instance", instance)

     # check wich type (doctypes) has to import | if types arg is empty, import all types
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
                make_log(f"Type {arg_type} is not existing in instance {instance} table mapping. Import for this type aborted!", "WARNING", APP_NAME)
                continue
            else:
                types_rows_to_import.append(existing_type)

    return types_rows_to_import


# get value from mapping entry
def get_mapped_value(sl_id: str, doc_type: str, fieldname: str) -> str:

    mapping_doc_name: any = frappe.db.exists(
        "Selectline Mapping",
        {
            "selectline_id": sl_id
        }
    )

    if fieldname == "name":
        docname_list: list = frappe.get_all(
            "Selectline Mapping Entry",
            filters={
                "parent": mapping_doc_name,
                "mapping_doctype": doc_type
            },
            pluck="docname"
        )

        return docname_list[0] if docname_list else ""

    if mapping_doc_name:
        mapping_entry_name: any = frappe.db.exists(
        "Selectline Mapping Entry",
        {
            "parent": mapping_doc_name,
            "mapping_doctype": doc_type,
            "fieldname": fieldname
        }
    )
        
    else: 
        return ""
        
    if mapping_entry_name:    
        _doctype = frappe.db.get_value("Selectline Mapping Entry", filters={"name": mapping_entry_name, "fieldname": fieldname}, fieldname="mapping_doctype"),
        _filters = frappe.db.get_value("Selectline Mapping Entry", filters={"name": mapping_entry_name, "fieldname": fieldname}, fieldname="docname"),

        value: any = frappe.db.get_value(str(_doctype[0]), str(_filters[0]), fieldname=fieldname)

        return value
    
    else: 
        return ""

#*## TESTS ##################################################################################

def test():
    pass