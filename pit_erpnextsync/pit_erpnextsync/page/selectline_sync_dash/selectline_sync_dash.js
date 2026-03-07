frappe.pages['selectline-sync-dash'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'SelectLine Sync Dashboard',
		single_column: true
	});

	let html = frappe.render_template("selectline_sync_dash", {
        // template context variables go here
        message: "Hello from Jinja!"
    });

    $(page.main).html(html);
}