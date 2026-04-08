# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.addons.setu_inventory_count_management.report.const import (
    get_dynamic_query,
    sql_current_user_approver_filter,
)
from odoo.exceptions import UserError


class SetuInvAdjustmentReport(models.TransientModel):
    _name = 'setu.inventory.adjustment.report'
    _inherit = 'setu.inventory.reporting.template'
    _description = 'Inventory Adjustment Report'

    adjustment_type = fields.Selection([('IN', 'IN'), ('OUT', 'OUT')], string="Adjustment Type")
    count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", string="Count")

    is_overstock = fields.Boolean(string="Overstock", index=True)
    is_understock = fields.Boolean(string="Understock", index=True)
    discrepancy_value = fields.Float(string="Discrepancy Value")
    serial_number_names = fields.Text(string="Serial Numbers")
    not_found_serial_number_names = fields.Text(string="Not Found Serials")

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

        start_date = '1990-01-01'
        end_date = '2100-01-01'

        if self.start_date:
            start_date = str(self.start_date)
        if self.end_date:
            end_date = str(self.end_date)
        self._cr.execute('delete from setu_inventory_adjustment_report;')
        query = f"""
            select 
                count_line.product_id,
                cou.warehouse_id,
                count_line.location_id,
                si.date as adjustment_date,
                max(coalesce(count_line.qty_in_stock,0)) as theoretical_qty,
                max(coalesce(count_line.counted_qty,0)) as counted_qty,
                max(coalesce(count_line.difference_qty,0)) as discrepancy_qty, 
                sum(coalesce(count_line.discrepancy_value,0)) as discrepancy_value,
                cou.approver_id as user_id,
                cou.id as count_id,
                case when coalesce(count_line.qty_in_stock,0) > coalesce(count_line.counted_qty,0) then 'OUT' else 'IN' end as adjustment_type,
                count_line.lot_id as lot_id,
                string_agg(distinct sl.name, ', ') as serial_number_names,
                string_agg(distinct nsl.name, ', ') as not_found_serial_number_names
            from setu_stock_inventory_count_line count_line
            inner join setu_stock_inventory_count cou on cou.id = count_line.inventory_count_id
            inner join setu_stock_inventory si on si.inventory_count_id = cou.id  
            left join setu_stock_inventory_count_line_stock_lot_rel rel on rel.setu_stock_inventory_count_line_id = count_line.id
            left join stock_lot sl on sl.id = rel.stock_lot_id
            left join not_found_stock_lot_rel nfrel on nfrel.count_line_id = count_line.id
            left join stock_lot nsl on nsl.id = nfrel.lot_id
            where cou.state = 'Inventory Adjusted'
            and count_line.is_discrepancy_found = 't'
            and si.date::date >= '{str(start_date)}' and si.date::date <= '{str(end_date)}'
            {where_query}
            group by
                count_line.product_id,
                count_line.lot_id,
                cou.warehouse_id,
                count_line.location_id,
                si.date,
                cou.approver_id,
                cou.id,
                adjustment_type;

        """
        self._cr.execute(query)
        data_list = self._cr.dictfetchall()

        vals_list = []
        for data in data_list:
            vals_list.append({
                'product_id': data['product_id'],
                'warehouse_id': data['warehouse_id'],
                'location_id': data['location_id'],
                'inventory_count_date': data['adjustment_date'],
                'theoretical_qty': data['theoretical_qty'],
                'counted_qty': data['counted_qty'],
                'discrepancy_qty': data['discrepancy_qty'],
                'discrepancy_value': data['discrepancy_value'],
                'user_id': data['user_id'],
                'count_id': data['count_id'],
                'lot_id': data['lot_id'],
                'adjustment_type': data['adjustment_type'],
                'is_overstock': data['counted_qty'] > data['theoretical_qty'],
                'serial_number_names': data['serial_number_names'],
                'not_found_serial_number_names': data['not_found_serial_number_names'],
                'is_understock': data['counted_qty'] < data['theoretical_qty']
            })
        if vals_list:
            self.create(vals_list)
        action = self.sudo().env.ref('setu_inventory_count_management.setu_inventory_adjustment_report_action_view').read()[0]
        return action

    def _compute_stock_status(self):
        for rec in self:
            rec.is_overstock = rec.counted_qty > rec.theoretical_qty
            rec.is_understock = rec.counted_qty < rec.theoretical_qty
