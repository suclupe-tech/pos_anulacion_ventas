from odoo import models, fields
from odoo.exceptions import UserError


class AnularVentaWizard(models.TransientModel):
    _name = "pos.anular.venta.wizard"
    _description = "Wizard Anular Venta POS"

    pos_order_id = fields.Many2one(
        "pos.order",
        string="Orden POS",
        required=True,
    )

    motivo = fields.Text(
        string="Motivo de Anulación",
        required=True,
    )

    def action_confirmar_anulacion(self):
        self.ensure_one()

        if not self.motivo or not self.motivo.strip():
            raise UserError("Debe ingresar un motivo de anulación.")

        self.pos_order_id.action_confirmar_anulacion(self.motivo)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Venta anulada",
                "message": "La venta fue anulada correctamente.",
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window_close",
                },
            },
        }
