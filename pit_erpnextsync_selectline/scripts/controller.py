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
        make_log(f"Fetching Data failed for {instance}: {e}", "ERROR", APP_NAME)
        return None
    
    finally:
        try:
            conn.close()
        except Exception:
            pass


### OBJECTS (DOCS) ##################################################################################

def create_object(obj_data: dict, mapping: list) -> None:
    pass

def update_object() -> None:
    pass

def delete_object() -> None:
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
def create_mapping(db_instance: str, selectline_id: str, mapping: list[dict[str, str]]) -> str:
    """Creates new Selectline Mapping

    Args:
        db_instance (str): Selectline DB Instace
        selectline_id (str): Selectline ID
        mapping (list[dict[str, str]]): List of dicts that contains the mapping

    Returns:
        str: success: <name of new mapping>
        str: arg_error: data not valid
        str: exception: error
    """

    if not db_instance or not selectline_id or not mapping:
        return "data not valid"

    try:
        new_mapping: Document = frappe.get_doc({
            "doctype": "Selectline Mapping",
            "selecline_db_instance": db_instance,
            "selectline_id": selectline_id,
            "last_update": now()
        })

        for row in mapping:
            new_mapping.append("mapping_table", {
                "mapping_doctype": row.get("mapping_doctype") or "",
                "docname": row.get("docname") or "",
                "fieldname": row.get("fieldname") or "",
                "selectline_column": row.get("selectline_column") or "",
                "child_table_doctype": row.get("child_table_doctype") or "",
                "child_table_name": row.get("child_table_name") or ""
            })

        new_mapping.insert(ignore_permissions=True)
        frappe.db.commit()

        return new_mapping.name

    except Exception as e:
        make_log(f"Could not create new mapping: {e}", "ERROR", APP_NAME)
        return "error"


def update_mapping() -> None:
    pass

def delete_mapping() -> None:
    pass


### UTILS ##################################################################################

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
        

# get default table mapping
def get_default_table_mapping() -> list:
    
    APP_PATH = frappe.get_app_path(APP_NAME)
    FILE_PATH = os.path.join(APP_PATH, "data", "default_mapping.json")

    try:
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            default_table_mapping: dict = json.load(f)
    
    except Exception as e:
        make_log(f"Could not get default mapping table data: {e}", "ERROR", APP_NAME)
        return []

    return default_table_mapping
    



### TESTS ##################################################################################

def test():
    pprint.pprint(fetch_data("test instance", "SELECT TOP (5) * FROM dbo.ART ORDER BY ART_ID"))