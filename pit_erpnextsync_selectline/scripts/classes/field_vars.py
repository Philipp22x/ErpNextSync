


class FieldVars:

    def __init__(self):    
        self.field_vars_list: list = []

    def get_field_vars(self) -> list:
        return self.field_vars_list
    
    def get_field_var_value(self, var_name: str) -> any:
        for entry in self.field_vars_list:
            if entry.get("var_name") == var_name:
                return entry.get("value")

    def add_field_var(self, field_var: dict) -> None:
        self.field_vars_list.append(field_var)

    def add_field_var_value(self, var_name: str, value: any) -> None:
        for entry in self.field_vars_list:
            if entry.get("var_name") == var_name:
                entry["value"] = value