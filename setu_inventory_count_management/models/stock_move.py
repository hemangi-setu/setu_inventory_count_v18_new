# -*- coding: utf-8 -*-
from odoo import fields, models, api


class StockMove(models.Model):
    _inherit = 'stock.move'

    inventory_adj_id = fields.Many2one(comodel_name="setu.stock.inventory", string="Inventory Adjustment")
    inventory_count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", string="Inventory Count")

    @api.model_create_multi
    def create(self, vals_list):
        inventory_adj_id = self._context.get('adj_context', False)
        if inventory_adj_id:
            inventory_adj_id = self.env['setu.stock.inventory'].sudo().browse(inventory_adj_id)
            for vals in vals_list:
                vals.update({'inventory_adj_id': inventory_adj_id.id,
                             'inventory_count_id': inventory_adj_id.inventory_count_id.id,
                             'origin': inventory_adj_id.name})
        return super().create(vals_list)
