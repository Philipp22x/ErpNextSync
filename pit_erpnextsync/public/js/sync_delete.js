// PIT ERPNextSync – synced document delete override
//
// When a synced document (Sales Order, Item, Customer, Supplier) is
// deleted, the standard delete would fail with a LinkValidationError
// because Sync Mapping Entry references it via a Dynamic Link.  This
// script intercepts frm.savetrash (the method the Delete menu button
// calls), shows a dialog informing the user that the Sync Mapping will
// also be removed, and offers to add an Import Ignore Rule so the
// record is not re-imported.

const PIT_SYNC_DTYPES = ["Sales Order", "Item", "Customer", "Supplier"];

PIT_SYNC_DTYPES.forEach(function (dt) {
	frappe.ui.form.on(dt, {
		setup(frm) {
			// Override savetrash synchronously on setup so there is no
			// race condition — the check runs at click time, not on refresh.
			if (frm.__pit_sync_override) return;
			frm.__pit_sync_override = true;

			const original_savetrash = frm.savetrash.bind(frm);
			frm.savetrash = function () {
				frappe
					.xcall("pit_erpnextsync.scripts.sync_delete.is_doc_synced", {
						doctype: frm.doctype,
						docname: frm.doc.name,
					})
					.then((synced) => {
						if (synced) {
							pit_sync_show_delete_dialog(frm);
						} else {
							original_savetrash();
						}
					})
					.catch(() => {
						original_savetrash();
					});
			};
		},
	});
});

function pit_sync_show_delete_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Delete Synced Document"),
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<div class="pb-3">
						<p>${__("This document is synced from SelectLine via PIT ERPNextSync.")}</p>
						<p>${__("Deleting it will also remove the associated Sync Mapping.")}</p>
						<p><strong>${__(
							"Add an Import Ignore Rule to prevent this document from being re-imported?"
						)}</strong></p>
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
	frappe.dom.freeze(__("Deleting..."));
	frappe
		.xcall("pit_erpnextsync.scripts.sync_delete.delete_synced_doc", {
			doctype: frm.doctype,
			docname: frm.doc.name,
			add_ignore_rule: add_ignore_rule,
		})
		.then(() => {
			frappe.dom.unfreeze();
			frappe.show_alert({
				message: __("Document deleted successfully"),
				indicator: "green",
			});
			frappe.set_route("List", frm.doctype);
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
