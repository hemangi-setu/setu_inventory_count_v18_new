# -*- coding: utf-8 -*-
from odoo import fields, models


class SetuUnscannedProductLines(models.Model):
    _name = 'setu.unscanned.product.lines'
    _description = 'Setu Unscanned Product Lines'

    quantity = fields.Float(string="Quantity")

    action = fields.Selection([
        ('make_it_0', 'Make It Zero'),
        ('do_nothing', 'Do Nothing'),
        ('remove_action', 'Remove Action'),
    ], copy=False, tracking=True)

    location_id = fields.Many2one('stock.location', string="Location")
    inventory_count_id = fields.Many2one('setu.stock.inventory.count', string="Inventory Count")
    session_id = fields.Many2one('setu.inventory.count.session', string="Session")
    inventory_count_line_id = fields.Many2one('setu.stock.inventory.count.line', string="Inventory Count Lines")
    session_line_id = fields.Many2one('setu.inventory.count.session.line', string="Session Line")
    product_id = fields.Many2one('product.product', string="Product")
    lot_id = fields.Many2one('stock.lot', string="Lot/Serial Number")
