# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools
from odoo.osv import expression

# session performance report
class SetuInventorySessionPerformanceReport(models.Model):
    _name = 'setu.inventory.session.performance.report'
    _description = 'Session Performance Report'
    _auto = False

    count_id = fields.Many2one("setu.stock.inventory.count", string="Count")
    session_id = fields.Many2one("setu.inventory.count.session", string="Session")

    session_start = fields.Datetime("Session Start")
    session_end = fields.Datetime("Session End")
    duration = fields.Float("Duration (hrs)")

    total_products_assigned = fields.Integer("Total Products Assigned")
    total_products_counted = fields.Integer("Total Products Counted")
    users_involved = fields.Integer("Users Involved")

    avg_time_per_product = fields.Float("Avg Time Per Product (hrs)")
    accuracy_ratio = fields.Float("Accuracy Ratio (%)")
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
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    sess.id as id,
                    sess.inventory_count_id as count_id,
                    sess.id as session_id,
                    sess.session_start_date as session_start,
                    sess.session_submit_date as session_end,

                    COALESCE(SUM(details.duration_seconds),0)/3600.0 as duration,
                    sess.total_products as total_products_assigned,
                    sess.total_scanned_products as total_products_counted,
                    COALESCE(COUNT(DISTINCT user_rel.user_id),0) as users_involved,
                    sess.approver_id AS approver_id,
                    sess.company_id AS company_id,
                    CASE 
                        WHEN sess.total_scanned_products > 0 
                        THEN (COALESCE(SUM(details.duration_seconds),0)/3600.0) / NULLIF(sess.total_scanned_products,0)
                        ELSE 0 
                    END as avg_time_per_product,
                    CASE 
                        WHEN sess.total_products > 0 
                        THEN (COUNT(CASE WHEN line.difference_qty = 0 THEN 1 END)::float / 
                              NULLIF(COUNT(line.id),0)) * 100
                        ELSE 0 END as accuracy_ratio

                FROM setu_inventory_count_session sess
                LEFT JOIN setu_inventory_session_details details 
                    ON details.session_id = sess.id
                LEFT JOIN setu_inventory_count_session_line line 
                    ON line.session_id = sess.id
                LEFT JOIN setu_inventory_count_session_user_rel user_rel
                    ON user_rel.session_id = sess.id

                WHERE sess.state IN ('Submitted','Done')

                GROUP BY sess.id, sess.company_id, sess.approver_id
            )
        """)
