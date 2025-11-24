import frappe
from frappe.model.document import Document

from pit_erpnextsync_selectline.scripts import controller
from pit_erpnext.scripts.logger import make_log



# entry point for after_install hook
def after_install() -> None:
    install_default_table_mapping()


@frappe.whitelist()
def install_default_table_mapping() -> None:
    try:
        settings_doc = controller.get_settings_doc()

        if not settings_doc:
            make_log(f"Could not get settings doc to install default table mapping", "WARNING", controller.APP_NAME)
            return None
        
        default_mapping: list = controller.get_default_table_mapping()

        if not settings_doc:
            make_log(f"Could not get default table mapping data", "WARNING", controller.APP_NAME)
            return None
        
        settings_doc.table_mapping = []
        
        for row in default_mapping:
            settings_doc.append("table_mapping", {
                "type": row["type"],
                "table_name": row["table_name"],
                "primary_key": row["primary_key"]
            })

        settings_doc.save()

    except Exception as e:
        make_log(f"Could install default table mapping: {e}", "ERROR", controller.APP_NAME)
        return None
