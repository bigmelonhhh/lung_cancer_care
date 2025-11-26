"""web_sales 视图模块."""

from .dashboard import sales_dashboard
from .account import sales_change_password
from .patient_entry import patient_entry
from .patient_detail import patient_detail

__all__ = ["sales_dashboard", "sales_change_password", "patient_entry", "patient_detail"]
