// Copyright (c) 2025, PIT IT GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sync Instance", {
	refresh(frm) {
        custom_action_buttons(frm);
	},
    test_connection(frm) {
        connection_test(frm);
    },
    import_json_file(frm) {
        import_json_file(frm);
    },
    reset(frm) {
        frm.set_value("types_to_import", "");
        frm.set_value("amount_of_data_rows", 0);
    }
});


function custom_action_buttons(frm){
    if (!frm.is_new()) {

        frm.add_custom_button(__('Import'), () => {
            start_import_action(frm);
        });
        frm.add_custom_button(__('Update'), () => {
            start_update_action(frm);
        });
        frm.add_custom_button(__('Preview'), () => {
            preview_reconciliation(frm);
        },__("Reconcile"));
        frm.add_custom_button(__('Apply'), () => {
            apply_reconciliation(frm);
        },__("Reconcile"));
    }
}


// start import button action
function start_import_action(frm){
    
    // check types
    let types_str = frm.doc.types_to_import
    let types_list = [];
    if (types_str){
        types_list = types_str.split(",");
    }

    let data_rows_int = frm.doc.amount_of_data_rows

    // call import
    frappe.dom.freeze(__("creating background jobs for import..."));
    frappe.call({
        method: "pit_erpnextsync.scripts.data_import.start_import",
        args:{
            "instance": frm.doc.name,
            "types_str": types_list,
            "top": data_rows_int
        },
        callback: function(r){
            frappe.dom.unfreeze();
            frappe.msgprint("Background jobs were created. Import runs in background.")
        }
    });
}


// start update button action
function start_update_action(frm){
    // check types
    let types_str = frm.doc.types_to_import
    let types_list = [];
    if (types_str){
        types_list = types_str.split(",");
    }

    // call import
    frappe.dom.freeze(__("creating background jobs for update..."));
    frappe.call({
        method: "pit_erpnextsync.scripts.update.run_bulk_update",
        args:{
            "instance": frm.doc.name,
            "types_str": JSON.stringify(types_list),
        },
        callback: function(r){
            frappe.dom.unfreeze();
            frappe.msgprint("Background jobs were created. Update runs in background.")
        }
    });
}
    

// import json mapping file
function import_json_file(frm){

    if(!frm.doc.mapping_json_file){
        frappe.msgprint(__("No file attached"))
        return;
    }

    frappe.call({
        method: "pit_erpnextsync.scripts.controller.load_table_mapping",
        args:{
            "instance": frm.doc.name
        },
        callback: function(r){
            if(r.message == "success"){
                frappe.msgprint(__("Mapping loaded successfully"))
                frm.reload_doc();
            }
        }
    });
}


// calls test for db connection
function connection_test(frm){
    frappe.dom.freeze(__("testing database connection..."));
    frappe.call({
        method: "pit_erpnextsync.scripts.controller.connection_test",
        args:{
            "instance": frm.doc.name
        },
        callback: function(r){
            if(r.message == true){
                frappe.msgprint("Connections test was successfully.")
            }else if(r.message == false || !r.message){
                frappe.msgprint("Connections test fails.")
            }
            frappe.dom.unfreeze();
        }
    });
}


// preview reconciliation button action
function preview_reconciliation(frm){
    // check types
    let types_str = frm.doc.types_to_import
    let types_list = [];
    if (types_str){
        types_list = types_str.split(",").map(t => t.trim()).filter(t => t);
    }

    frappe.dom.freeze(__("creating background jobs for reconciliation preview..."));
    frappe.call({
        method: "pit_erpnextsync.scripts.reconcile.start_reconciliation",
        args:{
            "instance": frm.doc.name,
            "types_str": JSON.stringify(types_list),
            "dry_run": true
        },
        callback: function(r){
            frappe.dom.unfreeze();
            if(r.message && r.message.status === "success"){
                frappe.msgprint({
                    title: __("Reconciliation Preview Queued"),
                    message: __("Preview queued for {0} mappings. Check Error Log for details.", [r.message.mappings_count]),
                    indicator: "blue"
                });
            } else {
                frappe.msgprint({
                    title: __("Error"),
                    message: r.message ? r.message.message : __("Unknown error"),
                    indicator: "red"
                });
            }
        }
    });
}


// apply reconciliation button action
function apply_reconciliation(frm){
    // check types
    let types_str = frm.doc.types_to_import
    let types_list = [];
    if (types_str){
        types_list = types_str.split(",").map(t => t.trim()).filter(t => t);
    }

    frappe.confirm(
        __("This will modify existing documents and mappings based on the current JSON mapping definitions. Are you sure you want to proceed?"),
        function(){
            frappe.dom.freeze(__("creating background jobs for reconciliation..."));
            frappe.call({
                method: "pit_erpnextsync.scripts.reconcile.start_reconciliation",
                args:{
                    "instance": frm.doc.name,
                    "types_str": JSON.stringify(types_list),
                    "dry_run": false
                },
                callback: function(r){
                    frappe.dom.unfreeze();
                    if(r.message && r.message.status === "success"){
                        frappe.msgprint({
                            title: __("Reconciliation Started"),
                            message: __("Reconciliation queued for {0} mappings. Check Error Log for details.", [r.message.mappings_count]),
                            indicator: "orange"
                        });
                    } else {
                        frappe.msgprint({
                            title: __("Error"),
                            message: r.message ? r.message.message : __("Unknown error"),
                            indicator: "red"
                        });
                    }
                }
            });
        }
    );
}
