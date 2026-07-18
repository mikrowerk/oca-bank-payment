# Copyright 2026 mikrowerk - Guenther Froestl
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

{
    "name": "Account Payment Order Early Payment Discount",
    "summary": "Apply early payment discounts on payment orders",
    "version": "17.0.1.0.0",
    "category": "Banking addons",
    "author": "mikrowerk Guenther Froestl, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/bank-payment",
    "license": "AGPL-3",
    "depends": ["account_payment_order"],
    "data": ["views/account_payment_order.xml"],
    "installable": True,
    "auto_install": False,
    "application": False,
}
