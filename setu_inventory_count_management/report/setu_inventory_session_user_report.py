# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class SetuInventorySessionUserReport(models.Model):
    _name = 'setu.inventory.session.user.report'
    _description = 'User-wise Inventory Count Report'
    _auto = False

    user_id = fields.Many2one("res.users", string="User")
    approver_id = fields.Many2one("res.users", string="Approver")
    company_id = fields.Many2one("res.company", string="Company")

    total_sessions = fields.Integer(string="Total Sessions")
    scanned_products = fields.Integer(string="Total Scanned Products")
    accurate_products = fields.Integer(string="Accurate Products")
    discrepancy_products = fields.Integer(string="Mistake Products")
    accuracy_ratio = fields.Float(string="Accuracy Ratio (%)")
    discrepancy_ratio = fields.Float(string="Mistake Ratio (%)")
    avg_time_per_session = fields.Float(string="Avg. Time per Session (min)")

    def init(self):
        tools.drop_view_if_exists(self._cr, self._table)
        self._cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH base_rows AS (
                    -- session-level approval: from session lines
                    SELECT
                        lu.res_users_id AS user_id,
                        cou.company_id AS company_id,
                        cou.approver_id AS approver_id,
                        sess.id AS session_id,
                        line.product_scanned AS scanned,
                        (
                            COALESCE(line.user_calculation_mistake, FALSE)
                            OR COALESCE(cl.user_calculation_mistake, FALSE)
                        ) AS is_mistake,
                        COALESCE(details.duration_seconds, 0) AS duration_seconds
                    FROM setu_inventory_count_session_line line
                    INNER JOIN setu_inventory_count_session sess
                        ON sess.id = line.session_id
                    INNER JOIN setu_stock_inventory_count cou
                        ON cou.id = line.inventory_count_id
                    INNER JOIN (
                        SELECT DISTINCT setu_inventory_count_session_line_id, res_users_id
                        FROM res_users_setu_inventory_count_session_line_rel
                    ) lu ON lu.setu_inventory_count_session_line_id = line.id
                    LEFT JOIN setu_stock_inventory_count_line cl
                        ON cl.id = line.inventory_count_line_id
                    LEFT JOIN (
                        SELECT session_id, SUM(duration_seconds) AS duration_seconds
                        FROM setu_inventory_session_details
                        GROUP BY session_id
                    ) details ON details.session_id = sess.id
                    WHERE sess.state IN ('Submitted', 'Done')
                      AND sess.session_id IS NULL
                      AND cou.approval_scope = 'session_level'

                    UNION ALL

                    -- count-level approval: from count lines (approved + rejected attempts)
                    SELECT
                        cu.res_users_id AS user_id,
                        cou.company_id AS company_id,
                        cou.approver_id AS approver_id,
                        NULL::integer AS session_id,
                        TRUE AS scanned,
                        COALESCE(cl.user_calculation_mistake, FALSE) AS is_mistake,
                        0::numeric AS duration_seconds
                    FROM setu_stock_inventory_count_line cl
                    INNER JOIN setu_stock_inventory_count cou
                        ON cou.id = cl.inventory_count_id
                    INNER JOIN (
                        SELECT DISTINCT setu_stock_inventory_count_line_id, res_users_id
                        FROM res_users_setu_stock_inventory_count_line_rel
                    ) cu ON cu.setu_stock_inventory_count_line_id = cl.id
                    WHERE cou.state NOT IN ('Draft', 'In Progress', 'Cancel', 'Rejected')
                      AND cou.approval_scope = 'count_level'
                      AND cl.state IN ('Approve', 'Reject')
                )
                SELECT
                    row_number() OVER () AS id,
                    row_data.user_id,
                    row_data.company_id,
                    MIN(row_data.approver_id) AS approver_id,
                    COUNT(DISTINCT CASE WHEN row_data.scanned THEN row_data.session_id END) AS total_sessions,
                    COUNT(CASE WHEN row_data.scanned THEN 1 END) AS scanned_products,
                    COUNT(CASE WHEN row_data.scanned AND NOT row_data.is_mistake THEN 1 END) AS accurate_products,
                    COUNT(CASE WHEN row_data.scanned AND row_data.is_mistake THEN 1 END) AS discrepancy_products,
                    CASE
                        WHEN COUNT(CASE WHEN row_data.scanned THEN 1 END) > 0
                        THEN (
                            COUNT(CASE WHEN row_data.scanned AND NOT row_data.is_mistake THEN 1 END)::float
                            / NULLIF(COUNT(CASE WHEN row_data.scanned THEN 1 END)::float, 0)
                        ) * 100
                        ELSE 0
                    END AS accuracy_ratio,
                    CASE
                        WHEN COUNT(CASE WHEN row_data.scanned THEN 1 END) > 0
                        THEN (
                            COUNT(CASE WHEN row_data.scanned AND row_data.is_mistake THEN 1 END)::float
                            / NULLIF(COUNT(CASE WHEN row_data.scanned THEN 1 END)::float, 0)
                        ) * 100
                        ELSE 0
                    END AS discrepancy_ratio,
                    CASE
                        WHEN COUNT(DISTINCT CASE WHEN row_data.scanned THEN row_data.session_id END) > 0
                        THEN (
                            SUM(CASE WHEN row_data.scanned THEN row_data.duration_seconds ELSE 0 END) / 60.0
                            / NULLIF(COUNT(DISTINCT CASE WHEN row_data.scanned THEN row_data.session_id END)::float, 0)
                        )
                        ELSE 0
                    END AS avg_time_per_session
                FROM base_rows row_data
                WHERE row_data.user_id NOT IN (
                    SELECT gu.uid
                    FROM res_groups_users_rel gu
                    WHERE gu.gid IN (
                        SELECT imd.res_id
                        FROM ir_model_data imd
                        WHERE imd.model = 'res.groups'
                          AND imd.module = 'setu_inventory_count_management'
                          AND imd.name IN (
                              'group_setu_inventory_count_approver',
                              'group_setu_inventory_count_manager'
                          )
                    )
                )
                GROUP BY
                    row_data.user_id,
                    row_data.company_id
            )
        """)
