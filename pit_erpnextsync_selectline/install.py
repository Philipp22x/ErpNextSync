import json

import frappe
from frappe.model.document import Document

from pit_erpnextsync_selectline.scripts import controller
from pit_erpnext.scripts.logger import make_log



# entry point for after_install hook
def after_install() -> None:
    pass