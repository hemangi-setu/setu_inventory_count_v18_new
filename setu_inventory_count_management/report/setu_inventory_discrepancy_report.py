from odoo import api, fields, models
from odoo import tools
from odoo.osv import expression


class SetuInventoryDiscrepancyReport(models.Model):
    _name = "setu.inventory.discrepancy.report"
    _description = "Inventory Count discrepancy Report"
    _auto = False

    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    discrepancy_percentage = fields.Float(string="Discrepancy %", readonly=True)

    date = fields.Date("Count Date", readonly=True)
    location_id = fields.Many2one("stock.location", string="Location", readonly=True)
    approver_id = fields.Many2one("res.users", string="Approver", readonly=True)
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
                    MIN(count_line.id) as id,
                    count_line.product_id,
                    CASE 
                        WHEN SUM(count_line.theoretical_qty) = 0 THEN 0
                        ELSE (SUM(ABS(count_line.counted_qty - count_line.theoretical_qty))::float 
                              / NULLIF(SUM(count_line.theoretical_qty),0)) * 100
                    END AS discrepancy_percentage,
                    cou.inventory_count_date::date as date,
                    count_line.location_id,
                    cou.approver_id,
                    cou.company_id
                FROM setu_stock_inventory_count_line count_line
                INNER JOIN setu_stock_inventory_count cou
                    ON cou.id = count_line.inventory_count_id
                WHERE cou.state IN ('Inventory Adjusted','Approved')
                GROUP BY count_line.product_id, cou.inventory_count_date, count_line.location_id, cou.approver_id, cou.company_id
            )
        """)
