// Copyright (c) 2025, PIT IT GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Pit ERPNextSync - SelectLine Settings", {
	restore_default(frm) {
        restore_table_mapping(frm);
	},
});



function restore_table_mapping(frm){
    frappe.confirm(
        "Do you want to restore the mapping table?",
        () => {
            frappe.dom.freeze(__("Restore mapping table..."));
            frappe.call("pit_erpnextsync_selectline.install.install_default_table_mapping")
                .then(() => frappe.dom.unfreeze());
        },
        () => {

        }
    )
};
