# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_is_zero


class StockInventoryLine(models.Model):
    _name = 'setu.stock.inventory.line'
    _description = 'Setu Stock Inventory Line'

    theoretical_qty = fields.Float(string="Theoretical QTY")
    product_qty = fields.Float(string="Counted QTY")
    difference_qty = fields.Float(string="Difference", compute="_compute_difference",
                                  help="Indicates the gap between the product's theoretical quantity and its newest quantity.",
                                  readonly=True, digits="Product Unit of Measure", search="_search_difference_qty",store=True)

    partner_id = fields.Many2one(comodel_name="res.partner", string="Owner", check_company=True)
    package_id = fields.Many2one(comodel_name="stock.package", string="Package",
                                 index=True, check_company=True, domain="[('location_id', '=', location_id)]")
    product_id = fields.Many2one(comodel_name="product.product", string="Product")
    product_uom_id = fields.Many2one(comodel_name="uom.uom", string="Product Unit of Measure", required=True,
                                     readonly=True)
    inventory_id = fields.Many2one(comodel_name="setu.stock.inventory", string="Inventory")
    quant_id = fields.Many2one(comodel_name="stock.quant", string="Quant")
    location_id = fields.Many2one(comodel_name="stock.location", string="Location")
    prod_lot_id = fields.Many2one(comodel_name="stock.lot", string="Lot/Serial Number",
                                  check_company=True,
                                  domain="[('product_id','=',product_id), ('company_id', '=', company_id)]")

    serial_number_ids = fields.Many2many('stock.lot', 'setu_stock_inventory_line_stock_lot_rel',
                                         'setu_stock_inventory_line_id', 'stock_lot_id', string="Serial Numbers")
    not_found_serial_number_ids = fields.Many2many('stock.lot', 'setu_not_found_line_stock_lot_rel',
                                                   'inventory_line_id', 'lot_id', string="Missing Serial Numbers")
    new_serial_number_ids = fields.Many2many('stock.lot', 'setu_new_serial_stock_lot_rel', 'inventory_line_id',
                                             'lot_id', string="New Serial Numbers")


    company_id = fields.Many2one(comodel_name="res.company",
                                 string="Company", related="inventory_id.company_id", index=True,
                                 readonly=True, store=True)
    discrepancy_value= fields.Float(string='Discrepancy Value',compute='_compute_discrepancy_value',store=True)

    @api.model
    def _prepare_product_uom_vals(self, vals):
        product_id = vals.get('product_id')
        if product_id and not vals.get('product_uom_id'):
            vals['product_uom_id'] = self.env['product.product'].browse(product_id).uom_id.id
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._prepare_product_uom_vals(dict(vals)) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        vals = self._prepare_product_uom_vals(dict(vals))
        return super().write(vals)

    @api.onchange('product_qty')
    def _onchange_product_qty(self):
        for rec in self:
            if rec.product_id and rec.product_id.tracking == 'serial' and rec.product_qty > 1:
                raise ValidationError(_("Serial number product should not have more than 1 quantity."))

    @api.depends('product_qty', 'theoretical_qty')
    def _compute_difference(self):
        for line in self:
            if line.theoretical_qty < 0:
                difference = line.product_qty
            else:
                difference = line.product_qty - line.theoretical_qty
            line.difference_qty = difference

    def _get_virtual_location(self):
        return self.product_id.with_company(self.company_id).property_stock_inventory

    def _generate_moves(self):
        vals_list = []
        sn_vals = []
        vals = {}
        for line in self:
            virtual_location = line._get_virtual_location()
            rounding = line.product_id.uom_id.rounding
            if float_is_zero(line.difference_qty, precision_rounding=rounding):
                continue
            if line.difference_qty > 0:  # found more than expected
                if line.serial_number_ids:
                    for serial_number in line.serial_number_ids:
                        serial_number_vals = line._get_move_values(1, virtual_location.id,
                                                                   line.location_id.id,
                                                                   False, serial_number)
                        sn_vals.append(serial_number_vals)
                else:
                    vals = line._get_move_values(line.difference_qty, virtual_location.id, line.location_id.id, False,
                                                 False)
            else:
                vals = line._get_move_values(abs(line.difference_qty), line.location_id.id, virtual_location.id, True,
                                             False)
            if sn_vals:
                vals_list.extend(sn_vals)
            if vals:
                vals_list.append(vals)
                vals = {}
        return self.env['stock.move'].create(vals_list)

    def _get_move_values(self, qty, location_id, location_dest_id, out, serial_number=False):
        self.ensure_one()
        return {
            'name': _('INV:') + (self.inventory_id.name or ''),
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'product_uom_qty': qty,
            'date': self.inventory_id.date,
            'company_id': self.inventory_id.company_id.id,
            'inventory_adj_id': self.inventory_id.id,
            'state': 'confirmed',
            'restrict_partner_id': self.partner_id.id,
            'location_id': location_id,
            'location_dest_id': location_dest_id,
            'move_line_ids': [(0, 0, {
                'product_id': self.product_id.id,
                'lot_id': self.prod_lot_id.id if self.product_id.tracking == 'lot' and self.prod_lot_id else serial_number.id if self.product_id.tracking == 'serial' and serial_number else False,
                'reserved_uom_qty': 0,  # bypass reservation here
                'product_uom_id': self.product_uom_id.id,
                'qty_done': qty,
                'package_id': out and self.package_id.id or False,
                'result_package_id': (not out) and self.package_id.id or False,
                'location_id': location_id,
                'location_dest_id': location_dest_id,
                'owner_id': self.partner_id.id,
            })]
        }


    @api.depends('difference_qty', 'product_id', 'prod_lot_id', 'not_found_serial_number_ids')
    def _compute_discrepancy_value(self):
        for line in self:
            cost = 0.0
            if line.product_id.tracking == 'lot' and line.prod_lot_id and line.prod_lot_id.purchase_order_ids:
                po_lines = line.prod_lot_id.purchase_order_ids.mapped('order_line').filtered(
                    lambda l: l.product_id == line.product_id)
                total_qty = sum(po_lines.mapped('product_qty'))
                total_value = sum(po_lines.mapped('price_subtotal'))
                if total_qty:
                    cost = total_value / total_qty
            elif line.product_id.tracking == 'serial' and line.not_found_serial_number_ids:
                unit_prices = []
                for serial in line.not_found_serial_number_ids:
                    if serial.purchase_order_ids:
                        po_lines = serial.purchase_order_ids.mapped('order_line').filtered(
                            lambda l: l.product_id == line.product_id)
                        unit_prices += po_lines.mapped('price_unit')
                if unit_prices:
                    cost = sum(unit_prices) / len(unit_prices)
            else:
                cost = line.product_id.standard_price or 0.0
            line.discrepancy_value = line.difference_qty * cost

