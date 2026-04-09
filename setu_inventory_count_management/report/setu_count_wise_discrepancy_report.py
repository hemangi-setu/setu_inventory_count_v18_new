# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools
from odoo.osv import expression


class SetuCountWiseDiscrepancyReport(models.Model):
    _name = "setu.count.wise.discrepancy.report"
    _description = "Count-wise Discrepancy Report"
    _auto = False

    count_id = fields.Many2one("setu.stock.inventory.count", string="Inventory Count", readonly=True)
    approver_id = fields.Many2one("res.users", string="Approver", readonly=True)
    total_count_lines = fields.Integer(string="Total Count Products", readonly=True)
    discrepancy_lines = fields.Integer(string="Discrepancy Products", readonly=True)
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
                    c.id AS id,
                    c.id AS count_id,
                    COUNT(l.id) AS total_count_lines,
                    SUM(CASE WHEN l.is_discrepancy_found = TRUE THEN 1 ELSE 0 END) AS discrepancy_lines,
                    ROUND(
                        (SUM(CASE WHEN l.is_discrepancy_found = TRUE THEN 1 ELSE 0 END)::decimal /
                         NULLIF(COUNT(l.id),0)) * 100, 2
                    ) AS discrepancy_percent,
                    c.company_id AS company_id,
                    c.approver_id AS approver_id
                FROM setu_stock_inventory_count c
                JOIN setu_stock_inventory_count_line l ON l.inventory_count_id = c.id
                WHERE c.state NOT IN ('Rejected','Cancel')
                  AND l.state != 'Reject'
                GROUP BY c.id, c.company_id, c.approver_id
            )
        """)
