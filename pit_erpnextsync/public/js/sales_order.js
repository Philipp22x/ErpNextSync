// PIT ERPNextSync – Sales Order delete override
//
// When a synced Sales Order is deleted, the standard delete would fail with
// a LinkValidationError because Sync Mapping Entry references it via a
// Dynamic Link.  This script intercepts the delete action, shows a dialog
// informing the user that the Sync Mapping will also be removed, and offers
// to add an Import Ignore Rule so the order is not re-imported.

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.is_new()) return;
		pit_sync_setup_delete_override(frm);
	},
});

function pit_sync_setup_delete_override(frm) {
	// Avoid double-wrapping on repeated refresh calls.
	if (frm.toolbar.__pit_sync_override) return;

	frappe
		.xcall("pit_erpnextsync.scripts.sales_order_sync.is_sales_order_synced", {
			sales_order_name: frm.doc.name,
		})
		.then((synced) => {
			if (!synced) return;

			frm.toolbar.__pit_sync_override = true;
			frm.toolbar.delete_doc = function () {
				pit_sync_show_delete_dialog(frm);
			};
		});
}

function pit_sync_show_delete_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Delete Synced Sales Order"),
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<div class="pb-3">
						<p>This Sales Order is synced from SelectLine via PIT ERPNextSync.</p>
						<p>Deleting it will also remove the associated Sync Mapping.</p>
						<p><strong>Add an Import Ignore Rule to prevent this order from being re-imported?</strong></p>
					</div>
				`,
			},
		],
		primary_action_label: __("Yes, prevent re-import"),
		primary_action: () => {
			d.hide();
			pit_sync_do_delete(frm, true);
		},
		secondary_action_label: __("No, just delete"),
		secondary_action: () => {
			d.hide();
			pit_sync_do_delete(frm, false);
		},
	});
	d.show();
}

function pit_sync_do_delete(frm, add_ignore_rule) {
	frappe.dom.freeze(__("Deleting Sales Order..."));
	frappe
		.xcall("pit_erpnextsync.scripts.sales_order_sync.delete_synced_sales_order", {
			sales_order_name: frm.doc.name,
			add_ignore_rule: add_ignore_rule,
		})
		.then(() => {
			frappe.dom.unfreeze();
			frappe.show_alert({
				message: __("Sales Order deleted successfully"),
				indicator: "green",
			});
			frappe.set_route("List", "Sales Order");
		})
		.catch((err) => {
			frappe.dom.unfreeze();
			frappe.msgprint({
				title: __("Delete Failed"),
				message: err.message || String(err),
				indicator: "red",
			});
		});
}
