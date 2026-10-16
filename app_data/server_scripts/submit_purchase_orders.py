# Submit the purchase orders that were created / updated by the
# officeno1_purchase_orders sync instance and keep the header field
# per_received in line with the already delivered qty of the positions
# (OfficeNo1 BESTELLUNGpos.MengeGeliefert -> Purchase Order Item.received_qty).
#
# Runs as a Sync Instance Hook (after import / after update) via
# controller.trigger_hooks() -> Server Script.execute_method() (safe_exec):
# it has no doc context and selects its own documents. Only documents that
# belong to this sync instance are touched - the manually created purchase
# orders are never submitted.
#
# Site specific quirks handled here:
#  * Item.item_group carries the SelectLine article-group NUMBER which
#    deliberately has no Item Group master record (see the webshop app,
#    scripts/item_group_tolerance.py, ERPNext PIT-TASK-2027-000346). In an
#    HTTP request the webshop tolerance makes ERPNext validation work; in a
#    background job / server script it is not installed (safe_exec cannot
#    import modules), so validation of such items fails with
#    "Item Group <n> not found". The first attempt therefore runs the normal
#    ERPNext validation; documents that ERPNext cannot validate are mirrored
#    anyway (the import mapping of this instance ignores validation as well),
#    but with everything ERPNext needs filled in explicitly: uom/stock_uom,
#    conversion factor, amounts/taxes via calculate_taxes_and_totals() and
#    the status via set_status().
#  * Some source orders carry a delivery date before the order date; ERPNext
#    rejects "Reqd by Date cannot be before Transaction Date". The item's
#    Required By is clamped to the order date - the original source date stays
#    visible in the header field custom_shipping_date.

mapping_names = frappe.get_all(
    "Sync Mapping",
    filters={"selectline_db_instance": "officeno1_purchase_orders"},
    pluck="name"
)

po_names = []

for mapping_name in mapping_names:
    entries = frappe.get_all(
        "Sync Mapping Entry",
        filters={"parent": mapping_name, "mapping_doctype": "Purchase Order"},
        fields=["docname"],
        limit=1
    )
    for entry in entries:
        if entry.docname:
            if entry.docname not in po_names:
                po_names.append(entry.docname)

for po_name in po_names:
    try:
        po = frappe.get_doc("Purchase Order", po_name)

        if po.docstatus == 2:
            po = None
        else:
            total_qty = 0.0
            received_qty = 0.0
            for item in po.items:
                total_qty = total_qty + item.qty
                item_received = item.received_qty
                if not item_received:
                    item_received = 0.0
                if item_received > item.qty:
                    item_received = item.qty
                received_qty = received_qty + item_received

            per_received = 0
            if total_qty > 0:
                per_received = received_qty / total_qty * 100

            if po.docstatus == 0:
                for item in po.items:
                    if not item.stock_uom:
                        item.stock_uom = item.uom
                    if not item.conversion_factor:
                        item.conversion_factor = 1
                    if item.schedule_date:
                        if po.transaction_date:
                            if item.schedule_date < po.transaction_date:
                                item.schedule_date = po.transaction_date

                po.per_received = per_received

                # first try with the full ERPNext validation so that amounts,
                # taxes and the status are calculated by ERPNext itself
                try:
                    po.save()
                    po.submit()
                except Exception as e:
                    frappe.log_error(
                        message="purchase order validation failed for " + str(po_name) + ": " + str(e),
                        title="Submit purchase orders"
                    )
                    po.reload()
                    for item in po.items:
                        if not item.stock_uom:
                            item.stock_uom = item.uom
                        if not item.conversion_factor:
                            item.conversion_factor = 1
                        # ignore_validate skips ERPNext's own
                        # BuyingController.set_qty_as_per_stock_uom(), which leaves
                        # stock_qty at 0 while qty > 0. Fill it explicitly so the
                        # fallback document really matches a validated one.
                        if not item.stock_qty:
                            if item.qty:
                                item.stock_qty = item.qty * item.conversion_factor
                        if item.schedule_date:
                            if po.transaction_date:
                                if item.schedule_date < po.transaction_date:
                                    item.schedule_date = po.transaction_date
                    # ERPNext fills the (mandatory) tax category from the
                    # supplier master - do the same, otherwise the mirrored
                    # document would stay without it. Suppliers without a tax
                    # category keep the source state (empty), just like a
                    # document entered through the UI.
                    if not po.tax_category:
                        supplier_tax_category = frappe.db.get_value(
                            "Supplier", po.supplier, "tax_category"
                        )
                        if supplier_tax_category:
                            po.tax_category = supplier_tax_category
                    po.flags.ignore_validate = True
                    po.flags.ignore_mandatory = True
                    po.per_received = per_received
                    po.calculate_taxes_and_totals()
                    po.save()
                    po.submit()
                    po.set_status(update=True)
            else:
                if po.docstatus == 1:
                    # Repair stock_qty on orders that were submitted through the
                    # fallback path before this was filled in (rows created by the
                    # first runs carry stock_qty 0 while qty > 0).
                    for item in po.items:
                        if not item.stock_qty:
                            if item.qty:
                                conversion_factor = item.conversion_factor
                                if not conversion_factor:
                                    conversion_factor = 1
                                item_stock_qty = item.qty * conversion_factor
                                frappe.db.set_value(
                                    "Purchase Order Item",
                                    item.name,
                                    "stock_qty",
                                    item_stock_qty
                                )
                    # per_received is stored as float(21,9), i.e. rounded to 9
                    # decimals, while this calculation is full precision
                    # (95.789473684 stored vs 95.78947368421052 calculated).
                    # A plain "!=" would therefore be true on every partial
                    # delivery and write into the submitted order on every sync
                    # cycle (modified bump, no value change). Compare with a
                    # tolerance so a hook run on unchanged data stays a no-op.
                    if abs((po.per_received or 0) - per_received) > 1e-6:
                        frappe.db.set_value(
                            "Purchase Order", po_name, "per_received", per_received
                        )
                        po.reload()
                        po.set_status(update=True)

        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            message="purchase order hook failed for " + str(po_name) + ": " + str(e),
            title="Submit purchase orders"
        )
        frappe.db.commit()

