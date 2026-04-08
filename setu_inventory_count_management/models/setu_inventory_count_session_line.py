# -*- coding: utf-8 -*-
from email.policy import default

from odoo import fields, models, api, _, Command
from odoo.exceptions import UserError, ValidationError


class InventoryCountSessionLine(models.Model):
    _name = 'setu.inventory.count.session.line'
    _description = 'Inventory Count Session Line'

    user_calculation_mistake = fields.Boolean(
        copy=False,
        default=False,
        store=True,
        readonly=False,
        tracking=True,
        string="User calculation mistake",
    )
    product_scanned = fields.Boolean(copy=False, default=False, string="Product scanned")
    is_system_generated = fields.Boolean(string="System Generated Line")
    is_multi_session = fields.Boolean(default=False, string="Is multi session")
    is_discrepancy_found = fields.Boolean(compute="_compute_is_discrepancy_found", store=True,
                                          string="Discrepancy Found")

    scanned_qty = fields.Float(copy=False, string="Scanned quantity")
    to_be_scanned = fields.Float(string="To be quantity")
    theoretical_qty = fields.Float(string="Theoretical quantity", compute='_compute_theoretical_qty', store=True)

    date_of_scanning = fields.Datetime(string="Date of scanning", default=fields.Datetime.now)

    state = fields.Selection([('Pending Review', 'Pending Review'), ('Approve', 'Approve'), ('Reject', 'Reject')],
                             default="Pending Review", string="State")

    inventory_count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", string="Inventory count")
    product_id = fields.Many2one(comodel_name="product.product", string="Product", ondelete='cascade')
    session_id = fields.Many2one(comodel_name="setu.inventory.count.session", string="Session")
    inventory_count_line_id = fields.Many2one(comodel_name="setu.stock.inventory.count.line",
                                              string="Inventory count line")
    location_id = fields.Many2one(comodel_name="stock.location", string="Location")
    lot_id = fields.Many2one(comodel_name="stock.lot", string="Lot")
    unscanned_product_line_id = fields.Many2one('setu.unscanned.product.lines', string="Unscanned Product Line")

    serial_number_ids = fields.Many2many(comodel_name="stock.lot", string="Serial Numbers")
    not_found_serial_number_ids = fields.Many2many('stock.lot', 'session_not_found_stock_lot_rel', 'session_line_id',
                                                   'lot_id', string="Serial Numbers Not Founded")

    tracking = fields.Selection(related="product_id.tracking", string="Tracking")
    user_ids = fields.Many2many('res.users', string='Users', copy=False)
    difference_qty = fields.Float(string="Difference", compute="_compute_difference",
                                  help="Indicates the gap between the product's theoretical quantity and its newest quantity.",
                                  readonly=True, digits="Product Unit of Measure", search="_search_difference_qty",
                                  store=True)
    discrepancy_value = fields.Float(string='Discrepancy Value', compute='_compute_discrepancy_value', store=True)

    def _enforce_session_product_limit(self, sessions):
        for session in sessions.filtered(lambda s: s and s.inventory_count_id):
            count = session.inventory_count_id
            if not count.use_max_products or count.max_products_per_session <= 0:
                continue
            product_ids = self.search([
                ('session_id', '=', session.id),
                ('product_id', '!=', False),
            ]).mapped('product_id').ids
            if len(set(product_ids)) > count.max_products_per_session:
                raise ValidationError(_(
                    "Maximum {} products are allowed per session."
                ).format(count.max_products_per_session))

    @api.model_create_multi
    def create(self, vals_list):
        # Pre-fetch session and inventory counts to avoid N+1 queries
        session_ids = [vals['session_id'] for vals in vals_list if vals.get('session_id')]
        sessions = self.env['setu.inventory.count.session'].browse(session_ids)
        session_count_map = {s.id: s.inventory_count_id.id for s in sessions if s.inventory_count_id}

        for vals in vals_list:
            if vals.get('session_id') in session_count_map:
                vals['inventory_count_id'] = session_count_map[vals['session_id']]
            if vals.get('scanned_qty', 0) > 0:
                # Safely append user to Many2many using Command
                vals['user_ids'] = [Command.link(self.env.user.id)]

        lines = super(InventoryCountSessionLine, self).create(vals_list)
        lines._enforce_session_product_limit(lines.mapped('session_id'))
        lines._auto_mark_previous_rejected_mistakes()
        return lines

    @api.constrains('scanned_qty')
    def constrains_scanned_aty(self):
        for line in self:
            if line.scanned_qty < 0:
                raise UserError(_('Counted QTY cannot be less than zero.'))

    @api.constrains('session_id', 'product_id')
    def _check_max_products_per_session_limit(self):
        self._enforce_session_product_limit(self.mapped('session_id'))

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
                approved_conflicts = self.env['setu.inventory.count.session.line'].search([
                    ('inventory_count_id', '=', line.inventory_count_id.id),
                    ('product_id', '=', line.product_id.id),
                    ('state', '=', 'Approve'),
                    ('location_id', '!=', line.location_id.id),
                    ('serial_number_ids', 'in', line.serial_number_ids.ids),
                    ('session_id.state', '!=', 'Cancel'),
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

    def change_line_state_to_reject(self):
        self.state = 'Reject'

    def set_theoretical(self):
        for line in self:
            if line.tracking == 'lot':
                line.scanned_qty = line.theoretical_qty
            elif line.tracking == 'serial':
                new_serials = line.serial_number_ids + line.not_found_serial_number_ids
                line.write({
                    'serial_number_ids': [Command.set(new_serials.ids)],
                    'not_found_serial_number_ids': [Command.clear()],
                    'scanned_qty': len(new_serials)
                })

    def set_mark_scanned(self):
        self.product_scanned = True

    def set_mark_unscanned(self):
        self.product_scanned = False

    @api.depends('lot_id', 'product_id', 'serial_number_ids', 'location_id')
    def _compute_theoretical_qty(self):
        for line in self:
            domain = [('location_id', '=', line.location_id.id),
                      ('product_id', '=', line.product_id.id)]
            if line.product_id and line.location_id:
                if line.lot_id:
                    domain.append(('lot_id', '=', line.lot_id.id))
                quants = self.env['stock.quant'].sudo().search(domain)
                theoretical_qty = sum(x.quantity for x in quants)
                line.theoretical_qty = theoretical_qty
            else:
                line.theoretical_qty = 0

    @api.onchange('product_id', 'lot_id', 'location_id', 'serial_number_ids')
    def _onchange_product_id(self):
        if self.location_id:
            allowed_location = self.session_id._get_allowed_locations_for_session()
            if self.location_id.id not in allowed_location.ids:
                if self.session_id.inventory_count_id.session_strategy == 'location_wise':
                    raise UserError(_(
                        '{} is not assigned to this session. Please select only assigned locations.'.format(
                            self.location_id.display_name)))
                raise UserError(_(
                    '{} is not an internal location of this company. Please select an internal location.'.format(
                        self.location_id.display_name)))
        self.scanned_qty = len(self.serial_number_ids)
        if not self.session_id or self.session_id.session_id or self.session_id.inventory_count_id.count_id:
            return
        base_domain = [
            ('inventory_count_id', '=', self.session_id.inventory_count_id.id),
            ('state', '!=', 'Cancel'),
            ('product_id', '=', self.product_id.id),
        ]
        if self._origin.id:
            base_domain.append(('id', '!=', self._origin.id))

        LineObj = self.env['setu.inventory.count.session.line']

        if self.product_id.tracking == 'lot' and self.product_id and self.location_id and self.lot_id:
            domain = base_domain + [('session_id', '=', self.session_id._origin.id),
                                    ('location_id', '=', self.location_id.id), ('lot_id', '=', self.lot_id.id)]
            if LineObj.search_count(domain):
                raise UserError(
                    _('Lot "{}" is already scanned for the same location in the same session for this Count.').format(
                        self.lot_id.name))

        elif self.product_id.tracking == 'none' and self.product_id and self.location_id:
            domain = base_domain + [('session_id', '=', self.session_id._origin.id),
                                    ('location_id', '=', self.location_id.id)]
            if LineObj.search_count(domain):
                raise UserError(
                    _('Product "{}" is already scanned for the same location in the same session for this Count.').format(
                        self.product_id.display_name))

        elif self.product_id.tracking == 'serial' and self.location_id and self.serial_number_ids:
            domain = base_domain + [('serial_number_ids', 'in', self.serial_number_ids.ids)]
            duplicate_lines = LineObj.search(domain)
            if duplicate_lines:
                # Find the intersection of serials scanned here and serials already existing
                duplicate_lots = duplicate_lines.mapped('serial_number_ids') & self.serial_number_ids
                if duplicate_lots:
                    names = ", ".join(duplicate_lots.mapped('name'))
                    raise UserError(
                        _('Serial Number "{}" is already scanned by another user in another session for this Count.').format(
                            names))

    def _get_theoretical_qty(self, count_line_exists_already=False, location=False):
        for line in self:
            if line.product_id and line.location_id:
                domain = [('location_id', '=', location.id if location else line.location_id.id),
                          ('product_id', '=', line.product_id.id),
                          ]
                if line.product_id.tracking == 'lot':
                    domain.append(('lot_id', '=', line.lot_id.id))

                elif line.product_id.tracking == 'serial':
                    domain.append(('quantity', '>', 0))

                quants = self.env['stock.quant'].sudo().search(domain)

                theoretical_qty = sum(x.quantity for x in quants)

                return theoretical_qty

            else:
                return 0

    def _get_counted_qty(self, line, count_line_exists_already=False):
        if line.product_id.tracking == 'serial':
            sessions = line.session_id.inventory_count_id.session_ids
            serial_type_session_lines = sessions.session_line_ids.filtered(
                lambda l: l.product_id.id == line.product_id.id and l.location_id.id == line.location_id.id)
            serial_numbers = serial_type_session_lines.mapped('serial_number_ids').filtered(lambda s: s.product_qty < 1)
            final_serial_numbers = serial_type_session_lines.mapped('serial_number_ids') - serial_numbers
            return len(final_serial_numbers)
        elif line.product_id.tracking == 'none':
            existing_qty = count_line_exists_already.counted_qty if count_line_exists_already else 0.0
            if line.session_id.session_id:
                qty = line.scanned_qty
            else:
                qty = existing_qty + line.scanned_qty

            moves = self.env['stock.move.line'].sudo().search([('state', '=', 'done'),
                                                               ('product_id', '=', line.product_id.id),
                                                               ('move_id.picking_type_id.code', '=', 'outgoing'),
                                                               ('date', '>=', line.date_of_scanning)])
            qty -= sum(x.qty_done for x in moves)
            return qty
        elif line.product_id.tracking == 'lot':
            existing_qty = count_line_exists_already.counted_qty if count_line_exists_already else 0.0
            if line.session_id.session_id:
                qty = line.scanned_qty
            else:
                qty = existing_qty + line.scanned_qty

            moves = self.env['stock.move.line'].sudo().search([('state', '=', 'done'),
                                                               ('product_id', '=', line.product_id.id),
                                                               ('move_id.picking_type_id.code', '=', 'outgoing'),
                                                               ('lot_id', '=', line.lot_id.id),
                                                               ('date', '>=', line.date_of_scanning)])
            qty -= sum(x.qty_done for x in moves)
            return qty

    def _get_serial_number_ids(self, line):
        sessions = line.session_id.inventory_count_id.session_ids
        serial_type_session_lines = sessions.session_line_ids.filtered(
            lambda l: l.product_id.id == line.product_id.id and l.location_id.id == line.location_id.id)
        serial_numbers = serial_type_session_lines.mapped('serial_number_ids').filtered(lambda s: s.product_qty < 1)
        final_serial_numbers = serial_type_session_lines.mapped('serial_number_ids') - serial_numbers
        return [(6, 0, final_serial_numbers.ids)]

    def write(self, vals):
        if vals.get('scanned_qty', 0) > 0:
            vals['user_ids'] = [Command.link(self.env.user.id)]

        result = super(InventoryCountSessionLine, self).write(vals)
        if 'product_id' in vals or 'session_id' in vals:
            self._enforce_session_product_limit(self.mapped('session_id'))
        trigger_fields = {'scanned_qty', 'product_id', 'location_id', 'lot_id', 'serial_number_ids', 'session_id'}
        if trigger_fields.intersection(vals.keys()):
            self._auto_mark_previous_rejected_mistakes()
        return result

    def _auto_mark_previous_rejected_mistakes(self):
        for line in self.filtered(lambda rec: rec.session_id and rec.inventory_count_id):
            count = line.inventory_count_id
            if count.approval_scope != 'session_level':
                continue
            parent_session = line.session_id.revision_of_id
            if not parent_session:
                continue
            prev_lines = parent_session.session_line_ids.filtered(
                lambda prev: (
                    prev.state == 'Reject'
                    and prev.product_id == line.product_id
                    and prev.location_id == line.location_id
                    and (
                        line.product_id.tracking == 'none'
                        or (line.product_id.tracking == 'lot' and prev.lot_id == line.lot_id)
                        or (
                            line.product_id.tracking == 'serial'
                            and bool(prev.serial_number_ids & line.serial_number_ids)
                        )
                    )
                )
            )
            for prev_line in prev_lines:
                if prev_line.scanned_qty != line.scanned_qty:
                    prev_line.with_context(auto_user_mistake_update=True).write({
                        'user_calculation_mistake': True,
                    })

    @api.depends('scanned_qty', 'theoretical_qty')
    def _compute_difference(self):
        for line in self:
            if line.theoretical_qty < 0:
                difference = line.scanned_qty
            else:
                difference = line.scanned_qty - line.theoretical_qty
            line.difference_qty = difference

    @api.depends('scanned_qty', 'theoretical_qty')
    def _compute_is_discrepancy_found(self):
        for line in self:
            if line.theoretical_qty < 0:
                line.is_discrepancy_found = False
            else:
                difference = abs(line.scanned_qty - line.theoretical_qty)
                line.is_discrepancy_found = difference > 0

    @api.depends('difference_qty', 'product_id', 'lot_id')
    def _compute_discrepancy_value(self):
        for line in self:
            cost = line.product_id.standard_price or 0.0
            if line.lot_id and line.lot_id.purchase_order_ids:
                po_lines = line.lot_id.purchase_order_ids.mapped('order_line').filtered(
                    lambda l: l.product_id == line.product_id)
                total_qty = sum(po_lines.mapped('product_qty'))
                total_value = sum(po_lines.mapped('price_subtotal'))
                if total_qty:
                    cost = total_value / total_qty
            line.discrepancy_value = line.difference_qty * cost
