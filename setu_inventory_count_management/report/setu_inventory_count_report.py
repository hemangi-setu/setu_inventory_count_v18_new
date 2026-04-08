# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.addons.setu_inventory_count_management.report.const import (
    get_dynamic_query,
    sql_current_user_approver_filter,
)
from odoo.exceptions import UserError

# Inventory loss report [Count report is renamed as Inventory loss report]
class SetuInvCountReport(models.TransientModel):
    _name = 'setu.inventory.count.report'
    _inherit = 'setu.inventory.reporting.template'
    _description = 'Inventory Count Report'

    count_id = fields.Many2one(
        comodel_name="setu.stock.inventory.count",
        string="Count"
    )
    discrepancy_ratio = fields.Float("Discrepancy Ratio (%)", digits=(16, 2))
    discrepancy_value = fields.Float(string="Discrepancy Value")
    use_barcode_scanner = fields.Char(string="Scanned/Manual")
    serial_number_ids = fields.Text(string="Serial Numbers")
    not_found_serial_number_ids = fields.Text(string="Not Found Serials")

    def generate_report(self):
        location_ids = False
        warehouse_ids = False
        user_ids = False

        if self.location_ids:
            location_ids = 'ARRAY' + str(self.location_ids.ids)
        if self.warehouse_ids:
            warehouse_ids = 'ARRAY' + str(self.warehouse_ids.ids)
        if self.user_ids:
            user_ids = 'ARRAY' + str(self.user_ids.ids)

        where_query = get_dynamic_query(
            'count_line.location_id', location_ids,
            'cou.approver_id', user_ids,
            'cou.warehouse_id', warehouse_ids
        )
        where_query += sql_current_user_approver_filter(self.env, column='cou.approver_id')

        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise UserError("Please enter a valid start date and end date.")

        start_date = str(self.start_date or '1990-01-01')
        end_date = str(self.end_date or '2100-01-01')

        self._cr.execute('DELETE FROM setu_inventory_count_report;')

        query = f"""
            SELECT
                count_line.product_id,
                cou.warehouse_id,
                count_line.location_id,
                cou.inventory_count_date,

                SUM(COALESCE(count_line.qty_in_stock, 0)) AS theoretical_qty,
                SUM(COALESCE(count_line.counted_qty, 0)) AS counted_qty,
                SUM(COALESCE(count_line.difference_qty, 0)) AS discrepancy_qty,
                SUM(COALESCE(count_line.discrepancy_value, 0)) AS discrepancy_value,

                cou.approver_id AS user_id,
                cou.id AS count_id,

                CASE
                    WHEN cou.use_barcode_scanner THEN 'Scanned'
                    ELSE 'Manual'
                END AS use_barcode_scanner,

                count_line.lot_id,

                sl_data.serial_number_ids,
                nfsl_data.not_found_serial_number_ids,

                ROUND(
                    CASE
                        WHEN SUM(COALESCE(count_line.qty_in_stock, 0)) = 0
                             AND SUM(COALESCE(count_line.counted_qty, 0)) > 0
                        THEN 100
                        WHEN SUM(COALESCE(count_line.qty_in_stock, 0)) = 0
                        THEN 0
                        ELSE
                            ABS(
                                SUM(COALESCE(count_line.qty_in_stock, 0)) -
                                SUM(COALESCE(count_line.counted_qty, 0))
                            ) / NULLIF(SUM(COALESCE(count_line.qty_in_stock, 0)), 0) * 100
                    END::numeric,
                    2
                ) AS discrepancy_ratio

            FROM setu_stock_inventory_count_line count_line
            JOIN setu_stock_inventory_count cou
                ON cou.id = count_line.inventory_count_id

            -- ✅ Found serial numbers (pre-aggregated)
            LEFT JOIN (
                SELECT
                    rel.setu_stock_inventory_count_line_id AS line_id,
                    STRING_AGG(DISTINCT sl.name, ', ') AS serial_number_ids
                FROM setu_stock_inventory_count_line_stock_lot_rel rel
                JOIN stock_lot sl ON sl.id = rel.stock_lot_id
                GROUP BY rel.setu_stock_inventory_count_line_id
            ) sl_data ON sl_data.line_id = count_line.id

            -- ✅ Not found serial numbers (pre-aggregated)
            LEFT JOIN (
                SELECT
                    nfrel.count_line_id AS line_id,
                    STRING_AGG(DISTINCT nsl.name, ', ') AS not_found_serial_number_ids
                FROM not_found_stock_lot_rel nfrel
                JOIN stock_lot nsl ON nsl.id = nfrel.lot_id
                GROUP BY nfrel.count_line_id
            ) nfsl_data ON nfsl_data.line_id = count_line.id

            WHERE cou.state IN ('Inventory Adjusted', 'Approved')
              AND count_line.is_discrepancy_found = TRUE
              AND count_line.state != 'Reject'
              AND COALESCE(count_line.difference_qty, 0) < 0
              AND cou.inventory_count_date::date >= '{start_date}'
              AND cou.inventory_count_date::date <= '{end_date}'
              {where_query}

            GROUP BY
                count_line.product_id,
                cou.warehouse_id,
                count_line.location_id,
                cou.inventory_count_date,
                cou.approver_id,
                cou.id,
                cou.use_barcode_scanner,
                count_line.lot_id,
                sl_data.serial_number_ids,
                nfsl_data.not_found_serial_number_ids
            ORDER BY
                cou.id DESC;
        """

        self._cr.execute(query)
        data_list = self._cr.dictfetchall()

        for data in data_list:
            self.create({
                'product_id': data['product_id'],
                'warehouse_id': data['warehouse_id'],
                'location_id': data['location_id'],
                'inventory_count_date': data['inventory_count_date'],
                'theoretical_qty': data['theoretical_qty'],
                'counted_qty': data['counted_qty'],
                'discrepancy_qty': data['discrepancy_qty'],
                'discrepancy_value': data['discrepancy_value'],
                'user_id': data['user_id'],
                'count_id': data['count_id'],
                'serial_number_ids': data['serial_number_ids'],
                'not_found_serial_number_ids': data['not_found_serial_number_ids'],
                'use_barcode_scanner': data['use_barcode_scanner'],
                'lot_id': data['lot_id'],  # always exists
                'discrepancy_ratio': data['discrepancy_ratio'],
            })

        action = self.sudo().env.ref(
            'setu_inventory_count_management.setu_inventory_count_report_record_action'
        ).read()[0]

        return action
