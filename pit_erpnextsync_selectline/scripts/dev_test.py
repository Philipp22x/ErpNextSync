import frappe



def test():
    child_doc = frappe.get_doc({
        "doctype": "Selectline Mapping Entry",
        "name": "bliblabub"
    })

    print(child_doc.name)

    child_doc.flags.name_set = True

    child_doc.insert(ignore_mandatory=True)
    frappe.db.commit()

    print(child_doc.name)