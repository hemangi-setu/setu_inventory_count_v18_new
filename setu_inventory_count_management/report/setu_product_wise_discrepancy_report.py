# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools
from odoo.osv import expression


class SetuProductWiseDiscrepancyReport(models.Model):
    _name = "setu.product.wise.discrepancy.report"
    _description = "Product-wise Discrepancy Report"
    _auto = False

    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    approver_id = fields.Many2one("res.users", string="Approver", readonly=True)
    total_times_counted = fields.Integer(string="Total Times Counted", readonly=True)
    discrepancy_products = fields.Integer(string="Discrepancy Products", readonly=True)
    discrepancy_percent = fields.Float(string="Discrepancy %", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self._cr, self._table)
        self._cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    -- unique id required by Odoo
                    MIN(l.id) AS id,

                    -- grouping key
                    l.product_id AS product_id,

                    -- metrics
                    COUNT(l.id) AS total_times_counted,

                    SUM(
                        CASE
                            WHEN l.is_discrepancy_found = TRUE THEN 1
                            ELSE 0
                        END
                    ) AS discrepancy_products,

                    ROUND(
                        (
                            SUM(
                                CASE
                                    WHEN l.is_discrepancy_found = TRUE THEN 1
                                    ELSE 0
                                END
                            )::decimal
                            / NULLIF(COUNT(l.id), 0)
                        ) * 100,
                        2
                    ) AS discrepancy_percent,

                    -- keep company-wise aggregation (no approver split)
                    c.company_id AS company_id,
                    MIN(c.approver_id) AS approver_id

                FROM setu_stock_inventory_count_line l
                JOIN setu_stock_inventory_count c
                    ON c.id = l.inventory_count_id

                WHERE
                    c.state NOT IN ('Rejected', 'Cancel')
                    AND l.state != 'Reject'

                GROUP BY
                    l.product_id,
                    c.company_id
            )
        """)
