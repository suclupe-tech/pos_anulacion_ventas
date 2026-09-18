from odoo import models, fields
from odoo.exceptions import UserError
from collections import defaultdict


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

        if sunat_state in ["aceptado", "accepted"]:
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

    # ============================================================
    # RESTAURAR STOCK COMERCIAL DE OFERTA
    #
    # Se ejecuta después de que la reversa ya devolvió físicamente
    # las prendas al almacén.
    #
    # Solo vuelve a la bolsa de oferta cuando:
    # - La línea original fue vendida como oferta.
    # - La asignación de oferta sigue activa.
    # - La oferta sigue vigente.
    #
    # Si la oferta terminó o fue desactivada, la prenda queda
    # disponible como stock regular.
    # ============================================================

    def _restore_offer_stock_after_cancellation(self):
        self.ensure_one()

        picking_type = self.config_id.picking_type_id
        warehouse = picking_type.warehouse_id if picking_type else False

        if not warehouse:
            return

        # Agrupar cantidades de oferta por modelo.
        quantities_by_template = defaultdict(float)

        for line in self.lines:
            if not line.is_offer_sale:
                continue

            if not line.product_id or line.qty <= 0:
                continue

            template = line.product_id.product_tmpl_id
            quantities_by_template[template.id] += line.qty

        if not quantities_by_template:
            return

        templates = self.env["product.template"].browse(
            list(quantities_by_template.keys())
        )

        for template in templates:
            qty_to_restore = quantities_by_template[template.id]

            # Reutilizamos el bloqueo FOR UPDATE del control de stock
            # para evitar conflictos con ventas simultáneas.
            allocation, current_offer_qty = self._get_locked_offer_allocation(
                warehouse,
                template,
            )

            # Si la oferta fue desactivada, no volvemos a reservar.
            if not allocation:
                self.message_post(
                    body=(
                        "La anulación devolvió %.2f unidad(es) de %s "
                        "al stock físico, pero no se restituyeron a oferta "
                        "porque la oferta ya no está activa."
                    )
                    % (qty_to_restore, template.display_name)
                )
                continue

            # Si la oferta venció o todavía no está vigente,
            # la prenda debe quedar como stock regular.
            validity_error = self._get_offer_validity_error(allocation)

            if validity_error:
                self.message_post(
                    body=(
                        "La anulación devolvió %.2f unidad(es) de %s "
                        "al stock físico, pero no se restituyeron a oferta "
                        "porque la vigencia ya no permite utilizarla."
                    )
                    % (qty_to_restore, template.display_name)
                )
                continue

            # Restituir la cantidad comercial.
            allocation.write(
                {
                    "quantity": allocation.quantity + qty_to_restore,
                }
            )

            # Registrar también el motivo en el chatter de la oferta.
            allocation.message_post(
                body=(
                    "Se restituyeron %.2f unidad(es) por anulación " "de la venta %s."
                )
                % (qty_to_restore, self.name)
            )

    def action_confirmar_anulacion(self, motivo):
        self.ensure_one()

        if self.venta_anulada:
            raise UserError("Esta venta ya fue anulada anteriormente.")

        sunat_state = getattr(self, "sunat_state", False)

        if sunat_state in ["aceptado", "accepted"]:
            raise UserError(
                "No se puede anular este documento porque ya fue enviado o aceptado por SUNAT. "
                "Debe manejarse con nota de crédito."
            )

        if not self.payment_ids:
            raise UserError("La venta no tiene pagos registrados para reversar.")

        # =========================================================
        # 1. DEFINIR EN QUÉ SESIÓN POS SE REGISTRARÁ LA ANULACIÓN
        # =========================================================
        session_refund = self.session_id

        if self.session_id.state == "closed":
            session_refund = self.env["pos.session"].search(
                [
                    ("state", "=", "opened"),
                    ("config_id", "=", self.config_id.id),
                ],
                limit=1,
            )

            if not session_refund:
                raise UserError(
                    "No hay una sesión abierta de la misma caja/POS. "
                    "Abra la caja correspondiente para realizar la anulación."
                )

        # =========================================================
        # 2. MARCAR LA VENTA ORIGINAL COMO ANULADA
        # =========================================================
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

        # =========================================================
        # 3. CREAR ORDEN REVERSA
        # =========================================================
        refund_order = self._refund()

        refund_order.write(
            {
                "session_id": session_refund.id,
                "config_id": session_refund.config_id.id,
                "es_reversa_anulacion": True,
                "orden_original_anulada_id": self.id,
                "sunat_excluir_resumen": True,
                "sunat_document_type": "NV",
                "sunat_document_number": False,
                "sunat_state": "no_aplica",
                "sunat_message": "Reversa interna por anulación de venta",
            }
        )

        # =========================================================
        # 4. CREAR PAGOS NEGATIVOS POR CADA MEDIO DE PAGO ORIGINAL
        # =========================================================
        for original_payment in self.payment_ids:
            if not original_payment.amount:
                continue

            refund_order.add_payment(
                {
                    "name": "Anulación de venta %s - %s"
                    % (self.name, original_payment.payment_method_id.name),
                    "pos_order_id": refund_order.id,
                    "amount": -abs(original_payment.amount),
                    "payment_date": fields.Datetime.now(),
                    "payment_method_id": original_payment.payment_method_id.id,
                    "session_id": session_refund.id,
                }
            )

        # =========================================================
        # 5. VALIDAR LA ORDEN REVERSA Y DEVOLVER STOCK
        # =========================================================
        refund_order.action_pos_order_paid()
        refund_order._create_order_picking()

        # =========================================================
        # RESTAURAR STOCK COMERCIAL DE OFERTA
        # =========================================================
        self._restore_offer_stock_after_cancellation()

        # =========================================================
        # 6. RELACIONAR VENTA ORIGINAL CON SU REVERSA
        # =========================================================
        self.write(
            {
                "orden_reversa_id": refund_order.id,
            }
        )

        self.message_post(
            body="Venta anulada mediante control interno POS con reversa por medios de pago."
        )

        refund_order.message_post(
            body="Reversa interna generada por anulación de la venta %s." % self.name
        )

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
