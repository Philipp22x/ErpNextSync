# Fill the missing prices on the purchase orders mirrored by the sync instance
# "officeno1_purchase_orders".
#
# ERPNext PIT-TASK-2027-000365, ADJUSTMENT 2 (see
# app_data/documentation/PIT-TASK-2027-000365_purchase_order_prices.md).
#
# Why this script exists
# ----------------------
# * OfficeNo1 (4D) keeps the order line price in BESTELLUNGpos.Preis_EK. For 224
#   of the 500 mirrored order lines that column is 0 - the import therefore
#   mirrors 0 into rate/price_list_rate of the Purchase Order Item.
# * For exactly those items the only maintained purchasing price in 4D is the
#   USD price (Artikel.EK_USD -> Item Price list "Standard-Kauf-USD",
#   migration mapping type EKItemPricesUSD). The EUR price list
#   ("Standard-Kauf", source column Artikel.LETZTER_EK_NTO, type
#   EKItemPricesEUR) has no price for 220 of the 224 items.
# * The mirrored orders themselves are EUR orders: 4D BESTELLUNG.Waehrung is
#   EUR/Eur for all 24 orders (the database uses EUR/Eur/ATS only, USD never
#   appears), so the price has to be written in EUR.
# * The USD->EUR rate used below is the one the customer uses in his own
#   manually created USD purchase orders of the same suppliers
#   (LNG-BE-2026-0007 .. LNG-BE-2026-0041: conversion_rate 0.86207,
#   LNG-BE-2026-0043 of 2026-07-02: 0.8785). There is no ERPNext
#   "Currency Exchange" record on this site to take the rate from.
#   If the rate changes, update usd_to_eur_rate here.
#
# What it does
# ------------
# For every order line of the mirrored purchase orders whose rate is still 0 the
# missing price is filled
#   1. from the EUR buying price list "Standard-Kauf" when it carries a price, else
#   2. from the USD buying price list "Standard-Kauf-USD" converted with
#      usd_to_eur_rate.
# Item amounts and the header totals are recalculated by ERPNext itself
# (calculate_taxes_and_totals / set_total_in_words), so the order total always
# stays consistent with its lines.
#
# Nothing else is touched: lines that already carry a price, the 40 manually
# created purchase orders, other sync instances, other doctypes.
# The script is idempotent - it only fills rows whose rate is 0, so hook runs on
# unchanged data are a no-op. It is registered as a Sync Instance Hook (after
# import / after update), i.e. it also repairs a price that the update phase
# wrote back to 0 from an unchanged 4D Preis_EK in the same sync cycle.

instance_name = "officeno1_purchase_orders"
eur_price_list = "Standard-Kauf"
usd_price_list = "Standard-Kauf-USD"
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

filled_eur = 0
filled_usd = 0
missing_price = 0
changed_pos = []

for po_name in po_names:
    try:
        po = frappe.get_doc("Purchase Order", po_name)

        if po.docstatus == 1:
            changed_rows = []

            for item in po.items:
                if not item.rate:
                    price = frappe.db.get_value(
                        "Item Price",
                        {"item_code": item.item_code, "price_list": eur_price_list, "buying": 1},
                        "price_list_rate"
                    )
                    source = "EUR price list " + eur_price_list

                    if not price:
                        usd_price = frappe.db.get_value(
                            "Item Price",
                            {"item_code": item.item_code, "price_list": usd_price_list, "buying": 1},
                            "price_list_rate"
                        )
                        if usd_price:
                            if usd_to_eur_rate:
                                price = usd_price * usd_to_eur_rate
                                source = "USD price list " + usd_price_list + " x " + str(usd_to_eur_rate)

                    if price:
                        if price > 0:
                            rate = round(price, 2)
                            item.rate = rate
                            item.price_list_rate = rate
                            item.base_rate = rate * po.conversion_rate
                            item.base_price_list_rate = rate * po.conversion_rate
                            changed_rows.append(item.name)
                            if source.startswith("USD"):
                                filled_usd = filled_usd + 1
                            else:
                                filled_eur = filled_eur + 1
                    else:
                        missing_price = missing_price + 1

            if changed_rows:
                po.calculate_taxes_and_totals()
                po.set_total_in_words()
                changed_pos.append(po_name)

                if not dry_run:
                    for item in po.items:
                        if item.name in changed_rows:
                            frappe.db.set_value("Purchase Order Item", item.name, {
                                "rate": item.rate,
                                "price_list_rate": item.price_list_rate,
                                "base_rate": item.base_rate,
                                "base_price_list_rate": item.base_price_list_rate,
                                "amount": item.amount,
                                "base_amount": item.base_amount,
                                "net_rate": item.net_rate,
                                "net_amount": item.net_amount,
                                "base_net_rate": item.base_net_rate,
                                "base_net_amount": item.base_net_amount
                            })

                    frappe.db.set_value("Purchase Order", po_name, {
                        "total": po.total,
                        "base_total": po.base_total,
                        "net_total": po.net_total,
                        "base_net_total": po.base_net_total,
                        "total_taxes_and_charges": po.total_taxes_and_charges,
                        "base_total_taxes_and_charges": po.base_total_taxes_and_charges,
                        "grand_total": po.grand_total,
                        "base_grand_total": po.base_grand_total,
                        "rounding_adjustment": po.rounding_adjustment,
                        "base_rounding_adjustment": po.base_rounding_adjustment,
                        "rounded_total": po.rounded_total,
                        "base_rounded_total": po.base_rounded_total,
                        "in_words": po.in_words,
                        "base_in_words": po.base_in_words
                    })

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
    + " filled_from_eur_price_list=" + str(filled_eur)
    + " filled_from_usd_price_list=" + str(filled_usd)
    + " no_price_found=" + str(missing_price)
    + " dry_run=" + str(dry_run)
)
print("fill purchase order prices: changed orders " + str(changed_pos))
