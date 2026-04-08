# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockInventory(models.Model):
    _name = 'setu.stock.inventory'
    _description = 'Setu Stock Inventory'

    name = fields.Char(string="Name")

    date = fields.Date(string="Inventory Date")

    state = fields.Selection(string='Status', selection=[
        ('draft', 'Draft'), ('cancel', 'Cancelled'),
        ('confirm', 'In Progress'), ('done', 'Validated')], copy=False, index=True, readonly=True, default='draft')

    inventory_count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", string="Inventory Count")
    session_id = fields.Many2one(comodel_name="setu.inventory.count.session", string="Session")
    location_id = fields.Many2one(comodel_name="stock.location", required=True, string="Location")
    partner_id = fields.Many2one(comodel_name="res.users",
                                 string="Inventoried Owner", readonly=True,
                                 help="Specify Owner to focus your inventory on a particular Owner.")
    company_id = fields.Many2one(comodel_name="res.company", string="Company",
                                 readonly=True, index=True, required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency", readonly=True)

    line_ids = fields.One2many('setu.stock.inventory.line', 'inventory_id', string='Inventories', copy=True,
                               readonly=False)
    move_ids = fields.One2many('stock.move', 'inventory_adj_id', readonly=True, string="Moves")
    line_count = fields.Integer(compute="_compute_kanban_metrics", string="Line Count")
    difference_line_count = fields.Integer(compute="_compute_kanban_metrics", string="Difference Lines")
    loss_value = fields.Float(compute="_compute_kanban_metrics", string="Loss Value")
    gain_value = fields.Float(compute="_compute_kanban_metrics", string="Gain Value")

    product_ids = fields.Many2many('product.product', string='Products', check_company=True,
                                   domain="[('type', '=', 'product'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
                                   readonly=True,
                                   help="Specify Products to focus your inventory on particular Products.")

    @api.depends('line_ids', 'line_ids.difference_qty', 'line_ids.discrepancy_value')
    def _compute_kanban_metrics(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.difference_line_count = len(rec.line_ids.filtered(lambda l: l.difference_qty != 0))
            if rec.line_ids:
                discrepancy_values = rec.line_ids.mapped('discrepancy_value')
                rec.loss_value = sum(abs(val) for val in discrepancy_values if val < 0)
                rec.gain_value = sum(val for val in discrepancy_values if val > 0)
            else:
                rec.loss_value = 0.0
                rec.gain_value = 0.0

    def action_cancel(self):
        if self.inventory_count_id:
            try:
                self.inventory_count_id.message_post(
                    body=f"""This count is cancelled. Please start new Inventory if you want to adjust it"""
                )
            except Exception as e:
                pass
            self.inventory_count_id = False
        self.state = 'cancel'

    def action_validate(self):
        auto_inventory_adjustment = self.env['ir.config_parameter'].sudo().get_param(
            'setu_inventory_count_management.auto_inventory_adjustment')

        quants_to_create = []
        quants_to_apply = self.env['stock.quant']
        line_to_quant_map = []  # To link quants back to lines after batch creation

        for line in self.line_ids:
            if line.product_id.tracking == 'serial':
                for sr_num in line.serial_number_ids:
                    quant = self.env['stock.quant'].sudo().search(
                        [('location_id', '=', line.location_id.id), ('lot_id', '=', sr_num.id),
                         ('product_id', '=', line.product_id.id),
                         ('quantity', '>', 0)], limit=1)
                    if quant:
                        if line.product_qty == 0:
                            quant.with_context(inventory_mode=True).write({'inventory_quantity': 0})
                            quants_to_apply |= quant
                        line.quant_id = quant
                        continue

                    quant_on_another_location = self.env['stock.quant'].sudo().search(
                        [('lot_id', '=', sr_num.id),
                         ('product_id', '=', line.product_id.id),
                         ('location_id.usage', '=', 'internal'),
                         ('quantity', '>', 0)], limit=1)
                    if quant_on_another_location:
                        quant_on_another_location.with_context(inventory_mode=True).write({'inventory_quantity': 0})
                        if auto_inventory_adjustment:
                            quant_on_another_location.with_context(adj_context=self.id).action_apply_inventory()

                    quants_to_create.append({
                        'product_id': line.product_id.id,
                        'location_id': line.location_id.id,
                        'lot_id': sr_num.id,
                        'inventory_quantity': 1
                    })
                    line_to_quant_map.append(line)

            elif line.product_id.tracking == 'lot':
                quant = self.env['stock.quant'].sudo().search([('lot_id', '=', line.prod_lot_id.id),
                                                               ('location_id', '=', line.location_id.id),
                                                               ('product_id', '=', line.product_id.id)], limit=1)
                if quant:
                    quant.with_context(inventory_mode=True).write({'inventory_quantity': line.product_qty})
                    quants_to_apply |= quant
                    line.quant_id = quant
                else:
                    quants_to_create.append({
                        'product_id': line.product_id.id,
                        'location_id': line.location_id.id,
                        'lot_id': line.prod_lot_id.id,
                        'inventory_quantity': line.product_qty
                    })
                    line_to_quant_map.append(line)
            else:
                quant = self.env['stock.quant'].sudo().search(
                    [('location_id', '=', line.location_id.id), ('product_id', '=', line.product_id.id)], limit=1)
                if quant:
                    quant.with_context(inventory_mode=True).write({'inventory_quantity': line.product_qty})
                    quants_to_apply |= quant
                    line.quant_id = quant
                else:
                    quants_to_create.append({
                        'product_id': line.product_id.id,
                        'location_id': line.location_id.id,
                        'inventory_quantity': line.product_qty
                    })
                    line_to_quant_map.append(line)

        if quants_to_create:
            created_quants = self.env['stock.quant'].with_context(inventory_mode=True).sudo().create(quants_to_create)
            for line, quant in zip(line_to_quant_map, created_quants):
                line.quant_id = quant  # Note: for serial this might overwrite if multiple serials, but original logic did this too
            quants_to_apply |= created_quants

        if auto_inventory_adjustment and quants_to_apply:
            for q in quants_to_apply:
                q.with_context(adj_context=self.id).action_apply_inventory()

        self.state = 'done'
        if self.inventory_count_id:
            self.inventory_count_id.state = 'Inventory Adjusted'

    def action_start(self):
        self.state = 'confirm'

    def action_check(self):
        for inventory in self.filtered(lambda x: x.state not in ('done', 'cancel')):
            inventory.with_context(prefetch_fields=False).mapped('move_ids').unlink()
            inventory.line_ids._generate_moves()
