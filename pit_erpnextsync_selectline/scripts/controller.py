import os
import json
import pymssql
from pprint import pprint

import frappe
from frappe.model.document import Document
from frappe.utils import now

from pit_erpnext.scripts.logger import make_log


# constants
APP_NAME: str = "pit_erpnextsync_selectline"



### CONNECTION ##################################################################################

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


### GET DATA ##################################################################################

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


### MAPPING ##################################################################################

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
def create_mapping(instance: str, mapping_obj_id: str, mapping_data: list[dict]) -> dict | None:

    try:
        if not mapping_data or not mapping_obj_id:
            raise Exception("Invalid arg values")
        
        # creade mapping doc
        new_mapping: Document = frappe.get_doc({
            "doctype": "Selectline Mapping",
            "selecline_db_instance": instance,
            "selectline_id": mapping_obj_id,
            "last_update": now()
        })

        # create mapping table entries
        mapping_childs_list: list = []

        for row in mapping_data:

            # basic data for new mapping child
            new_mapping_child: Document = frappe.new_doc("Selectline Mapping Entry")
            new_mapping_child.parrenttype = new_mapping.doctype
            new_mapping_child.parent = new_mapping.name
            new_mapping_child.parentfield = "mapping_table"

            # mapping data
            for key, value in row.items():
                new_mapping_child.set(key, value)

            mapping_childs_list.append(new_mapping_child)

        return {"mapping_doc": new_mapping, "mapping_childs": mapping_childs_list}

    except Exception as e:
        make_log(f"Could not create new mapping: {e} {frappe.get_traceback()}", "ERROR", APP_NAME)
        return None


def update_mapping() -> None:
    pass

def delete_mapping() -> None:
    pass


### UTILS ##################################################################################

# create object mapping id
def create_object_id(instance: str, table_name: str, primary_key: str) -> str:
    return f"{instance.replace(" ", "_")}:{table_name.replace(" ", "_")}:{primary_key.replace(" ", "_")}"


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
                if key == "mapping":
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



### TESTS ##################################################################################

def test():
    # pprint(fetch_data("test instance", "SELECT TOP (5) * FROM dbo.ART ORDER BY ART_ID"))
    load_table_mapping("test instance")