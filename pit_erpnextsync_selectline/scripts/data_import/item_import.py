import pprint

import frappe
from frappe import _
from frappe.utils import nowdate, now
from frappe.model.document import Document
from pit_erpnextsync_selectline.scripts import controller
from pit_erpnext.scripts.tax_module.item_tax_update import update_item_taxes

from pit_erpnext.scripts.logger import make_log



# entry point for item import
def start_import(instance: str) -> str:

    default_item_mapping: dict = next((d for d in get_table_mapping() if d.get("type") == "Item"), None)

    if not default_item_mapping:
        make_log(f"Could not get the default table mapping for Item", "ERROR", controller.APP_NAME)
        return "Could not get the default table mapping for Item"

    # sql command
    fetch_sql: str = f"""
    SELECT TOP (5) {default_item_mapping["primary_key"]},
        Artikelnummer,
        EANNummer,
        Bezeichnung,
        Zusatz,
        Matchcode,
        Artikelgruppe,
        Mengeneinheit,
        Gewicht,
        Lagerartikel,
        Lieferant,
        Warencode,
        Variantenartikel
    FROM dbo.{default_item_mapping["table_name"]} 
    ORDER BY {default_item_mapping["primary_key"]} 
    """

    try:
        selectline_items: list = controller.fetch_data(instance=instance, sql=fetch_sql)

        if not selectline_items:
            make_log(f"Could not fetch any data", "ERROR", controller.APP_NAME)
            return _("Could not fetch any data -> see logs for more info")
        
        invalid_selectline_id: bool = False

        # create id and check if mapping exists -> if not create new mapping and item -> if yes check for update
        for fetched_item in selectline_items:
            selectline_id: str = f"{instance.replace(" ", "_")}:{default_item_mapping['table_name']}:{fetched_item[default_item_mapping['primary_key']]}"
            if not selectline_id:
                make_log(f"Invalid selectline id", "ERROR", controller.APP_NAME)
                invalid_selectline_id = True
                continue
 
            existing_mapping: str | None = controller.check_mapping_exists(selectline_id)

            if existing_mapping:
                frappe.enqueue(
                    "pit_erpnextsync_selectline.scripts.data_import.item_import.update_item_and_mapping",
                    queue="long",
                    timeout=600, 
                    fetched_item=fetched_item,
                    selectline_id=selectline_id,
                    instance=instance,
                    existing_mapping=existing_mapping
                )
            else:
                frappe.enqueue(
                    "pit_erpnextsync_selectline.scripts.data_import.item_import.create_item_and_mapping",
                    queue="long",
                    timeout=600,
                    fetched_item=fetched_item,
                    selectline_id=selectline_id,
                    instance=instance
                )
        
        # if some selectline ids are failed
        if invalid_selectline_id:
            return "Some ids where not valid -> check logs for more infos"

        return "success"
    
    except Exception as e:
        make_log(f"Error on fetching items: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return "Something went wrong on item import -> see logs for more infos"


# update
def update_item_and_mapping(fetched_item: dict, selectline_id: str, instance: str, existing_mapping: str) -> None:
    try:
        mapping_doc: Document = frappe.get_doc("Selectline Mapping", existing_mapping)
    except Exception as e:
        make_log(f"Could not update Selectline Mapping {existing_mapping}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return None
    
    if not mapping_doc.enable:
        return
    
    if not mapping_doc.mapping_table:
        make_log(f"Could not update Selectline Mapping {existing_mapping}: No mapping table entries", "ERROR", controller.APP_NAME)
        return None
    
    for row in mapping_doc.mapping_table:
        for key, value in fetched_item.items():
            if row.selectline_column != key:
                continue
            else:
                try:
                    # row with child docs
                    if row.child_table_doctype and row.child_table_name:
                        old_value = frappe.db.get_value(row.child_table_doctype, row.child_table_name, row.fieldname)
                        if value != old_value:
                            # set new data
                            frappe.db.set_value(row.child_table_doctype, row.child_table_name, row.fieldname, value)

                            make_log(f"Updated field {row.fieldname} in {row.child_table_doctype} {row.child_table_name} for Mapping {existing_mapping} successfully", "INFO", controller.APP_NAME)

                    # row without child docs
                    else:
                        old_value = frappe.db.get_value(row.mapping_doctype, row.docname, row.fieldname)
                        if value != old_value:
                            # set new data
                            frappe.db.set_value(row.mapping_doctype, row.docname, row.fieldname, value)

                            make_log(f"Updated field {row.fieldname} in {row.mapping_doctype} {row.docname} for Mapping {existing_mapping} successfully", "INFO", controller.APP_NAME)
                    
                    if value != old_value:
                        # make update comment on item
                        new_comment: Document = frappe.get_doc({
                            "doctype": "Comment",
                            "comment_type": "Info",
                            "reference_doctype": row.mapping_doctype,
                            "reference_name": row.docname,
                            "content": _(f"Selectline sync update changed field {row.fieldname} from {old_value} to {value}"),
                            "comment_by": "Pit Erpnextsync SelectLine"
                        })
                        new_comment.insert(ignore_permissions=True)
                    
                    # set last update timestamp
                    frappe.db.set_value("Selectline Mapping", existing_mapping, "last_update", now())

                except Exception as e:
                    make_log(f"Could not update field {row.fieldname} in {row.mapping_doctype} {row.docname} for Mapping {existing_mapping}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
                    continue


# create new item doc // run by background workers
def create_item_and_mapping(fetched_item: dict, selectline_id: str, instance: str) -> None:

    if frappe.db.exists("Item", fetched_item["Artikelnummer"]):
        make_log(f"Item with name '{fetched_item["Artikelnummer"]}' already exists", "ERROR", controller.APP_NAME)
        return

    try:
        # create item first
        new_item: Document = frappe.get_doc({
            "doctype": "Item",
            "item_code": fetched_item["Artikelnummer"],
            "item_name": f"{fetched_item["Bezeichnung"]}",
            "description":  f"{fetched_item["Zusatz"]}",
            "custom_matchcode": fetched_item["Matchcode"],
            "weight_per_unit": fetched_item["Gewicht"],
            "is_stock_item": fetched_item["Lagerartikel"],
        })
        
        # create or get item group and uom
        new_item.item_group = create_item_group(fetched_item["Artikelgruppe"])
        new_item.stock_uom = create_uom(fetched_item["Mengeneinheit"])

        # add barcode
        barcode: str = fetched_item["EANNummer"]

        if barcode:
            add_barcode(new_item, barcode)

        new_item.insert(ignore_mandatory=True, ignore_permissions=True, ignore_links=True)

        # create child mapping schema -> later merge with default mapping schema
        child_doc_mapping: list = []
        if new_item.barcodes:
            for row in new_item.barcodes:
                child_doc_mapping.append({"mapping_doctype": "Item", "docname": new_item.item_code, "child_table_doctype": "Item Barcode", "child_table_name": row.name, "fieldname": "barcode", "selectline_column": "EANNummer"})
                child_doc_mapping.append({"mapping_doctype": "Item", "docname": new_item.item_code, "child_table_doctype": "Item Barcode", "child_table_name": row.name, "fieldname": "uom", "selectline_column": "Mengeneinheit"})

        # update item taxes from tax matrix
        try:
            update_item_taxes(new_item.item_code)
            new_item.save()
        except Exception as e:
            make_log(f"Could not update item taxes for '{new_item.item_code}': {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)

        # make info comment on new item
        new_comment: Document = frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Item",
            "reference_name": new_item.item_code,
            "content": "This Item was created from Pit Erpnextsync SelectLine",
            "comment_by": "Pit Erpnextsync SelectLine"
        })
        new_comment.insert(ignore_permissions=True)

        

    except Exception as e:
        make_log(f"Could not create Item '{fetched_item["Artikelnummer"]}': {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return
    
    # create mapping for item
    try:
        static_mapping: list = get_item_mapping_schema(docname=new_item.item_code, item_group=new_item.item_group, uom=new_item.stock_uom)
        total_mapping: list = static_mapping + child_doc_mapping

        new_item_mapping: str = controller.create_mapping(
            db_instance=instance,
            selectline_id=selectline_id,
            mapping=total_mapping
        )

        if new_item_mapping in ["error", "data not valid"]:
            raise Exception

        make_log(f"Item '{new_item.item_code}' successfully created and mapped in '{new_item_mapping}'", "INFO", controller.APP_NAME)

        # create item prices
        try:
           fetch_and_create_item_prices(instance=instance, item_code=new_item.item_code)
        except Exception as e:
            make_log(f"Could not create Item Prices for '{fetched_item["Artikelnummer"]}': {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)

    except Exception as e:
        make_log(f"Could not create mapping for item '{fetched_item["Artikelnummer"]}': {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        frappe.delete_doc("Item", new_item.item_code)
        return None
    

# create item group -> return name of existing or new name
def create_item_group(sl_item_group: str) -> str | None:

    if not sl_item_group:
        return

    exists: str | None = frappe.db.exists("Item Group", sl_item_group)
    if exists:
        return exists
    
    try:
        new_item_group: Document = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": sl_item_group
        })

        new_item_group.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)
        frappe.db.commit()

        make_log(f"Item group '{sl_item_group}' successfully created", "INFO", controller.APP_NAME)
        return new_item_group.item_group_name
    
    except Exception as e:
        make_log(f"Could not create item group '{sl_item_group}': {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return None


# create uom -> return name of existing or new name
def create_uom(sl_uom) -> str:

    if not sl_uom:
        return
    
    exists: str | None = frappe.db.exists("UOM", sl_uom)
    if exists:
        return exists
    
    try:
        new_uom: Document = frappe.get_doc({
            "doctype": "UOM",
            "uom_name": sl_uom,
            "enabled": 1,
            "must_be_whole_number": 0
        })

        new_uom.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)
        frappe.db.commit()

        make_log(f"UOM '{sl_uom}' successfully created", "INFO", controller.APP_NAME)
        return new_uom.uom_name
    
    except Exception as e:
        make_log(f"Could not create UOM '{sl_uom}': {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return None
    

# add barcode to item if not already exists in barcode table
def add_barcode(item: Document, ean_number: str, ) -> None:
    if item.barcodes:
        for barcode in item.barcodes:
            if barcode.barcode == ean_number:
                return
        
    item.append("barcodes", {
        "barcode": ean_number,
        "barcode_type": "EAN",
        "uom": item.stock_uom
    })


# creates ek and vk prices if available
def fetch_and_create_item_prices(instance: str, item_code: str) -> None:

    default_item_ek_mapping: dict = next((d for d in get_table_mapping() if d.get("type") == "Item Price Buying"), None)
    default_item_vk_mapping: dict = next((d for d in get_table_mapping() if d.get("type") == "Item Price Selling"), None)

    # sql commands
    fetch_sql_for_ek: str = f"""
        SELECT {default_item_ek_mapping['primary_key']}, Artikelnummer, ESPreis, EKSeit, GeaendertAm
        FROM {default_item_ek_mapping["table_name"]}
        WHERE Artikelnummer = '{item_code}';
    """

    fetch_sql_for_vk: str = f"""
        SELECT {default_item_vk_mapping['primary_key']}, Artikelnummer, Preis, VonDatum, GeaendertAm
        FROM {default_item_vk_mapping["table_name"]}
        WHERE Artikelnummer = '{item_code}';
    """

    try:
        sl_item_ek_prices: list = controller.fetch_data(instance=instance, sql=fetch_sql_for_ek)
        sl_item_vk_prices: list = controller.fetch_data(instance=instance, sql=fetch_sql_for_vk)

        # buying price
        if sl_item_ek_prices:
            for price in sl_item_ek_prices:
                fetched_ek: dict = price.get("ESPreis")
                if not type(fetched_ek) == float:
                    continue

                if fetched_ek == 0:
                    continue

                if frappe.db.exists("Item Price", {"item_code": item_code, "buying": 1, "price_list_rate": fetched_ek}):
                    continue

                from_date: str = price.get("EKSeit") or price.get("GeaendertAm")

                try:
                    new_buying_price: Document = frappe.get_doc({
                        "doctype": "Item Price",
                        "item_code": item_code,
                        "price_list_rate": fetched_ek,
                        "uom": frappe.db.get_value("Item", item_code, "stock_uom"),
                        "price_list": frappe.db.get_single_value("Buying Settings", "buying_price_list"),
                        "valid_from": from_date or nowdate()
                    })

                    new_buying_price.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True, ignore_if_duplicate=True)
                    frappe.db.commit()

                    make_log(f"Buying Item Price for Item {item_code} with amount {fetched_ek} successfully created", "INFO", controller.APP_NAME)

                    # create mapping for buying item price
                    selectline_id: str = f"{instance.replace(" ", "_")}:{default_item_ek_mapping['table_name']}:{price[default_item_ek_mapping['primary_key']]}"

                    new_item_price_mapping: str = controller.create_mapping(
                        db_instance=instance,
                        selectline_id=selectline_id,
                        mapping=[
                            {"mapping_doctype": "Item Price", "docname": new_buying_price.name, "fieldname": "item_code", "selectline_column": "Artikelnummer"},
                            {"mapping_doctype": "Item Price", "docname": new_buying_price.name, "fieldname": "price_list_rate", "selectline_column": "ESPreis"},
                        ]
                    )

                    make_log(f"Buying Item Price mapping {new_item_price_mapping} for Item {item_code} successfully created", "INFO", controller.APP_NAME)

                except Exception as e:
                    make_log(f"Could not create Item Price for Item {item_code}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
                    continue

        # selling price
        if sl_item_vk_prices:
            for price in sl_item_vk_prices:
                fetched_vk: dict = price.get("Preis")
                if not type(fetched_vk) == float:
                    continue

                if fetched_vk == 0:
                    continue

                if frappe.db.exists("Item Price", {"item_code": item_code, "selling": 1, "price_list_rate": fetched_vk}):
                    continue

                from_date: str = price.get("VonDatum") or price.get("GeaendertAm")

                try:
                    new_selling_price: Document = frappe.get_doc({
                        "doctype": "Item Price",
                        "item_code": item_code,
                        "price_list_rate": fetched_vk,
                        "uom": frappe.db.get_value("Item", item_code, "stock_uom"),
                        "price_list": frappe.db.get_single_value("Selling Settings", "selling_price_list"),
                        "valid_from": from_date or nowdate()
                    })

                    new_selling_price.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True, ignore_if_duplicate=True)
                    frappe.db.commit()

                    make_log(f"Selling Item Price for Item {item_code} with amount {fetched_vk} successfully created", "INFO", controller.APP_NAME)

                    # create mapping for selling item price
                    selectline_id: str = f"{instance.replace(" ", "_")}:{default_item_vk_mapping['table_name']}:{price[default_item_vk_mapping['primary_key']]}"

                    new_item_price_mapping: str = controller.create_mapping(
                        db_instance=instance,
                        selectline_id=selectline_id,
                        mapping=[
                            {"mapping_doctype": "Item Price", "docname": new_selling_price.name, "fieldname": "item_code", "selectline_column": "Artikelnummer"},
                            {"mapping_doctype": "Item Price", "docname": new_selling_price.name, "fieldname": "price_list_rate", "selectline_column": "Preis"},
                        ]
                    )

                    make_log(f"Buying Item Price mapping {new_item_price_mapping} for Item {item_code} successfully created", "INFO", controller.APP_NAME)

                except Exception as e:
                    make_log(f"Could not create Item Price for Item {item_code}: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
                    continue
    
    except Exception as e:
        make_log(f"Could not create Item Price: {e} {frappe.get_traceback()}", "ERROR", controller.APP_NAME)
        return None
    

# get pre-filled mapping table data for item
def get_item_mapping_schema(docname: str, item_group: str, uom: str) -> list:
    return [
        {"mapping_doctype": "Item", "docname": docname, "fieldname": "item_code", "selectline_column": "Artikelnummer"},
        {"mapping_doctype": "Item", "docname": docname, "fieldname": "item_name", "selectline_column": "Bezeichnung"},
        {"mapping_doctype": "Item", "docname": docname, "fieldname": "description", "selectline_column": "Zusatz"},
        {"mapping_doctype": "Item", "docname": docname, "fieldname": "custom_matchcode", "selectline_column": "Matchcode"},
        {"mapping_doctype": "Item", "docname": docname, "fieldname": "weight_per_unit", "selectline_column": "Gewicht"},
        {"mapping_doctype": "Item", "docname": docname, "fieldname": "is_stock_item", "selectline_column": "Lagerartikel"},
        {"mapping_doctype": "Item Group", "docname": item_group, "fieldname": "name", "selectline_column": "Artikelgruppe"},
        {"mapping_doctype": "UOM", "docname": uom, "fieldname": "name", "selectline_column": "Mengeneinheit"},
    ]


# get table mapping
def get_table_mapping() -> list:
    default_table_mapping: list = controller.get_default_table_mapping()
    if not default_table_mapping:
        make_log(f"Could not get the default table mapping", "ERROR", controller.APP_NAME)
        return "Could not get the default table mapping"
    
    return default_table_mapping




def test():
    pprint.pprint(start_import("test instance"))

def test2():
    pprint.pprint(fetch_and_create_item_prices("test instance", "0003"))