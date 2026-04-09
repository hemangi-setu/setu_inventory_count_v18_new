# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class StockInvCountLine(models.Model):
    _name = 'setu.stock.inventory.count.line'
    _description = 'Stock Inventory Count Line'

    is_discrepancy_found = fields.Boolean(compute="_compute_is_discrepancy_found", store=True, depends=['counted_qty'],
                                          string="Is Discrepancy Found")
    user_calculation_mistake = fields.Boolean(
        default=False,
        store=True,
        readonly=False,
        tracking=True,
        string="User Calculation Mistake",
    )
    is_multi_session = fields.Boolean(default=False, string="Is Multi session")
    is_system_generated = fields.Boolean(string="System Generated Line")

    theoretical_qty = fields.Float(string="Theoretical Qty")
    qty_in_stock = fields.Float(string="Quantity In Stock")
    counted_qty = fields.Float(string="Counted Quantity")

    state = fields.Selection([('Pending Review', 'Pending Review'), ('Approve', 'Approve'), ('Reject', 'Reject')],
                             default="Pending Review", string="State")

    unscanned_product_line_id = fields.Many2one('setu.unscanned.product.lines', string="Unscanned Product Line")
    inventory_count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", string="Inventory Count")
    product_id = fields.Many2one(comodel_name="product.product", string="Product")
    location_id = fields.Many2one(comodel_name="stock.location", string="Location")
    lot_id = fields.Many2one(comodel_name="stock.lot", string="Lot")

    session_line_ids = fields.One2many('setu.inventory.count.session.line', 'inventory_count_line_id',
                                       string="Session Lines")

    new_count_lot_ids = fields.Many2many('stock.lot', 'new_count_stock_rel', string='New Count Serial Numbers')
    serial_number_ids = fields.Many2many('stock.lot', 'setu_stock_inventory_count_line_stock_lot_rel',
                                         'setu_stock_inventory_count_line_id', 'stock_lot_id', string='Serial Numbers')
    not_found_serial_number_ids = fields.Many2many('stock.lot', 'not_found_stock_lot_rel', 'count_line_id', 'lot_id',
                                                   string='Serial Numbers Not Founded')

    tracking = fields.Selection(related="product_id.tracking", string="Tracking")
    user_ids = fields.Many2many('res.users', string='Users')
    difference_qty = fields.Float(string="Difference", compute="_compute_difference",
                                  help="Indicates the gap between the product's theoretical quantity and its newest quantity.",
                                  readonly=True, digits="Product Unit of Measure", search="_search_difference_qty",
                                  store=True)
    discrepancy_value = fields.Float(string='Discrepancy Value', compute='_compute_discrepancy_value', store=True)

    def change_line_state_to_approve(self):
        for line in self:
            if (
                line.product_id
                and line.product_id.tracking == 'serial'
                and line.serial_number_ids
                and line.location_id
                and line.inventory_count_id
            ):
                # A serial (lot) cannot be approved in multiple locations for the same count.
                approved_conflicts = self.env['setu.stock.inventory.count.line'].search([
                    ('inventory_count_id', '=', line.inventory_count_id.id),
                    ('product_id', '=', line.product_id.id),
                    ('state', '=', 'Approve'),
                    ('location_id', '!=', line.location_id.id),
                    ('serial_number_ids', 'in', line.serial_number_ids.ids),
                    ('id', '!=', line.id),
                ])
                if approved_conflicts:
                    serial_names = set()
                    conflict_locations = set()
                    for other in approved_conflicts:
                        intersection = other.serial_number_ids & line.serial_number_ids
                        if intersection:
                            serial_names.update(intersection.mapped('name'))
                            if other.location_id:
                                conflict_locations.add(other.location_id.display_name)
                    raise ValidationError(_(
                        'Serial(s) "%(serials)s" are already approved in a different location (%(locations)s) for this count. '
                        'You can approve only one location per serial. Please reject the other line(s) first.'
                    ) % {
                        'serials': ", ".join(sorted(serial_names)) if serial_names else "",
                        'locations': ", ".join(sorted(conflict_locations)) if conflict_locations else "",
                    })

            line.state = 'Approve'
        return False

    def change_line_state_to_reject(self):
        self.write({'state': 'Reject'})
        return False

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._auto_mark_previous_rejected_count_mistakes()
        return lines

    def write(self, vals):
        result = super().write(vals)
        trigger_fields = {'counted_qty', 'product_id', 'location_id', 'lot_id', 'serial_number_ids', 'inventory_count_id'}
        if trigger_fields.intersection(vals.keys()):
            self._auto_mark_previous_rejected_count_mistakes()
        return result

    def _auto_mark_previous_rejected_count_mistakes(self):
        valid_lines = self.filtered(lambda rec: rec.inventory_count_id and rec.product_id)
        for line in valid_lines:
            count = line.inventory_count_id
            if count.approval_scope != 'count_level' or not count.count_id:
                continue

            parent_count = count.count_id
            domain = [
                ('state', '=', 'Reject'),
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', line.location_id.id),
                ('inventory_count_id', '=', parent_count.id),
            ]

            tracking = line.product_id.tracking
            if tracking == 'lot':
                domain.append(('lot_id', '=', line.lot_id.id))

            previous_lines = self.env['setu.stock.inventory.count.line'].search(domain)
            if tracking == 'serial':
                previous_lines = previous_lines.filtered(
                    lambda prev: prev.serial_number_ids & line.serial_number_ids
                )

            for prev_line in previous_lines:
                if prev_line.counted_qty != line.counted_qty:
                    prev_line.with_context(auto_user_mistake_update=True).write({
                        'user_calculation_mistake': True,
                    })

    @api.constrains('state', 'serial_number_ids', 'product_id', 'location_id', 'inventory_count_id')
    def _check_serial_approval_uniqueness_one_location(self):
        """Enforce: for serial-tracked products, the same serial cannot be approved in multiple locations
        within the same inventory count."""
        for line in self:
            if not line.inventory_count_id or line.state != 'Approve':
                continue
            if line.tracking != 'serial' or not line.serial_number_ids or not line.location_id:
                continue

            conflicts = self.search([
                ('id', '!=', line.id),
                ('inventory_count_id', '=', line.inventory_count_id.id),
                ('product_id', '=', line.product_id.id),
                ('location_id', '!=', line.location_id.id),
                ('state', '=', 'Approve'),
                ('serial_number_ids', 'in', line.serial_number_ids.ids),
            ])

            if conflicts:
                serial_names = set()
                conflict_locations = set()
                for other in conflicts:
                    intersection = other.serial_number_ids & line.serial_number_ids
                    if intersection:
                        serial_names.update(intersection.mapped('name'))
                        if other.location_id:
                            conflict_locations.add(other.location_id.display_name)

                raise ValidationError(_(
                    'Serial(s) "%(serials)s" are already approved in another location (%(locations)s) for this count. '
                    'Only one location can be approved per serial.'
                ) % {
                    'serials': ", ".join(sorted(serial_names)) if serial_names else "",
                    'locations': ", ".join(sorted(conflict_locations)) if conflict_locations else "",
                })

    @api.depends('counted_qty', 'qty_in_stock', 'serial_number_ids', 'product_id.tracking')
    def _compute_is_discrepancy_found(self):
        for line in self:
            is_discrepancy = False
            if line.product_id.tracking == 'serial':
                # Simplified check: if counted qty doesn't match theoretical or serial IDs differ
                # We use sudo for quant search only if needed, or rely on qty_in_stock
                if line.counted_qty != line.qty_in_stock:
                    is_discrepancy = True
                else:
                    # Deep check for serial mismatches
                    quants = self.env['stock.quant'].sudo().search([
                        ('location_id', '=', line.location_id.id),
                        ('product_id', '=', line.product_id.id),
                        ('quantity', '=', 1)
                    ])
                    if set(quants.lot_id.ids) != set(line.serial_number_ids.ids):
                        is_discrepancy = True
            elif line.counted_qty != line.qty_in_stock:
                is_discrepancy = True

            line.is_discrepancy_found = is_discrepancy

    @api.depends('session_line_ids.user_calculation_mistake')
    def _compute_user_calculation_mistake(self):
        for line in self:
            line.user_calculation_mistake = any(
                session_line.user_calculation_mistake
                for session_line in line.session_line_ids
            )

    @api.depends('counted_qty', 'theoretical_qty')
    def _compute_difference(self):
        for line in self:
            if line.theoretical_qty < 0:
                difference = line.counted_qty
            else:
                difference = line.counted_qty - line.theoretical_qty
            line.difference_qty = difference

    @api.depends('difference_qty', 'product_id', 'lot_id', 'not_found_serial_number_ids')
    def _compute_discrepancy_value(self):
        for line in self:
            cost = line.product_id.standard_price or 0.0
            if line.product_id.tracking == 'lot' and line.lot_id and line.lot_id.purchase_order_ids:
                po_lines = line.lot_id.purchase_order_ids.mapped('order_line').filtered(
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
            line.discrepancy_value = line.difference_qty * cost

    def _has_serial_number(self, serial_id):
        self.ensure_one()
        return serial_id in self.serial_number_ids.ids or \
            serial_id in self.not_found_serial_number_ids.ids or \
            serial_id in self.new_count_lot_ids.ids
