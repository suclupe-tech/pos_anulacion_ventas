{
    "name": "Anulación de Ventas POS",
    "version": "1.0",
    "category": "Point of Sale",
    "summary": "Control de anulación de ventas POS con auditoría",
    "depends": [
        "point_of_sale",
        "pos_sunat_direct",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/anular_venta_wizard_views.xml",
        "views/pos_order_views.xml",
    ],
    "installable": True,
    "application": False,
}
