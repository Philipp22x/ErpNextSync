# Purchase Order sync - OfficeNo1 (4D) -> ERPNext (Lang Kunstgewerbe)

Site: `portal.lang-kunstgewerbe.at` (bench `/home/user/frappe-bench`)
Sync instance: `officeno1_purchase_orders` (driver `p4d`, database `OfficeNo1`)
Synced in the same pipeline as `officeno1_migration` (customers, items, suppliers)
and `officeno1_sales_orders`.

Status: live and verified (2026-09-25). 24 open source orders mirrored as
submitted Purchase Orders, sample rows compared line by line against 4D.

## 1. What is synced

* Source headers: `BESTELLUNG` (primary key `BESTELLNR`, timestamp `LETZTEAENDERUNG`,
  order `BESTELLNR DESC`, batch size 10).
* Source lines: `BESTELLUNGpos`, related to the header through `BestellNr`
  (`multiple_query_condition: BestellNr = {BESTELLNR}`), match key `PRIMARYKEY`.
* Filter (the "not completed" criterion - only orders that are still open in the
  source are imported):

  ```sql
  t.[allesgeliefert] IS NULL OR t.[allesgeliefert] = false
  ```

  Measured against the source on 2026-09-25: 2051 orders in `BESTELLUNG`, 2027 with
  `allesgeliefert = true`, 24 with `false`, none `NULL`. `Storno` and `gesperrt` are
  `false` on **every** row, so the import does not need to exclude them separately.
  `Teilzugang` (partial delivery) orders keep `allesgeliefert = false` and are
  therefore still synced (2 of the 24) - which is what the purchasing department
  wants: those orders still have to be received and billed.
* The filter decides only which source orders are **imported**. The update phase
  addresses existing orders by primary key, so an order that later becomes fully
  delivered is still kept in line (its lines then reach `received_qty = qty` and
  ERPNext shows `To Bill`).
* Nothing is deleted by the sync: reconcile only keeps the stored `Sync Mapping
  Entry` rows in line with the mapping JSON (add/remove/structural) and never
  deletes the mirrored document - a purchase order that was really placed must stay
  in ERPNext. (Removing mirrored orders would be a business decision.)

Field mapping: see `app_data/mappings/purchase_orders.json`. Highlights:

| ERPNext | source | note |
| --- | --- | --- |
| `supplier` | `LIEFERANTENNR` | forced to string, supplier comes from `officeno1_migration` |
| `transaction_date` | `BESTELLDATUM` | |
| `naming_series` | default | `LNG-BE-2026-.####` (continues the existing, manually created series) |
| `company` | default | `Lang Kunstgewerbe GmbH` |
| `currency` | `WAEHRUNG` | value map `Eur/EUR -> EUR`, `USD -> USD`, default `EUR` |
| `buying_price_list` | `WAEHRUNG` | `USD -> Standard-Kauf-USD`, else `Standard-Kauf` |
| `custom_header_text` | `BESTELLNR` | source order number, used by the manual POs as well |
| `custom_shipping_date` | `LIEFERDATUM` | original (unchanged) source delivery date |
| `custom_confirmed_delivery_date` | `BESTAETIGTES_LIEFERDATUMK` | |
| `custom_footer_text` / `custom_additional_info_text` | `FUSSTEXT` / `BEMERKUNG` | |
| lines `item_code`, `item_name`, `qty`, `uom` | `ARTIKELNR`, `POSBEZEICHNUNG`, `MENGE`, `ME` | |
| lines `rate`, `price_list_rate` | `PREIS_EK` | |
| lines `discount_percentage` | `RABATT` | |
| lines `received_qty` | `MENGEGELIEFERT` | already delivered qty per line |
| lines `schedule_date` | `LIEFERDATUM` | Reqd by Date |
| lines `warehouse` | default | `Lagerräume - LNG` |

The line mapping deliberately leaves `net_rate`/`amount` to ERPNext: they are
calculated from `rate` and `discount_percentage`.

## 2. Hooks (submit the mirrored orders)

The import creates the Purchase Orders as **drafts** (the mapping carries
`ignore_validate`/`ignore_links`, exactly like the other instances). Two Sync
Instance Hooks call the Server Script **`submit purchase orders`**
(`trigger = after`, `action = import` and `trigger = after`, `action = update`),
which

1. walks all `Sync Mapping` rows of the instance and loads the linked Purchase Order,
2. recalculates the header field `per_received` from the line field `received_qty`
   (ERPNext does not maintain `per_received` for Purchase Orders itself),
3. submits draft orders (`docstatus 0`) - with the full ERPNext validation when
   it passes, otherwise through the documented fallback described in section 4,
4. updates `per_received` and the document status on already submitted orders -
   only when the stored value really deviates (tolerance `1e-6`, see section 3.3),
   so a hook run on unchanged data does not touch the submitted documents.

The script text is versioned as `app_data/server_scripts/submit_purchase_orders.py`.
ERPNext shows orders with `per_received = 100` as `To Bill`, partial deliveries as
`To Receive and Bill` - the same logic the manually created purchase orders follow.

## 3. Verification (live, 2026-09-25)

Full import run (real app code path, `_run_import` for the instance) plus a real
update cycle (`_run_bulk_update`): 24 orders, 24 `Sync Mapping` rows, all
`docstatus = 1`, status `To Receive and Bill`, `stock_uom` complete on every line.

Sample comparison source (4D) vs ERPNext, all values identical:

| source BestellNr | ERPNext | source sum MENGE / MENGEGELIEFERT | ERPNext sum qty / received_qty | per_received | source GESAMTNETTO | ERPNext grand_total |
| --- | --- | --- | --- | --- | --- | --- |
| 226065 (Teilzugang) | LNG-BE-2026-0060 | 190 / 182 | 190 / 182 | 95.79 | 767.70 | 767.70 |
| 226048 (Teilzugang) | LNG-BE-2026-0051 | 44 / 42 | 44 / 42 | 95.45 | 178.95 | 178.95 |
| 226071 (open) | LNG-BE-2026-0050 | 12564 / 0 | 12564 / 0 | 0.00 | 9409.92 | 9409.92 |

Line level (first lines of 226065): item 18177 qty 4 / delivered 4 / rate 4.45 /
uom `Rl.`, item 17268 qty 8 / 8 / 2.50, item 17683 qty 4 / 4 / 2.50 - identical in
4D and ERPNext, positions 39/40 (items 18220, 18221) are the not yet delivered
lines that make `Teilzugang` true in the source.

`tax_category` is filled from the supplier master (the same value ERPNext uses for
manually entered orders). Two suppliers (`33551`, `33552`) have no tax category in
their master data - their orders keep it empty, exactly as a manual order would.

### 3.1 The update phase follows a changed MengeGeliefert

Requirement 3 is not only about the import: the already delivered qty has to stay
in line when the source delivers more later. That was executed once for real. The
production 4D data was **not** modified - instead the source access was simulated:

* `controller.fetch_data` (the timestamp query of `check_timestamp`) and
  `controller.fetch_multiple_rows` (`BESTELLUNGpos` rows) were wrapped so that they
  return the real rows with `MENGEGELIEFERT` of one line raised by 1 and the
  timestamp one day later.
* `update.update_batch` -> `check_timestamp` -> `update_mapping` is the untouched
  app code; only the enqueued `update_mapping` job was executed inline instead of
  being handed to the RQ worker (the worker process would not see the simulation).

Order 226065 / `LNG-BE-2026-0060`, line `PRIMARYKEY`
`540A768A41C54EC3808584DE0EFE5A94` (`POSITIONNR` 39, `ARTIKELNR` 18220, `MENGE` 4,
`MENGEGELIEFERT` 0, simulated 1):

| step | measured |
| --- | --- |
| timestamp gate | stored `db_time_stamp` 2026-08-31 vs simulated 2026-09-01 -> not "up to date", `update_mapping` enqueued |
| line value | `Purchase Order Item` `0eml5ddf0m` `received_qty` 0.0 -> 1.0 |
| header after hook | `per_received` 95.789473684 -> 96.315789474 |

Afterwards the regular cycle was run again for real
(`_run_bulk_update(..., ignore_ts=1)`, 12.8 s, batch jobs on the `long` queue) and
it wrote the source values back: `received_qty` 1.0 -> 0.0 (line sum 182) and
`per_received` back to 95.789473684. So the update phase moves the line delivered
qty in both directions, and the header follows through the hook.

### 3.2 `stock_qty` of the fallback path (fixed in round 2)

The 11 orders that ERPNext could not validate (see section 4) had `stock_qty = 0`
on all of their line rows while `qty > 0` - 286 of the 500 child rows. Cause:
`ignore_validate` skips ERPNext's own
`BuyingController.set_qty_as_per_stock_uom()`, which normally fills `stock_qty`.

The hook now sets `stock_qty = qty * conversion_factor` in the fallback path and
repairs already submitted orders on every run. After re-running the hook
(`trigger_hooks`, 1.2 s, no new `Error Log` entry):

```
BEFORE: 500 child rows, rows with qty>0 and stock_qty==0: 286
AFTER : 500 child rows, rows with qty>0 and stock_qty==0:   0
        rows where stock_qty != qty * conversion_factor  :   0
```

The draft/fallback path itself was executed as well: `LNG-BE-2026-0068` (4 lines,
imported through the fallback) was set back to `docstatus 0` with its line
`stock_qty` zeroed and the after-import hook was triggered. The hook logged
`purchase order validation failed for LNG-BE-2026-0068: Item Group 98 not found`,
took the fallback and left the order at `docstatus 1` (`To Receive and Bill`,
`per_received` 0) with all 4 lines at `stock_qty = qty * conversion_factor`.

### 3.3 The submit hook is idempotent (fixed in round 3)

`per_received` is stored as `float(21,9)`, i.e. rounded to 9 decimals, while the
hook calculates it in full precision. The original check
`if po.per_received != per_received` was therefore true for every partial
delivery on every run and wrote into the submitted order (`modified` bump, same
value) - permanently so in the daily 04:00 cycle. The hook now compares with a
tolerance: `abs((po.per_received or 0) - per_received) > 1e-6`.

Measured on the 24 mirrored orders:

```
old check (stored != calc)          would write: 2  (LNG-BE-2026-0051, LNG-BE-2026-0060)
new check (abs(delta) > 1e-6)       would write: 0
LNG-BE-2026-0051 stored 95.454545455 vs calculated 95.45454545454545 -> delta  4.55e-10
LNG-BE-2026-0060 stored 95.789473684 vs calculated 95.78947368421052 -> delta -2.11e-10
```

Two consecutive `controller.trigger_hooks(...)` runs on unchanged data:
`modified`-changed documents: 0 (run 1) and 0 (run 2), no new `Version` rows
(131 before/after) and no new `Comment` rows (148 before/after).

The correction branch still works: `per_received` of `LNG-BE-2026-0051` was
deliberately set to `42.0`, one hook run restored `95.454545455` (status stayed
`To Receive and Bill`), and the immediately following run left `modified`
untouched again.

A full real cycle on unchanged source data (`_run_import` 0.8 s +
`_run_bulk_update` 6.5 s, hooks included) left 24 orders before/after with
`modified` changed on **0** of them, 500 child rows with 0 deviating from
`stock_qty = qty * conversion_factor` and no new `Error Log` entry - the daily
04:00 cycle is a no-op while the source does not change.

## 4. Pitfalls and known limitations

* **Server Scripts cannot import modules.** `safe_exec` blocks `import` and the
  `frappe` namespace has no `get_attr`, so the `item_group_tolerance` helper of the
  `webshop` app (which tolerates items whose numeric `item_group` has no master
  record, PIT-TASK-2027-000346) cannot be installed from a Server Script.
  ERPNext's own validation therefore fails with `Item Group <n> not found` for
  such items. The hook tries the normal `save()`/`submit()` first and only falls back
  to `ignore_validate`/`ignore_mandatory` when that fails; in that fallback it
  sets `stock_uom`/`conversion_factor`/`stock_qty` (ERPNext's own
  `set_qty_as_per_stock_uom()` is part of the skipped validation and would otherwise
  leave `stock_qty` at 0), clamps `schedule_date`, mirrors
  `tax_category` from the supplier and calls `calculate_taxes_and_totals()` /
  `set_status()` explicitly so the result matches a validated document. For orders that
  were submitted by an earlier run of the fallback (before it filled `stock_qty`), the
  hook repairs the line `stock_qty` on every subsequent run.
  A proper fix would install the tolerance for background jobs as well (app
  code, out of scope here).
* **Reqd by Date before the order date.** Some source orders carry a
  `LIEFERDATUM` older than `BESTELLDATUM` (e.g. BestellNr 226069: order 2026-07-22,
  delivery 2026-01-08). ERPNext rejects that, so the hook clamps `schedule_date` to
  `transaction_date`; the original value stays visible in `custom_shipping_date`.
* **`tax_category` is mandatory** (property setter of `pit_erpnext`) but ERPNext
  only fills it from the supplier master, which is empty for two suppliers.
* **Diagnostics against 4D:** a manual `WHERE t.[BESTELLNR] = 226065` (alias plus
  quoted column) returns 0 rows, while the connector's generated
  `WHERE BestellNr = 226065` works. Use the bare column name when querying by hand.
* `LIEFERDATUM`/`LETZTEAENDERUNG` are date-only in 4D, so timestamp based updates
  are day-granular - unchanged orders are skipped (`up to date`).

## 5. Re-running / restoring

* Re-import one instance (real app path, run with the bench python):

  ```
  cd ~/frappe-bench
  env/bin/python - <<'EOF'   # or a small script file
  import frappe
  frappe.init(site="portal.lang-kunstgewerbe.at", sites_path="/home/user/frappe-bench/sites")
  frappe.connect()
  from pit_erpnextsync.scripts.data_import import _run_import
  _run_import(instance="officeno1_purchase_orders", top=0, types_str='["PurchaseOrder"]')
  EOF
  ```

* Update cycle: `pit_erpnextsync.scripts.update._run_bulk_update(instance="officeno1_purchase_orders", types_str='["PurchaseOrder"]')`
* The hook runs automatically after both phases (Sync Instance Hooks) and can be
  re-triggered with `pit_erpnextsync.scripts.controller.trigger_hooks(instance="officeno1_purchase_orders", before_after="after", import_update="import")`.
* Configuration snapshot: `app_data/mappings/purchase_orders.json` (mapping) and
  `app_data/mappings/purchase_orders_instance.json` (instance settings + hooks,
  credentials intentionally omitted).
* The Server Script **`submit purchase orders`** on the site must be identical to
  `app_data/server_scripts/submit_purchase_orders.py` (md5
  `0476acc19539c526100c8519b4d1af4f`); install it with a small bench-python script
  that copies the file content into `Server Script.script`.
* `purchase_orders.json` is the **verbatim content of the live mapping file**
  `sites/portal.lang-kunstgewerbe.at/private/files/officeno1_purchase_order_mapping.json`
  (including its `_comment*` documentation keys and `idx`; the loader ignores the
  comment keys, they are not doctype columns). Verified by loading both variants
  through the app's own `load_table_mapping()` field logic and running the generated
  SQL against 4D - both give
  `WHERE t.[allesgeliefert] IS NULL OR t.[allesgeliefert] = false` and 24 rows.
  The earlier revision of the artifact had the filter wrapped in an extra pair of
  quotes (`query_filter: "\"t.[...] = false\""`); after the `chr(34)` strip in
  `make_sql_string()` the backslashes survived and 4D returned **0 rows** (silently
  empty import). Do not re-introduce those quotes.
