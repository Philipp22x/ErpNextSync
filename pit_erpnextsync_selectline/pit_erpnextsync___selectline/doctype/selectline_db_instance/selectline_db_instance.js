// Copyright (c) 2025, PIT IT GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Selectline DB Instance", {
	refresh(frm) {

	},
    test_connection(frm) {
        connection_test(frm);
    }
});


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
