# Fill / repair the prices of the purchase orders mirrored by the sync instance
# "officeno1_purchase_orders" and keep them on the USD buying price list.
#
# ERPNext PIT-TASK-2027-000365, ADJUSTMENT 3 (see
# app_data/documentation/PIT-TASK-2027-000365_purchase_order_prices.md).
#
# What the mirrored orders are
# ----------------------------
# The 24 mirrored purchase orders (naming series LNG-BE-2026-.####) are USD
# orders like the customer's own manually created purchase orders of the same
# suppliers (LNG-BE-2026-0007 .. 0041 and 0043): currency USD, price list
# currency USD, buying price list "Standard-Kauf-USD", conversion_rate 0.86207
# (the rate the customer uses in his own USD purchase orders; ERPNext has no
# Currency Exchange record on this site). The 4D source (BESTELLUNG.Waehrung)
# carries "EUR"/"Eur" for all open orders and is therefore not used for the
# currency any more (mapping fields currency/buying_price_list/conversion_rate
# are fixed defaults since ADJUSTMENT 3).
#
# Price sources
# -------------
# * BESTELLUNGpos.Preis_EK is the order line price and is mirrored 1:1 into
#   rate/price_list_rate - these lines keep their source price value.
# * For 224 of the 500 mirrored order lines 4D has Preis_EK = 0; the only
#   maintained purchasing price for those articles is the USD price
#   (Artikel.EK_USD -> Item Price list "Standard-Kauf-USD", migration mapping
#   type EKItemPricesUSD). Those lines are filled from "Standard-Kauf-USD"
#   (PRIMARY lookup). "Standard-Kauf" (EUR, Artikel.LETZTER_EK_NTO) is only
#   the FALLBACK for an article without a USD price (ADJUSTMENT 3: the order of
#   the two price lists was inverted; before, the EUR list was asked first and
#   the USD price was multiplied with usd_to_eur_rate).
#
# What this script does (per mirrored, submitted purchase order)
# --------------------------------------------------------------
# 1. Header: currency/price_list_currency = USD, conversion_rate and
#    plc_conversion_rate = usd_to_eur_rate, buying_price_list =
#    "Standard-Kauf-USD" - written only when the value differs.
# 2. Order lines with rate = 0: fill rate/price_list_rate from
#    "Standard-Kauf-USD", else from "Standard-Kauf" (rounded to the currency
#    precision, 2 decimals). Lines that already carry a price (the mirrored 4D
#    Preis_EK) keep their value.
# 3. ERPNext recalculates the line amounts and the header totals in the new
#    document currency (calculate_taxes_and_totals() + set_total_in_words()):
#    amount = qty x rate, base_* = amount x conversion_rate. Only fields whose
#    value really changes are written, so a hook run on unchanged data is a
#    no-op (idempotent) and a second sync cycle changes nothing.
#    stock_uom_rate is kept in line with rate (the import path skips ERPNext's
#    set_qty_as_per_stock_uom, which leaves stock_uom_rate at 0 on imported
#    lines); uom and stock_uom are identical on all mirrored lines.
#
# The lines of a mirrored order are also repaired inside the same sync cycle
# when the update phase re-writes a 4D Preis_EK of 0.0 (update.py skips only
# None/"", not 0.0) - this hook runs after the import/update phase.
#
# Nothing else is touched: the 40 manually created purchase orders, other sync
# instances (officeno1_migration, officeno1_sales_orders, stock_reconciliation),
# other doctypes, quantities and delivery quantities.
#
# Change the rate in usd_to_eur_rate if the customer changes it.

instance_name = "officeno1_purchase_orders"
usd_price_list = "Standard-Kauf-USD"
eur_price_list = "Standard-Kauf"
usd_currency = "USD"
usd_to_eur_rate = 0.86207
dry_run = 0

mapping_names = frappe.get_all(
    "Sync Mapping",
    filters={"selectline_db_instance": instance_name},
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

filled_usd = 0
filled_eur = 0
missing_price = 0
changed_lines = 0
changed_pos = []
changed_fields = 0

item_fields_to_write = [
    "rate",
    "price_list_rate",
    "base_rate",
    "base_price_list_rate",
    "amount",
    "base_amount",
    "net_rate",
    "net_amount",
    "base_net_rate",
    "base_net_amount",
    "stock_uom_rate"
]

head_fields_to_write = [
    "total",
    "base_total",
    "net_total",
    "base_net_total",
    "total_taxes_and_charges",
    "base_total_taxes_and_charges",
    "grand_total",
    "base_grand_total",
    "rounding_adjustment",
    "base_rounding_adjustment",
    "rounded_total",
    "base_rounded_total",
    "in_words",
    "base_in_words"
]

for po_name in po_names:
    try:
        po = frappe.get_doc("Purchase Order", po_name)

        if po.docstatus == 1:
            # 1) header - the mirrored order is a USD order on the USD price list
            head_values = {}

            if po.currency != usd_currency:
                head_values["currency"] = usd_currency
            if abs(float(po.conversion_rate or 0) - usd_to_eur_rate) > 1e-9:
                head_values["conversion_rate"] = usd_to_eur_rate
            if po.price_list_currency != usd_currency:
                head_values["price_list_currency"] = usd_currency
            if abs(float(po.plc_conversion_rate or 0) - usd_to_eur_rate) > 1e-9:
                head_values["plc_conversion_rate"] = usd_to_eur_rate
            if po.buying_price_list != usd_price_list:
                head_values["buying_price_list"] = usd_price_list

            for key in head_values:
                po.set(key, head_values[key])

            # 2) order lines: fill prices that the 4D source does not have
            for item in po.items:
                new_rate = None
                source = ""

                if not item.rate:
                    price = frappe.db.get_value(
                        "Item Price",
                        {"item_code": item.item_code, "price_list": usd_price_list, "buying": 1},
                        "price_list_rate"
                    )
                    source = "usd"

                    if not price:
                        price = frappe.db.get_value(
                            "Item Price",
                            {"item_code": item.item_code, "price_list": eur_price_list, "buying": 1},
                            "price_list_rate"
                        )
                        source = "eur"

                    if price:
                        if price > 0:
                            new_rate = round(float(price), 2)

                    if new_rate is None:
                        missing_price = missing_price + 1
                    elif source == "usd":
                        filled_usd = filled_usd + 1
                    else:
                        filled_eur = filled_eur + 1
                else:
                    # the mirrored source order price (4D BESTELLUNGpos.Preis_EK)
                    # stays untouched - it is not a price list price
                    new_rate = item.rate
                    source = "source"

                if new_rate is not None:
                    if abs(float(item.rate or 0) - new_rate) > 1e-9:
                        changed_lines = changed_lines + 1

                    item.rate = new_rate
                    item.price_list_rate = new_rate

                    if item.uom == item.stock_uom:
                        item.stock_uom_rate = new_rate

            # 3) ERPNext recalculates amounts and totals in the document currency.
            #    The orders that carry tax rows hit ERPNext's item tax template
            #    validation, which looks up the Item Group master - these
            #    articles carry the SelectLine article group NUMBER as
            #    item_group and deliberately have no Item Group master on this
            #    site (webshop tolerance, ERPNext PIT-TASK-2027-000346), so the
            #    validation raises "Item Group <n> not found" in a background
            #    job. Retry once with the item tax templates hidden (they are
            #    not written, they are restored afterwards); the tax rows of
            #    these orders are +20% / -20% on net total, i.e. their tax total
            #    is 0 either way.
            calculated = 0
            templates_hidden = {}

            try:
                po.calculate_taxes_and_totals()
                calculated = 1
            except Exception as calc_error:
                for item in po.items:
                    if item.item_tax_template:
                        templates_hidden[item.name] = item.item_tax_template
                        item.item_tax_template = ""

                if templates_hidden:
                    try:
                        po.calculate_taxes_and_totals()
                        calculated = 1
                    except Exception:
                        frappe.log_error(
                            message="calculation without item tax templates failed for "
                            + str(po_name) + " after: " + str(calc_error),
                            title="Fill purchase order prices"
                        )
                else:
                    frappe.log_error(
                        message="calculation failed for " + str(po_name) + ": "
                        + str(calc_error),
                        title="Fill purchase order prices"
                    )

            for item in po.items:
                if item.name in templates_hidden:
                    item.item_tax_template = templates_hidden[item.name]

            if calculated == 1:
                # the document totals in words are part of validate() in ERPNext,
                # the calculation above does not fill them
                po.set_total_in_words()

            # ... and only the values that really change are written
            item_values_to_write = {}

            if calculated == 1:
                for item in po.items:
                    stored = frappe.db.get_value(
                        "Purchase Order Item",
                        item.name,
                        item_fields_to_write,
                        as_dict=True
                    )
                    row_values = {}

                    for fieldname in item_fields_to_write:
                        if abs(float(stored.get(fieldname) or 0) - float(item.get(fieldname) or 0)) > 1e-9:
                            row_values[fieldname] = item.get(fieldname)

                    if row_values:
                        item_values_to_write[item.name] = row_values

                for fieldname in head_fields_to_write:
                    current_value = frappe.db.get_value("Purchase Order", po_name, fieldname)
                    new_value = po.get(fieldname)

                    if fieldname in ("in_words", "base_in_words"):
                        if str(current_value or "") != str(new_value or ""):
                            head_values[fieldname] = new_value
                    else:
                        if abs(float(current_value or 0) - float(new_value or 0)) > 1e-9:
                            head_values[fieldname] = new_value

                if not dry_run:
                    for item_name in item_values_to_write:
                        frappe.db.set_value(
                            "Purchase Order Item",
                            item_name,
                            item_values_to_write[item_name]
                        )

                    if head_values:
                        frappe.db.set_value("Purchase Order", po_name, head_values)

                if head_values:
                    changed_fields = changed_fields + len(head_values)
                if item_values_to_write:
                    changed_pos.append(po_name)
                    changed_fields = changed_fields + len(item_values_to_write)

        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            message="fill purchase order prices failed for " + str(po_name) + ": " + str(e),
            title="Fill purchase order prices"
        )
        frappe.db.commit()

print(
    "fill purchase order prices: orders=" + str(len(po_names))
    + " changed_orders=" + str(len(changed_pos))
    + " changed_lines=" + str(changed_lines)
    + " filled_from_usd_price_list=" + str(filled_usd)
    + " filled_from_eur_price_list=" + str(filled_eur)
    + " no_price_found=" + str(missing_price)
    + " written_field_values=" + str(changed_fields)
    + " dry_run=" + str(dry_run)
)
print("fill purchase order prices: changed orders " + str(changed_pos))
