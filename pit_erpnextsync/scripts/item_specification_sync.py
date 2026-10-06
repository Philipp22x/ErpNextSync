# Copyright (c) 2026, PIT IT and contributors
# For license information, please see license.txt
"""
Incremental sync of dbo.ShopSachmerkmale (4D/MSSQL) into the pit_erpnext
Specification module and the Item specification tables.

Design notes:
- The source table has NO timestamp column, so there is no delta feed: each run
  reads the full assignment set and only WRITES items whose stored
  `custom_specification_json` differs from the desired one (idempotent, cheap).
- Reference data (Specification / Specification Value / Specification Template
  child rows) is auto-created when the source introduces new names/values.
  Existing docs are extended via direct SQL so the app's `on_update` hooks do
  not trigger a 12k-item doc cascade.
- The item-level JSON must contain ALL template specifications with the full
  option map (the webshop filter accesses `parsed[spec]["values"][option]`
  without a guard); items not present in the source are left untouched.

Entry points:
    sync_item_specifications(instance)                 # used by the pipeline
    main()  (bench execute)                            # manual run: default DRY, "run" arg = write
"""
import sys
import json
import frappe
from frappe.utils import now_datetime

from pit_erpnext.scripts.logger import make_log
from pit_erpnextsync.scripts import controller

TEMPLATE_NAME = "HTX"
SOURCE_TABLE = "ShopSachmerkmale"

LOG_TAG = controller.APP_NAME


# --------------------------------------------------------------------- source

def _source_has_table(instance: str) -> bool:
    """Cheap existence check so instances without the table are skipped silently."""
    try:
        rows = controller.fetch_data(
            instance,
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = '%s'" % SOURCE_TABLE,
        )
        return bool(rows)
    except Exception:
        return False


def _read_source(instance: str) -> tuple[dict, dict]:
    """Return ({spec_name: {values}}, {article: {spec_name: set(values)}})."""
    rows = controller.fetch_data(
        instance,
        "SELECT [Artikelnummer], [Sachmerkmalbezeichnung], [Bezeichnung] "
        "FROM dbo.%s WHERE Typ = 2" % SOURCE_TABLE,
    ) or []
    spec_values: dict[str, set] = {}
    assign: dict[str, dict[str, set]] = {}
    for row in rows:
        spec = row.get("Sachmerkmalbezeichnung")
        art = row.get("Artikelnummer")
        val = row.get("Bezeichnung")
        if not spec or not val or not str(val).strip():
            continue
        spec_values.setdefault(spec, set()).add(val)
        if art:
            assign.setdefault(art, {}).setdefault(spec, set()).add(val)
    return {k: sorted(v) for k, v in spec_values.items()}, assign


# ------------------------------------------------------- reference data (docs)

def _ensure_specification_values(values: list[str]) -> int:
    existing = set(frappe.get_all("Specification Value", pluck="name"))
    created = 0
    for v in values:
        if v in existing:
            continue
        d = frappe.new_doc("Specification Value")
        d.specification_value_name = v
        d.insert(ignore_permissions=True)
        created += 1
    return created


def _ensure_specifications(spec_values: dict[str, list[str]]) -> int:
    """Create missing Specification docs; extend existing ones via SQL (no hooks)."""
    created = 0
    for spec, values in spec_values.items():
        doc_name = frappe.db.get_value("Specification", {"specification_name": spec})
        if not doc_name:
            d = frappe.new_doc("Specification")
            d.specification_name = spec
            d.selection_mode = "Multiple selection"  # refined below when values known
            for v in values:
                d.append("specification_value", {"specification_value": v})
            d.insert(ignore_permissions=True)
            created += 1
            continue
        have = set(frappe.get_all(
            "Specification Value Table",
            filters={"parent": doc_name, "parenttype": "Specification"},
            pluck="specification_value",
        ))
        missing = [v for v in values if v not in have]
        if missing:
            now = now_datetime()
            sql = ("INSERT INTO `tabSpecification Value Table` "
                   "(name,creation,modified,modified_by,owner,parent,parenttype,parentfield,idx,docstatus,specification_value) "
                   "VALUES (%s,%s,%s,'Administrator','Administrator',%s,'Specification','specification_value',%s,0,%s)")
            for i, v in enumerate(missing, start=len(have) + 1):
                frappe.db.sql(sql, (frappe.generate_hash(length=10), now, now, doc_name, i, v))
    return created


def _ensure_template(spec_values: dict[str, list[str]]) -> None:
    """Create the template if missing; extend its child rows via direct SQL (no hooks)."""
    if not frappe.db.exists("Specification Template", TEMPLATE_NAME):
        d = frappe.new_doc("Specification Template")
        d.specification_template_name = TEMPLATE_NAME
        for spec in sorted(spec_values):
            d.append("specification", {"specification": spec, "available_for_filtering": 1})
        d.insert(ignore_permissions=True)
        frappe.db.commit()
        return
    have = set(frappe.get_all(
        "Specification Table",
        filters={"parent": TEMPLATE_NAME, "parenttype": "Specification Template"},
        pluck="specification",
    ))
    missing = [s for s in sorted(spec_values) if s not in have]
    if missing:
        now = now_datetime()
        sql = ("INSERT INTO `tabSpecification Table` "
               "(name,creation,modified,modified_by,owner,parent,parenttype,parentfield,idx,docstatus,specification,available_for_filtering) "
               "VALUES (%s,%s,%s,'Administrator','Administrator',%s,'Specification Template','specification',%s,0,%s,1)")
        for i, s in enumerate(missing, start=len(have) + 1):
            frappe.db.sql(sql, (frappe.generate_hash(length=10), now, now, TEMPLATE_NAME, i, s))


def _load_reference() -> dict[str, dict]:
    """Live reference data: {spec: {selection_mode, options:[...]}} from ERPNext docs."""
    ref: dict[str, dict] = {}
    for row in frappe.get_all(
        "Specification Table",
        filters={"parent": TEMPLATE_NAME, "parenttype": "Specification Template"},
        fields=["specification", "available_for_filtering"],
        order_by="idx",
    ):
        doc = frappe.db.get_value(
            "Specification", row.specification,
            ["selection_mode"], as_dict=True,
        )
        options = frappe.get_all(
            "Specification Value Table",
            filters={"parent": row.specification, "parenttype": "Specification"},
            pluck="specification_value",
            order_by="idx",
        )
        if doc is None:
            continue
        ref[row.specification] = {
            "selection_mode": doc.selection_mode,
            "available_for_filtering": row.available_for_filtering,
            "options": options,
        }
    return ref


# ------------------------------------------------------------------ item fill

def _desired_json(ref: dict[str, dict], item_values: dict[str, set]) -> str:
    data = {}
    for spec, cfg in ref.items():
        true_vals = item_values.get(spec) or set()
        data[spec] = {
            "selection_mode": "radio" if cfg["selection_mode"] == "Single selection" else "checkbox",
            "values": {opt: (opt in true_vals) for opt in cfg["options"]},
        }
    return frappe.as_json(data)


def _ensure_item_rows(item: str, specs: list[str]) -> int:
    """Insert missing `tabItem Specification` rows for one item (direct SQL, no hooks)."""
    have = set(frappe.db.get_values(
        "Item Specification", {"parent": item, "parenttype": "Item"},
        "specification", as_dict=False,
    ))
    missing = [s for s in specs if s not in have]
    if not missing:
        return 0
    now = now_datetime()
    sql = ("INSERT INTO `tabItem Specification` "
           "(name,creation,modified,modified_by,owner,parent,parenttype,parentfield,idx,docstatus,specification) "
           "VALUES (%s,%s,%s,'Administrator','Administrator',%s,'Item','custom_item_specification',%s,0,%s)")
    for i, s in enumerate(missing, start=len(have) + 1):
        frappe.db.sql(sql, (frappe.generate_hash(length=10), now, now, item, i, s))
    return len(missing)


def sync_item_specifications(instance: str) -> dict:
    """Full compare / minimal write pass. Returns a stats dict for logging."""
    stats = {"skipped_no_table": False, "values_created": 0, "specifications_created": 0,
             "template_child_rows_added": 0, "items_scanned": 0, "items_changed": 0,
             "item_rows_added": 0, "items_missing_in_erpnext": 0}
    if not _source_has_table(instance):
        stats["skipped_no_table"] = True
        return stats

    spec_values, assign = _read_source(instance)
    if not spec_values:
        stats["skipped_no_table"] = True
        return stats

    stats["values_created"] = _ensure_specification_values(
        sorted({v for values in spec_values.values() for v in values}))
    frappe.db.commit()
    stats["specifications_created"] = _ensure_specifications(spec_values)
    frappe.db.commit()
    _ensure_template(spec_values)
    frappe.db.commit()

    ref = _load_reference()
    specs = list(ref.keys())

    # only items that exist in ERPNext
    articles = list(assign.keys())
    existing: dict[str, dict] = {}
    for i in range(0, len(articles), 2000):
        chunk = articles[i:i + 2000]
        for row in frappe.get_all("Item", filters={"name": ["in", chunk]},
                                  fields=["name", "custom_specification_template", "custom_specification_json"]):
            existing[row["name"]] = row
    stats["items_missing_in_erpnext"] = len(articles) - len(existing)

    for art, values_by_spec in assign.items():
        item_row = existing.get(art)
        if not item_row:
            continue
        stats["items_scanned"] += 1
        desired = _desired_json(ref, values_by_spec)
        changed = frappe.parse_json(item_row.get("custom_specification_json") or "{}") != frappe.parse_json(desired)
        wrong_template = item_row.get("custom_specification_template") != TEMPLATE_NAME
        if not changed and not wrong_template:
            continue
        added = _ensure_item_rows(art, specs)
        stats["item_rows_added"] += added
        updates = {"custom_specification_json": desired}
        if wrong_template:
            updates["custom_specification_template"] = TEMPLATE_NAME
        frappe.db.set_value("Item", art, updates, update_modified=False)
        stats["items_changed"] += 1
        if stats["items_changed"] % 500 == 0:
            frappe.db.commit()
            make_log("item_specification_sync: %d items changed" % stats["items_changed"], "INFO", LOG_TAG)
    frappe.db.commit()

    if stats["items_changed"]:
        try:
            from webshop.webshop.redisearch_utils import reindex_all_web_items
            reindex_all_web_items()
        except Exception as e:
            make_log("item_specification_sync reindex failed: %r" % (e,), "ERROR", LOG_TAG)
        try:
            from webshop.webshop.api import clear_listing_cache
            clear_listing_cache()
        except Exception as e:
            make_log("item_specification_sync clear_listing_cache failed: %r" % (e,), "ERROR", LOG_TAG)
        frappe.clear_cache()
    return stats


def _run_in_cycle(instance: str) -> None:
    """Pipeline hook (called by scheduler after import/update)."""
    try:
        stats = sync_item_specifications(instance)
        if stats.get("skipped_no_table"):
            make_log("item_specification_sync: no %s table for %s - skipped" % (SOURCE_TABLE, instance), "INFO", LOG_TAG)
        else:
            make_log("item_specification_sync for %s: %s" % (instance, json.dumps(stats)), "INFO", LOG_TAG)
    except Exception as e:
        make_log("item_specification_sync failed for %s: %r" % (instance, e), "ERROR", LOG_TAG, with_traceback=True)


def main():
    MODE = "dry" if (len(sys.argv) > 1 and sys.argv[1] == "dry") else "run"
    instance = "hella_sl"
    if MODE == "dry":
        if not _source_has_table(instance):
            print("no %s table for %s" % (SOURCE_TABLE, instance)); return
        spec_values, assign = _read_source(instance)
        ref = _load_reference()
        print("specs in source: %d | values: %d | articles: %d" % (
            len(spec_values), sum(len(v) for v in spec_values.values()), len(assign)))
        print("template specs (live): %s" % sorted(ref.keys()))
        articles = list(assign.keys())
        have = set()
        for i in range(0, len(articles), 2000):
            have |= set(frappe.get_all("Item", filters={"name": ["in", articles[i:i + 2000]]}, pluck="name"))
        print("articles existing in ERPNext: %d (missing %d)" % (len(have), len(articles) - len(have)))
        changed = 0
        for art, values_by_spec in assign.items():
            if art not in have:
                continue
            desired = _desired_json(ref, values_by_spec)
            cur = frappe.db.get_value("Item", art, "custom_specification_json")
            if frappe.parse_json(cur or "{}") != frappe.parse_json(desired):
                changed += 1
        print("DRY - items that would change: %d" % changed)
        return
    stats = sync_item_specifications(instance)
    print("stats:", json.dumps(stats))

main()