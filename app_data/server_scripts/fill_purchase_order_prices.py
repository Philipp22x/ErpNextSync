# Prices / price list of the purchase orders mirrored by the sync instance
# "officeno1_purchase_orders": every line is priced from the buying price list
# of the order's currency.
#
# ERPNext PIT-TASK-2027-000365, ADJUSTMENT 4 (see
# app_data/documentation/PIT-TASK-2027-000365_purchase_order_prices.md).
#
# User feedback (2026-09-28): "can you please check where prices are dollar in
# source db set price list to dollar and if euro set pricelist to euro".
#
# The currency of a mirrored order follows the currency in which the purchase
# prices of that order are maintained in the source (OfficeNo1 / 4D):
#   * Supplier.default_currency / default_price_list - the customer's own
#     configuration on the Supplier master. His 40 manually created purchase
#     orders of the same suppliers follow it in 40/40 orders and 1357/1357
#     lines (rate == price list price of that list).
#   * Chinese / Indian suppliers  -> USD + "Standard-Kauf-USD"
#     (4D Artikel.EK_USD -> Item Price list "Standard-Kauf-USD"; every line of
#     these orders has a price on that list, and most of them have no source
#     order price at all).
#   * German suppliers (33078, 33345, 33486, 33547) -> EUR + "Standard-Kauf"
#     (4D Artikel.LETZTER_EK_NTO -> Item Price list "Standard-Kauf"; the 4D
#     order price BESTELLUNGpos.Preis_EK equals that list price in 132 of 133
#     lines).
#   * Suppliers without a currency on the Supplier master (33551, 33552) are
#     resolved from the data: the price list that has a price for EVERY line of
#     the order decides (only "Standard-Kauf-USD" qualifies for these orders).
#
# What this script does (per mirrored, submitted purchase order)
# --------------------------------------------------------------
# 1. Determine the order's price list (supplier master, else price coverage of
#    the lines) and with it currency / price_list_currency (USD or EUR),
#    conversion_rate and plc_conversion_rate (0.86207 for USD - the rate the
#    customer uses in his own USD purchase orders, ERPNext has no Currency
#    Exchange record on this site; 1.0 for EUR) and buying_price_list.
#    Every value is written only when it really differs.
# 2. Price EVERY line from that price list: rate = price_list_rate = the
#    price list price, rounded to the currency precision (2 decimals). This is
#    the customer's own convention in all his manual purchase orders. The 4D
#    source price BESTELLUNGpos.Preis_EK is NOT used as the line price: it is
#    the EUR book value of the line (measured: it equals the EUR price list
#    price to the cent in 271 of 276 priced lines, also in the USD suppliers'
#    orders) and must not be mixed into a USD price list. A line without a
#    price on its own list keeps its current rate (never a price from the other
#    currency's list) and is counted as no_price_found.
# 3. ERPNext recalculates the line amounts and the header totals in the new
#    document currency (calculate_taxes_and_totals() + set_total_in_words()):
#    amount = qty x rate, base_* = amount x conversion_rate. Only fields whose
#    value really changes are written, so a hook run on unchanged data is a
#    no-op (idempotent) and a second sync cycle changes nothing.
#    stock_uom_rate is kept in line with rate (the import path skips ERPNext's
#    set_qty_as_per_stock_uom, which leaves stock_uom_rate at 0 on imported
#    lines); uom and stock_uom are identical on all mirrored lines.
#
# Nothing else is touched: the 40 manually created purchase orders, other sync
# instances (officeno1_migration, officeno1_sales_orders, stock_reconciliation),
# other doctypes, quantities and delivery quantities.
#
# Change usd_to_eur_rate if the customer changes his rate.

instance_name = "officeno1_purchase_orders"
usd_price_list = "Standard-Kauf-USD"
eur_price_list = "Standard-Kauf"
usd_currency = "USD"
eur_currency = "EUR"
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

changed_lines = 0
changed_pos = []
changed_fields = 0
missing_price = 0
orders_usd = 0
orders_eur = 0
from_supplier = 0
from_lines = 0
order_log = []

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
            # 1) which currency / price list does THIS order belong to?
            supplier_price_list = frappe.db.get_value(
                "Supplier", po.supplier, "default_price_list"
            )
            supplier_currency = frappe.db.get_value(
                "Supplier", po.supplier, "default_currency"
            )

            if not supplier_price_list:
                supplier_price_list = ""
            if not supplier_currency:
                supplier_currency = ""

            known_list = 0
            if supplier_price_list == usd_price_list:
                known_list = 1
            if supplier_price_list == eur_price_list:
                known_list = 1
            if known_list == 0:
                supplier_price_list = ""

            resolved_from = "supplier"

            if not supplier_price_list:
                # no currency maintained on the Supplier master - the price
                # list that actually carries a price for every line of the
                # order decides
                resolved_from = "line_coverage"
                lines_have_usd = 1
                lines_have_eur = 1

                for item in po.items:
                    usd_price = frappe.db.get_value(
                        "Item Price",
                        {"item_code": item.item_code, "price_list": usd_price_list, "buying": 1},
                        "price_list_rate"
                    )
                    eur_price = frappe.db.get_value(
                        "Item Price",
                        {"item_code": item.item_code, "price_list": eur_price_list, "buying": 1},
                        "price_list_rate"
                    )
                    if not usd_price:
                        lines_have_usd = 0
                    if not eur_price:
                        lines_have_eur = 0

                if supplier_currency == usd_currency:
                    if lines_have_usd == 1:
                        supplier_price_list = usd_price_list
                if not supplier_price_list:
                    if supplier_currency == eur_currency:
                        if lines_have_eur == 1:
                            supplier_price_list = eur_price_list
                if not supplier_price_list:
                    if lines_have_usd == 1:
                        supplier_price_list = usd_price_list
                if not supplier_price_list:
                    if lines_have_eur == 1:
                        supplier_price_list = eur_price_list

                if supplier_price_list:
                    from_lines = from_lines + 1
            else:
                from_supplier = from_supplier + 1

            if supplier_price_list == usd_price_list:
                price_list = usd_price_list
                order_currency = usd_currency
                order_rate = usd_to_eur_rate
                orders_usd = orders_usd + 1
            else:
                price_list = eur_price_list
                order_currency = eur_currency
                order_rate = 1.0
                orders_eur = orders_eur + 1

            # 2) header - written only when the value differs
            head_values = {}

            if po.currency != order_currency:
                head_values["currency"] = order_currency
            if abs(float(po.conversion_rate or 0) - order_rate) > 1e-9:
                head_values["conversion_rate"] = order_rate
            if po.price_list_currency != order_currency:
                head_values["price_list_currency"] = order_currency
            if abs(float(po.plc_conversion_rate or 0) - order_rate) > 1e-9:
                head_values["plc_conversion_rate"] = order_rate
            if po.buying_price_list != price_list:
                head_values["buying_price_list"] = price_list

            for key in head_values:
                po.set(key, head_values[key])

            # 3) order lines: every line is priced from the price list of the
            #    order's currency
            order_changed_lines = 0

            for item in po.items:
                new_rate = None
                price = frappe.db.get_value(
                    "Item Price",
                    {"item_code": item.item_code, "price_list": price_list, "buying": 1},
                    "price_list_rate"
                )

                if price:
                    if price > 0:
                        new_rate = round(float(price), 2)

                if new_rate is None:
                    # never take a price out of the other currency's list -
                    # keep what the line has and report it
                    missing_price = missing_price + 1
                    new_rate = item.rate

                if new_rate is not None:
                    if abs(float(item.rate or 0) - new_rate) > 1e-9:
                        order_changed_lines = order_changed_lines + 1
                        changed_lines = changed_lines + 1

                    item.rate = new_rate
                    item.price_list_rate = new_rate

                    if item.uom == item.stock_uom:
                        item.stock_uom_rate = new_rate

            # 4) ERPNext recalculates amounts and totals in the document currency.
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

            order_log.append(
                po_name + " supplier=" + str(po.supplier) + " currency=" + str(order_currency)
                + " price_list=" + str(price_list) + " rate=" + str(order_rate)
                + " source=" + str(resolved_from) + " lines=" + str(len(po.items))
                + " changed_lines=" + str(order_changed_lines)
            )

        frappe.db.commit()
    except Exception as e:
        frappe.log_error(
            message="fill purchase order prices failed for " + str(po_name) + ": " + str(e),
            title="Fill purchase order prices"
        )
        frappe.db.commit()

print(
    "fill purchase order prices: orders=" + str(len(po_names))
    + " usd_orders=" + str(orders_usd)
    + " eur_orders=" + str(orders_eur)
    + " price_list_from_supplier=" + str(from_supplier)
    + " price_list_from_line_coverage=" + str(from_lines)
    + " changed_orders=" + str(len(changed_pos))
    + " changed_lines=" + str(changed_lines)
    + " no_price_found=" + str(missing_price)
    + " written_field_values=" + str(changed_fields)
    + " dry_run=" + str(dry_run)
)
print("fill purchase order prices: changed orders " + str(changed_pos))
for log_line in order_log:
    print("fill purchase order prices: order " + log_line)
