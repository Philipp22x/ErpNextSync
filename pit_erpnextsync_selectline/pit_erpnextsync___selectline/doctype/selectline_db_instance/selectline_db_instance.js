// Copyright (c) 2025, PIT IT GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Selectline DB Instance", {
	refresh(frm) {

	},
    test_connection(frm) {
        connection_test(frm);
    },
    import_json_file(frm) {
        import_json_file(frm);
    },
    start_import(frm) {
        start_import_action(frm);
    },
    reset(frm) {
        frm.set_value("types_to_import", "");
        frm.set_value("amount_of_data_rows", 0);
    }
});


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
        method: "pit_erpnextsync_selectline.scripts.import.start_import",
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


// import json mapping file
function import_json_file(frm){

    if(!frm.doc.mapping_json_file){
        frappe.msgprint(__("No file attached"))
        return;
    }

    frappe.call({
        method: "pit_erpnextsync_selectline.scripts.controller.load_table_mapping",
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
        method: "pit_erpnextsync_selectline.scripts.controller.connection_test",
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
