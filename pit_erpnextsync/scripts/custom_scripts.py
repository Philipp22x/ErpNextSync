import frappe
from frappe.model.document import Document
from frappe.utils.background_jobs import enqueue

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller


#*## WEBSHOP ITEMS #######################################################################################################################


@frappe.whitelist()
def bulk_create_webshop_item():
    """
    Create Website Items for all Items that don't have one yet.
    
    Only creates for Items that:
    - Are not disabled
    - Are sales items
    - Are NOT variant items (variant_of not set)
    - Don't already have a Website Item linked
    
    Note: Variant items (variant_of is set) are handled automatically 
    by the website/webshop and don't need their own Website Item.
    
    Returns dict with counts: queued, skipped, errors
    """
    try:
        # Create Website Items for:
        # 1. Template items (has_variants=1) - variants handled automatically by webshop
        # 2. Single/standalone items (has_variants=0 AND not a variant)
        # Skip variant items (variant_of is set) as they're handled automatically
        items = frappe.get_all(
            "Item",
            filters={
                "disabled": 0,
                "is_sales_item": 1,
                "variant_of": ["is", "not set"],
            },
            fields=["name", "item_name", "has_variants", "variant_of"],
            limit=0
        )
        
        if not items:
            return {"queued": 0, "skipped": 0, "errors": 0, "message": "No items found"}
        
        # Check which items already have website items
        existing_web_items = frappe.get_all(
            "Website Item",
            filters={},
            fields=["item_code"],
            limit=0,
            pluck="item_code"
        )
        existing_set = set(existing_web_items)
        
        # Filter to items needing website items
        items_to_create = []
        skipped = 0
        
        for item in items:
            # Skip if already has website item
            if item.name in existing_set:
                skipped += 1
                continue
            
            items_to_create.append(item)
        
        if not items_to_create:
            return {
                "queued": 0, 
                "skipped": skipped, 
                "errors": 0,
                "message": "All template items already have Website Items"
            }
        
        # Process in batches to avoid overwhelming the job queue
        # Use a background job for the actual creation to handle large volumes
        batch_size = 100
        total_queued = 0
        
        for i in range(0, len(items_to_create), batch_size):
            batch = items_to_create[i:i + batch_size]
            enqueue(
                "pit_erpnextsync.scripts.custom_scripts._create_webshop_items_batch",
                queue="long",
                timeout=1800,
                job_id=f"pes_webitem_batch:{i}",
                items=batch,
                queue_each=False  # Process batch inline in one job
            )
            total_queued += len(batch)
        
        make_log(
            f"Queued {total_queued} Website Item creation jobs (skipped {skipped} existing)",
            "INFO",
            controller.APP_NAME
        )
        
        return {
            "queued": total_queued,
            "skipped": skipped,
            "errors": 0,
            "message": f"Queued {total_queued} items for Website Item creation"
        }
        
    except Exception as e:
        make_log(
            f"Failed to queue Website Item creation: {e}",
            "ERROR",
            controller.APP_NAME,
            with_traceback=True
        )
        frappe.throw(f"Failed to create Website Items: {e}")


def _create_webshop_items_batch(items: list, queue_each: bool = False):
    """
    Process a batch of items to create Website Items.
    Called as a background job.
    """
    created = 0
    skipped = 0
    errors = 0
    error_details = []
    
    for item_data in items:
        try:
            result = create_webshop_item(
                item_code=item_data["name"],
                item_name=item_data.get("item_name")
            )
            
            if result.get("created"):
                created += 1
            elif result.get("skipped"):
                skipped += 1
            elif result.get("error"):
                errors += 1
                error_details.append(f"{item_data['name']}: {result.get('error')}")
                
        except Exception as e:
            errors += 1
            error_details.append(f"{item_data['name']}: {e}")
            make_log(
                f"Unexpected error creating Website Item for {item_data['name']}: {e}",
                "ERROR",
                controller.APP_NAME,
                with_traceback=True
            )
    
    if errors > 0:
        make_log(
            f"Website Item batch completed: {created} created, {skipped} skipped, {errors} errors. Details: {error_details[:5]}",
            "WARNING",
            controller.APP_NAME
        )
    else:
        make_log(
            f"Website Item batch completed: {created} created, {skipped} skipped, {errors} errors",
            "INFO",
            controller.APP_NAME
        )
    
    frappe.db.commit()


def create_webshop_item(item_code: str, item_name: str = None) -> dict:
    """
    Create a single Website Item for the given Item code.
    
    Args:
        item_code: The Item code to create a Website Item for
        item_name: Optional item name (fetched from DB if not provided)
    
    Returns:
        dict with keys: created (bool), skipped (bool), error (str or None), docname (str or None)
    """
    try:
        # Check if item exists
        if not frappe.db.exists("Item", item_code):
            return {
                "created": False,
                "skipped": False,
                "error": f"Item {item_code} does not exist",
                "docname": None
            }
        
        # Check if Website Item already exists
        existing = frappe.get_all(
            "Website Item",
            filters={"item_code": item_code},
            pluck="name",
            limit=1
        )
        if existing:
            return {
                "created": False,
                "skipped": True,
                "error": None,
                "docname": existing[0]
            }
        
        # Get item details
        item_doc: Document = frappe.get_doc("Item", item_code)
        
        # Prepare Website Item fields
        web_item_data = {
            "doctype": "Website Item",
            "item_code": item_code,
            "web_item_name": item_name or item_doc.item_name or item_code,
            "item_name": item_doc.item_name or item_code,
            "item_group": item_doc.item_group,
            "stock_uom": item_doc.stock_uom,
            "description": item_doc.description or "",
            "has_variants": item_doc.has_variants,
            "variant_of": item_doc.variant_of,
            "published": 1,
            "route": f"products/{frappe.scrub(item_code)}",
        }
        
        # Copy brand if exists
        if item_doc.get("brand"):
            web_item_data["brand"] = item_doc.brand
        
        # Copy image if exists
        if item_doc.get("image"):
            web_item_data["website_image"] = item_doc.image
        
        # Create the document
        new_doc: Document = frappe.get_doc(web_item_data)
        
        # Insert with appropriate flags
        new_doc.insert(
            ignore_permissions=True,
            ignore_mandatory=True,
            ignore_links=True,
            ignore_if_duplicate=True
        )
        
        make_log(
            f"Created Website Item {new_doc.name} for Item {item_code}",
            "INFO",
            controller.APP_NAME
        )
        
        return {
            "created": True,
            "skipped": False,
            "error": None,
            "docname": new_doc.name
        }
        
    except frappe.exceptions.DuplicateEntryError:
        # Race condition: another process created it between our check and insert
        existing = frappe.get_all(
            "Website Item",
            filters={"item_code": item_code},
            pluck="name",
            limit=1
        )
        return {
            "created": False,
            "skipped": True,
            "error": None,
            "docname": existing[0] if existing else None
        }
        
    except Exception as e:
        make_log(
            f"Could not create Website Item for {item_code}: {e}",
            "ERROR",
            controller.APP_NAME,
            with_traceback=True
        )
        return {
            "created": False,
            "skipped": False,
            "error": str(e),
            "docname": None
        }