from odoo import models, fields
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

    venta_anulada = fields.Boolean(
        string="Venta Anulada",
        default=False,
    )

    motivo_anulacion = fields.Text(
        string="Motivo de Anulación",
    )

    usuario_anulacion_id = fields.Many2one(
        "res.users",
        string="Anulado por",
    )

    fecha_anulacion = fields.Datetime(
        string="Fecha de Anulación",
    )

    sunat_excluir_resumen = fields.Boolean(
        string="Excluir de Resumen SUNAT",
        default=False,
    )

    orden_reversa_id = fields.Many2one(
        "pos.order",
        string="Orden Reversa",
        readonly=True,
    )

    orden_original_anulada_id = fields.Many2one(
        "pos.order",
        string="Orden Original Anulada",
        readonly=True,
    )

    es_reversa_anulacion = fields.Boolean(
        string="Es Reversa de Anulación",
        default=False,
    )

    def action_anular_venta(self):
        self.ensure_one()

        sunat_state = getattr(self, "sunat_state", False)

        if sunat_state in [
            "aceptado",
            "accepted",
        ]:
            raise UserError(
                "No se puede anular este documento porque ya fue enviado o aceptado por SUNAT. "
                "Debe manejarse con nota de crédito."
            )

        return {
            "type": "ir.actions.act_window",
            "name": "Anular Venta",
            "res_model": "pos.anular.venta.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_pos_order_id": self.id,
            },
        }

    def action_confirmar_anulacion(self, motivo):
        self.ensure_one()

        if self.venta_anulada:
            raise UserError("Esta venta ya fue anulada anteriormente.")

        if self.session_id.state == "closed":

            sesion_abierta_misma_caja = self.env["pos.session"].search(
                [
                    ("state", "=", "opened"),
                    ("config_id", "=", self.config_id.id),
                ],
                limit=1,
            )

            if not sesion_abierta_misma_caja:
                raise UserError(
                    "No hay una sesión abierta de la misma caja/POS."
                    "Abra la caja correspondiente para realizar la anulación."
                )

        if len(self.payment_ids) != 1:
            raise UserError(
                "La venta tiene múltiples métodos de pago. "
                "No se puede anular automáticamente desde este módulo. "
                "Debe revisarse manualmente por administración."
            )

        sunat_state = getattr(self, "sunat_state", False)

        if sunat_state in ["aceptado", "accepted"]:
            raise UserError(
                "No se puede anular este documento porque ya fue enviado o aceptado por SUNAT. "
                "Debe manejarse con nota de crédito."
            )

        self.write(
            {
                "venta_anulada": True,
                "motivo_anulacion": motivo,
                "usuario_anulacion_id": self.env.user.id,
                "fecha_anulacion": fields.Datetime.now(),
                "sunat_excluir_resumen": True,
                "sunat_state": "anulado",
                "sunat_message": "Documento anulado antes del envio a SUNAT",
            }
        )

        refund_order = self._refund()

        original_payment = self.payment_ids[0]

        refund_order.add_payment(
            {
                "name": "Anulación de venta %s" % self.name,
                "pos_order_id": refund_order.id,
                "amount": -abs(original_payment.amount),
                "payment_date": fields.Datetime.now(),
                "payment_method_id": original_payment.payment_method_id.id,
            }
        )

        refund_order.action_pos_order_paid()
        refund_order._create_order_picking()

        refund_order.write(
            {
                "es_reversa_anulacion": True,
                "orden_original_anulada_id": self.id,
                "sunat_excluir_resumen": True,
                "sunat_document_type": "NV",
                "sunat_document_number": False,
                "sunat_state": "no_aplica",
                "sunat_message": "Reversa interna por anulación de venta",
            }
        )

        self.write(
            {
                "orden_reversa_id": refund_order.id,
            }
        )

        self.message_post(body="Venta anulada mediante control interno POS.")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Venta anulada",
                "message": "La venta fue anulada correctamente.",
                "type": "success",
                "sticky": False,
            },
        }
