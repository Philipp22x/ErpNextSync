import frappe

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync_selectline.scripts import controller
from pit_erpnextsync_selectline.scripts.data_import import start_import
from pit_erpnextsync_selectline.scripts.update import run_bulk_update



# get list of db instances
def get_instances(repetition: str) -> list:
    enabled_instances: list = frappe.get_all(
        "Selectline DB Instance",
        filters={
            "enabled": 1,
            "repetition": repetition
        },
        fields=[
            "name", 
            "enable_scheduler", 
            "repetition",
            "amount_of_data_rows",
            "types_to_import"
        ]
    )

    return enabled_instances


# scheduler event hooks
def all() -> None:
    run(get_instances("all"))

def daily() -> None:
    run(get_instances("daily"))

def weekly() -> None:
    run(get_instances("weekly"))

def monthly() -> None:
    run(get_instances("monthly"))


# run import / update
def run(instances: list) -> None:
    make_log(f"Scheduled import/update ({instance_data.get('repetation')}) for {instance_data.get('name')} is starting...", "INFO", controller.APP_NAME)

    if not instances:
        return
    
    for instance_data in instances:

        if not instance_data.get("enable_scheduler"):
            continue

        try:   
            start_import(
                instance=instance_data.get("name"), 
                top=instance_data.get("amount_of_data_rows"), 
                types_str=instance_data.get("types_to_import")
            )

            run_bulk_update(
                instance=instance_data.get("name"), 
                types_str=instance_data.get("types_to_import")
            )

            make_log(f"Background jobs for import/update ({instance_data.get('repetation')}) for {instance_data.get('name')} created successfully", "INFO", controller.APP_NAME)

        except Exception as e:
            make_log(f"Could not run scheduled import/update for {instance_data.get('name')}: {e}", "ERROR", controller.APP_NAME, with_traceback=True)
            continue