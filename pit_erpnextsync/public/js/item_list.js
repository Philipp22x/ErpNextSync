frappe.listview_settings['Item'] = {
	onload: function(listview) {
		listview.page.add_actions_menu_item(__("Create Missing Website Items"), function() {
			frappe.confirm(
				__('This will create Website Items for all Items (templates and single items) that do not have one yet. Variant items are handled automatically. Continue?'),
				function() {
					frappe.call({
						method: 'pit_erpnextsync.scripts.custom_scripts.bulk_create_webshop_item',
						freeze: true,
						freeze_message: __('Creating Website Items...'),
						callback: function(r) {
							if (r.message) {
								let result = r.message;
								let msg = __('Queued {0} Website Item creation jobs.', [result.queued]);
								if (result.skipped > 0) {
									msg += ' ' + __('Skipped {0} items (already have Website Items).', [result.skipped]);
								}
								if (result.errors > 0) {
									msg += ' ' + __('{0} items had errors.', [result.errors]);
								}
								frappe.show_alert({
									message: msg,
									indicator: result.errors > 0 ? 'orange' : 'green'
								}, 10);
								listview.refresh();
							}
						},
						error: function(r) {
							frappe.show_alert({
								message: __('Failed to create Website Items. Please check Error Log.'),
								indicator: 'red'
							}, 10);
						}
					});
				}
			);
		});
	}
};