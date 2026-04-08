# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools
from odoo.osv import expression


class SetuLocationWiseDiscrepancyReport(models.Model):
    _name = "setu.location.wise.discrepancy.report"
    _description = "Location-wise Discrepancy Report"
    _auto = False

    location_id = fields.Many2one("stock.location", string="Location", readonly=True)
    approver_id = fields.Many2one("res.users", string="Approver", readonly=True)
    total_products_counted = fields.Integer(string="Total Products Counted", readonly=True)
    total_discrepancy_lines = fields.Integer(string="Discrepancy Products", readonly=True)
    discrepancy_percent = fields.Float(string="Discrepancy %", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        domain = list(domain or [])
        uid = kwargs.get("access_rights_uid") or self._uid
        user = self.env["res.users"].browse(uid).sudo()
        is_manager = user.has_group("setu_inventory_count_management.group_setu_inventory_count_manager")
        is_approver = user.has_group("setu_inventory_count_management.group_setu_inventory_count_approver")
        if is_approver and not is_manager:
            domain = expression.AND([domain, [('approver_id', '=', user.id)]])
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)

    def init(self):
        tools.drop_view_if_exists(self._cr, self._table)
        self._cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(l.id) AS id,
                    l.location_id AS location_id,
                    COUNT(l.id) AS total_products_counted,
                    SUM(CASE WHEN l.is_discrepancy_found = TRUE THEN 1 ELSE 0 END) AS total_discrepancy_lines,
                    ROUND(
                        (SUM(CASE WHEN l.is_discrepancy_found = TRUE THEN 1 ELSE 0 END)::decimal /
                         NULLIF(COUNT(l.id),0)) * 100, 2
                    ) AS discrepancy_percent,
                    c.company_id AS company_id,
                    c.approver_id AS approver_id
                FROM setu_stock_inventory_count_line l
                JOIN setu_stock_inventory_count c ON c.id = l.inventory_count_id
                WHERE c.state NOT IN ('Rejected','Cancel')
                  AND l.state != 'Reject'
                  AND l.location_id IS NOT NULL
                GROUP BY l.location_id, c.company_id, c.approver_id
            )
        """)
