import frappe
from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller




#*## WEBSHOP ITEMS #######################################################################################################################
@frappe.whitelist()
def bulk_create_webshop_item():
    items = frappe.get_all(
        "Item",
        filters={
            "variant_of": ["is", "not set"],
            "has_variants": 1
        },
        pluck="name"
    )
    
    for item in items:
        frappe.enqueue(
            "pit_erpnextsync.scripts.custom_scripts.create_webshop_item",
            queue="long",
            item_name=item
        )


def create_webshop_item(item_name):
    try:
        new_doc = frappe.get_doc({
            "doctype": "Website Item",
            "item_code": item_name
        })
        
        new_doc.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.commit()

    except Exception as e:
        make_log(f"Could not create new website item: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
