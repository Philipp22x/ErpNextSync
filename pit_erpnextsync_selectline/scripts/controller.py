
import pymysql

import frappe
from frappe.model.document import Document

from pit_erpnext.scripts.logger import make_log


# constants
APP_NAME: str = "pit_erpnextsync_selectline"



### CONNECTION ##################################################################################

# create connection to db
def db_connect(instance: str) -> pymysql.Connection | None:
    """Connects to a Microsoft SQL database

    Args:
        instance (str): Name of the Selectline DB Instance doc

    Returns:
        pyodbc.Connection | None: Database connection or None if fails
    """

    db_cred: dict = get_instance_data(instance=instance)

    if not db_cred:
        make_log(f"Database credentials for instance {instance} not valid", "ERROR", APP_NAME)
        return
    
    try:
        conn: pymysql.Connection = pymysql.connect(
            
            server=db_cred["server"],
            user=db_cred["user"],
            password=db_cred["password"],
            database=db_cred["database"],
            port=db_cred["port"],
            connect_timeout=30
        )

        return conn

    except pymysql.Error as e:
        make_log(f"Could not connect to instance {instance}: {e}", "ERROR", APP_NAME)
        return
    

# connection test from db instance
@frappe.whitelist()
def connection_test(instance: str) -> bool:
    """Checks the connection to the db instance

    Args:
        instance (str): Name of the Selectline DB Instance doc

    Returns:
        bool: success = True, fail = False
    """

    conn: pymysql.Connection | None = None
    conn = db_connect(instance=instance)

    if conn == None:
        return False
    else:
        return True


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
        "port": instance_doc.port
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
        


### TESTS ##################################################################################
def test():
    print(connection_test("test instance"))
    print(pymysql.drivers())