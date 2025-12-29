import json
from pprint import pprint

import frappe
from frappe.model.document import Document

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync_selectline.scripts import controller



def start_update(instance: str, types: list = []) -> None:
    
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
        pass