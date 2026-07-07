from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def get_liquidacion_data(self):
        res = super().get_liquidacion_data()

        for session in self:
            # Órdenes normales: sirven para ventas reales
            orders_ventas = session.order_ids.filtered(
                lambda o: o.state in ["paid", "done"]
                and not o.es_reversa_anulacion
            )

            # Órdenes de caja: aquí SÍ deben entrar las reversas
            # porque una anulación debe restar efectivo / yape / tarjeta
            orders_caja = session.order_ids.filtered(
                lambda o: o.state in ["paid", "done"]
            )

            total_pagos_efectivo = 0.0
            total_pagos_no_efectivo = 0.0
            medios_pago = {}

            for order in orders_caja:
                for payment in order.payment_ids:
                    metodo = payment.payment_method_id.name or "SIN MÉTODO"
                    monto = payment.amount or 0.0

                    if metodo not in medios_pago:
                        medios_pago[metodo] = 0.0

                    medios_pago[metodo] += monto

                    if payment.payment_method_id.is_cash_count:
                        total_pagos_efectivo += monto
                    else:
                        total_pagos_no_efectivo += monto

            total_ventas = sum(orders_ventas.mapped("amount_total"))

            total_anulaciones = sum(
                orders_caja.filtered(
                    lambda o: o.es_reversa_anulacion
                ).mapped("amount_total")
            )

            res.update(
                {
                    "totalVentasSinAnulaciones": total_ventas,
                    "totalAnulaciones": total_anulaciones,
                    "totalEfectivoCajaReal": total_pagos_efectivo,
                    "totalMediosPagoNoEfectivo": total_pagos_no_efectivo,
                    "mediosPagoCajaReal": medios_pago,
                }
            )

        return res