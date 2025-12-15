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
    }
});


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
