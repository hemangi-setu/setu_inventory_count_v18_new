# -*- coding: utf-8 -*-
from datetime import datetime
import logging

from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SetuInventoryCountSession(models.Model):
    _name = 'setu.inventory.count.session'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin', 'barcodes.barcode_events_mixin']
    _description = 'Inventory Count Session'

    open_session_again = fields.Boolean(compute="_compute_open_session_again", string="Open session again")
    is_session_approved = fields.Boolean(default=False, string="Is session approved")
    re_open_session_bool = fields.Boolean(compute="_compute_re_open_session", string="Re-open session")
    use_barcode_scanner = fields.Boolean(default=False, string="Use barcode scanner")
    is_multi_session = fields.Boolean(default=False, string="Is multi session")
    session_strategy = fields.Selection(related='inventory_count_id.session_strategy', string="Session Strategy")
    count_strategy = fields.Selection(related='session_strategy', string="Count Strategy")

    name = fields.Char(string="Name")
    time_taken = fields.Char(compute="_compute_time_taken", string="Time Taken")

    session_submit_date = fields.Datetime(string="Session submit date")
    session_start_date = fields.Datetime(string="Session start date")
    session_end_date = fields.Datetime(string="Session end date")

    color = fields.Integer(compute="_compute_color", string="Color")
    total_products = fields.Integer(compute="_compute_scanned_products", store=True, string="Total Products")
    count_child_session_ids = fields.Integer(compute="_compute_child_session_ids", string="Child Sessions")
    total_scanned_products = fields.Integer(compute="_compute_scanned_products",
                                            store=True, string="Total Scanned Products")
    to_be_scanned = fields.Integer(compute="_compute_scanned_products", store=True, string="To be scanned")
    rejected_lines_count = fields.Integer(
        compute="_compute_rejected_lines_count",
        store=True,
        string="Rejected count lines",
    )
    session_history_count = fields.Integer(compute="_compute_session_history_count", string="Session history count")
    user_ids_count = fields.Integer(compute="_compute_user_ids_count", string="User Count", store=True)
    session_adjustment_count = fields.Integer(compute="_compute_session_adjustment_count", string="Adjustments")
    kanban_user_names = fields.Char(compute="_compute_kanban_display_names", string="Kanban Users")
    kanban_location_names = fields.Char(compute="_compute_kanban_display_names", string="Kanban Locations")

    state = fields.Selection(selection=[('Draft', 'Draft'), ('In Progress', 'In Progress'),
                                        ('Submitted', 'Submitted'), ('Done', 'Done'), ('Cancel', 'Cancel')],
                             default="Draft", string="State")

    approval_scope = fields.Selection(related='inventory_count_id.approval_scope', string="Approval Scope", store=True)
    adjustment_strategy = fields.Selection(related='inventory_count_id.adjustment_strategy',
                                           string="Adjustment Strategy", store=True)
    is_revision = fields.Boolean(string="Is Revision", default=False)
    revision_of_id = fields.Many2one('setu.inventory.count.session', string="Revision Of")
    current_state = fields.Selection(selection=[('Created', 'Created'), ('Resume', 'Resume'),
                                                ('Start', 'Start'), ('Pause', 'Pause'), ('End', 'End')],
                                     default='Created', string="Current State")

    inventory_count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", string="Inventory Count")
    location_id = fields.Many2one(comodel_name="stock.location", string="Location")
    assigned_location_ids = fields.Many2many(
        comodel_name="stock.location",
        relation="setu_inventory_count_session_location_rel",
        column1="session_id",
        column2="location_id",
        string="Locations",
        help="Allowed locations for this session when strategy is Location Wise.",
    )
    warehouse_id = fields.Many2one(comodel_name="stock.warehouse", string="Warehouse")
    company_id = fields.Many2one(comodel_name="res.company", related="warehouse_id.company_id", string="Company",
                                 store=True)
    session_id = fields.Many2one(comodel_name="setu.inventory.count.session", string="Session")
    current_scanning_location_id = fields.Many2one(comodel_name="stock.location", string="Current scanning location")
    current_scanning_product_id = fields.Many2one(comodel_name="product.product", string="Current scanning product")
    current_scanning_lot_id = fields.Many2one(comodel_name="stock.lot", string="Current scanning lot")

    session_line_ids = fields.One2many('setu.inventory.count.session.line', 'session_id',
                                       string="Inventory Session Count Lines")
    unscanned_product_lines_ids = fields.One2many(
        'setu.unscanned.product.lines',
        'session_id',
        string="Unscanned Products",
    )
    session_ids = fields.One2many('setu.inventory.count.session', 'session_id', string='Sessions')
    allowed_scan_location_ids = fields.Many2many(
        comodel_name="stock.location",
        compute="_compute_allowed_scan_location_ids",
        string="Allowed Scan Locations",
    )

    planned_products = fields.Integer(compute="_compute_session_stats", string="Planned Products")
    assigned_products = fields.Integer(compute="_compute_session_stats", string="Assigned Products")
    counted_quantity = fields.Float(compute="_compute_session_stats", string="Counted Quantity")
    variance = fields.Float(compute="_compute_session_stats", string="Variance")

    user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="setu_inventory_count_session_user_rel",
        column1="session_id",
        column2="user_id",
        string="Users",
        domain=lambda self: self._get_allowed_assignment_user_domain(),
    )

    count_state = fields.Selection(related='inventory_count_id.state', string="Count State")
    # Type field removed - use is_multi_session instead to determine session behavior
    approver_id = fields.Many2one(related="inventory_count_id.approver_id", string="Approver", store=True)

    def get_inventory_user_group(self):
        inventory_user_group = self.env.ref(
            'setu_inventory_count_management.group_setu_inventory_count_user',
            raise_if_not_found=False,
        )
        return inventory_user_group

    def _get_allowed_assignment_user_domain(self):
        inventory_user_group = self.get_inventory_user_group()
        domain = [('share', '=', False), ('company_ids', 'in', self.env.companies.ids)]
        if inventory_user_group:
            domain.append(('groups_id', 'in', [inventory_user_group.id]))
        return domain

    @api.constrains('user_ids')
    def _check_assigned_users_are_inventory_users(self):
        inventory_user_group = self.get_inventory_user_group()
        if not inventory_user_group:
            return
        for rec in self:
            invalid_users = rec.user_ids.filtered(lambda user: inventory_user_group not in user.groups_id)
            if invalid_users:
                raise ValidationError(_(
                    "Only users with Inventory Count User rights can be assigned to sessions."
                ))

    def _check_user_is_configured_approver(self):
        self.ensure_one()
        if self.approver_id and self.approver_id != self.env.user:
            raise ValidationError(_("Only the configured approver can perform this action."))

    @api.depends('assigned_location_ids', 'location_id', 'company_id', 'session_strategy')
    def _compute_allowed_scan_location_ids(self):
        for rec in self:
            rec.allowed_scan_location_ids = rec._get_allowed_locations_for_session()

    @api.constrains('session_line_ids')
    def check_session_line_ids(self):
        if not self.session_line_ids:
            self.current_scanning_location_id = self.current_scanning_product_id = self.current_scanning_lot_id = False

    def messege_return(self, msg_type, message):
        return {'warning': {'title': _(msg_type), 'message': _(message)}}

    def _get_allowed_locations_for_session(self):
        self.ensure_one()

        location_obj = self.env['stock.location'].sudo()
        strategy = self.inventory_count_id.session_strategy

        # Base domain (common for all cases)
        domain = [
            ('usage', '=', 'internal'),
            ('company_id', '=', self.company_id.id),
        ]

        # Apply additional filters
        if strategy == 'product_wise':
            return location_obj.search(domain)

        if self.assigned_location_ids:
            domain.append(('id', 'child_of', self.assigned_location_ids.ids))
        elif self.location_id:
            domain.append(('id', 'child_of', self.location_id.id))
        else:
            return location_obj.browse()

        return location_obj.search(domain)

    def _is_allowed_scan_location(self, location):
        self.ensure_one()
        if not location:
            return False
        return location.id in self._get_allowed_locations_for_session().ids

    def _check_product_session_limit(self, product):
        """Prevent scanning new products above configured session product limit."""
        self.ensure_one()

        if not product:
            return False

        count = self.inventory_count_id
        if not count.use_max_products or count.max_products_per_session <= 0:
            return False

        # Check if product already exists (no need to build full set)
        if product in self.session_line_ids.mapped('product_id'):
            return False

        # Check limit
        if len(self.session_line_ids) >= count.max_products_per_session:
            return self.messege_return(
                "Warning",
                f"You cannot scan more products in this session. "
                f"Maximum allowed products per session is {count.max_products_per_session}.",
            )

        return False

    def on_barcode_scanned(self, barcode):
        if self.use_barcode_scanner:
            if self.current_state in ('Start', 'Resume'):
                vals = {}
                scanning_done = False
                location = self.env['stock.location'].sudo().search([('barcode', '=', barcode)], limit=1)
                if location:
                    if not self._is_allowed_scan_location(location):
                        strategy = self.inventory_count_id.session_strategy
                        if strategy == 'location_wise':
                            return self.messege_return(
                                "Warning",
                                "Scanned location is not assigned to this session."
                            )
                        return self.messege_return(
                            "Warning",
                            "Only internal locations from the current company are allowed."
                        )
                    self.current_scanning_location_id = location
                    self.current_scanning_product_id = False
                    self.current_scanning_lot_id = False
                if not self.current_scanning_location_id:
                    return self.messege_return("Warning",
                                               "Please scan the Location first.")
                lot = self.env['stock.lot'].sudo().search([('name', '=ilike', barcode)], limit=1)
                if lot:
                    self.current_scanning_lot_id = lot
                    self.current_scanning_product_id = lot.product_id.id
                    if not self.session_id and not self.session_id.inventory_count_id.count_id:
                        session_lines = self.inventory_count_id.sudo().session_ids.mapped('session_line_ids')
                        if self.current_scanning_product_id.tracking == 'serial' and self.current_scanning_product_id and self.current_scanning_location_id:
                            if self.current_scanning_product_id.id in session_lines.filtered(
                                    lambda x: x.product_id == self.current_scanning_product_id and x.location_id != self.current_scanning_location_id
                                              and lot.id in x.serial_number_ids.ids
                                              and x.session_id.state != 'Cancel'
                                              and x.inventory_count_id == self.inventory_count_id).mapped(
                                'product_id').ids:
                                raise UserError(
                                    'Serial Number "{}" is already scanned in another location or by another user in '
                                    'another session for this Count.'.format(lot.name))
                        elif self.current_scanning_product_id.tracking == 'lot' and self.current_scanning_product_id and self.current_scanning_location_id and lot:
                            if self.current_scanning_product_id.id in session_lines.filtered(
                                    lambda x: x.product_id == self.current_scanning_product_id
                                              and x.session_id.state != 'Cancel'
                                              and x.location_id == self.current_scanning_location_id and x.lot_id.id == lot.id and x.inventory_count_id == self.inventory_count_id and x.session_id.id == self._origin.id).mapped(
                                'product_id').ids:
                                raise UserError(
                                    'Lot "{}" is already scanned for the same location in the same session for this Count.'.format(
                                        lot.name))
                    vals.update({'location_id': self.current_scanning_location_id.sudo().id,
                                 'product_id': self.current_scanning_product_id.id,
                                 'session_id': self._origin.id,
                                 'date_of_scanning': fields.Datetime.now(),
                                 'inventory_count_id': self.inventory_count_id.id})
                if self.current_scanning_location_id and self.current_scanning_product_id and self.current_scanning_product_id.tracking != 'none' and not self.current_scanning_lot_id:
                    return self.messege_return("Warning",
                                               "Please scan the Lot/Serial Number.")
                if self.current_scanning_product_id.tracking == 'lot':
                    quants_lot = self.env['stock.quant'].sudo().search(
                        [('location_id', '=', self.current_scanning_location_id.id),
                         ('lot_id', '=', lot.id),
                         ('product_id', '=', lot.product_id.id)])
                    vals.update({'lot_id': lot.id, 'theoretical_qty': sum([x.quantity for x in quants_lot])})  #

                if self.current_scanning_product_id.tracking == 'serial':
                    quants = self.env['stock.quant'].sudo().search(
                        [('location_id', '=', self.current_scanning_location_id.id),
                         ('quantity', '=', 1),
                         ('product_id', '=', lot.product_id.id)])
                    qty_available = sum([x.quantity for x in quants])
                    vals.update({'serial_number_ids': [(4, lot.id)], 'theoretical_qty': qty_available})  # ,

                product = self.env['product.product'].sudo().search([('barcode', '=', barcode)], limit=1)
                if product:
                    limit_warning = self._check_product_session_limit(product)
                    if limit_warning:
                        return limit_warning
                    if not self.current_scanning_lot_id and product.tracking == 'lot':
                        return self.messege_return("Warning",
                                                   "Please scan the Lot of the Product first!")
                    if product.tracking in ['lot',
                                            'serial'] and self.current_scanning_lot_id and self.current_scanning_lot_id.sudo().product_id != product:
                        return self.messege_return("Warning",
                                                   "Please select an appropriate lot number as current lot is not belongs to the product you have scanned.")
                    if product.tracking == 'none':
                        self.current_scanning_product_id = product
                        self.current_scanning_lot_id = False
                        session_lines = self.inventory_count_id.sudo().session_ids.mapped('session_line_ids')
                        # if self.current_scanning_product_id.tracking == 'none' and self.current_scanning_product_id and self.current_scanning_location_id:
                        #     if self.current_scanning_product_id.id in session_lines.filtered(
                        #             lambda x: x.product_id == self.current_scanning_product_id
                        #                       and x.session_id.state != 'Cancel' and x.state != 'Reject'
                        #                       and x.location_id == self.current_scanning_location_id and x.inventory_count_id == self.inventory_count_id and x.session_id.id == self._origin.id).mapped(
                        #         'product_id').ids:
                        #         raise UserError('Product "{}" is already scanned for the same location '
                        #                         'in the same session for this Count.'.format(
                        #             self.current_scanning_product_id.name))
                        none_type_product_line_already_exist = self.session_line_ids.filtered(
                            lambda x: x.location_id == self.current_scanning_location_id and x.product_id == product)
                        if not none_type_product_line_already_exist:
                            quants = self.env['stock.quant'].sudo().search(
                                [('location_id', '=', self.current_scanning_location_id.id),
                                 ('product_id', '=', product.id)])
                            qty_available = sum([x.quantity for x in quants])
                            self.write({'session_line_ids': [(0, 0, {
                                'location_id': self.current_scanning_location_id.sudo().id,
                                'product_id': product.id,
                                'date_of_scanning': fields.Datetime.now(),
                                'session_id': self._origin.id,
                                'inventory_count_id': self.inventory_count_id.id,
                                'scanned_qty': 1,
                                'theoretical_qty': qty_available
                            })]})
                        else:
                            none_type_product_line_already_exist.scanned_qty += 1
                        scanning_done = True
                    if product and product.tracking != 'none':
                        self.current_scanning_product_id = product
                        new_product = product not in self.session_line_ids.mapped('product_id')
                        if new_product:
                            self.current_scanning_product_id = product
                            self.current_scanning_lot_id = False
                        if self.current_scanning_location_id and self.current_scanning_product_id:
                            session_line = self.session_line_ids.filtered(
                                lambda x: x.location_id == self.current_scanning_location_id and (
                                        x.lot_id == self.current_scanning_lot_id or x.serial_number_ids in self.session_line_ids.serial_number_ids) and x.product_id == product)
                            if session_line:
                                if session_line.product_scanned:
                                    return self.messege_return("Warning",
                                                               f"{product.display_name} is marked scanned in location {self.current_scanning_location_id.sudo().display_name} for this session. "
                                                               f"Please uncheck the Scanned checkbox.")
                                session_line.scanned_qty += 1
                                scanning_done = True
                            else:
                                vals.update({'location_id': self.current_scanning_location_id.sudo().id,
                                             'product_id': self.current_scanning_product_id.id,
                                             'session_id': self._origin.id,
                                             'inventory_count_id': self.inventory_count_id.id})
                        else:
                            self.current_scanning_product_id = False
                            return self.messege_return("Warning",
                                                       "Please set the current location, then scan the products.")
                    if self.current_scanning_location_id and not product:
                        return self.messege_return("Warning",
                                                   "Product or Location with scanned barcode is not found.")
                if not scanning_done and self.current_scanning_location_id and self.current_scanning_product_id and self.current_scanning_lot_id:
                    if product.tracking in ['lot',
                                            'serial'] and self.current_scanning_lot_id and self.current_scanning_lot_id.sudo().product_id != product:
                        return self.messege_return("Warning",
                                                   "Please select an appropriate lot number as current lot is not belongs to the product you have scanned.")
                    line_already_exist = False
                    if self.current_scanning_product_id.tracking == 'lot':
                        line_already_exist = self.session_line_ids.filtered(
                            lambda x: x.location_id == self.current_scanning_location_id and (
                                    x.lot_id == self.current_scanning_lot_id) and x.product_id == self.current_scanning_product_id)
                    elif self.current_scanning_product_id.tracking == 'serial':
                        line_already_exist = self.session_line_ids.filtered(
                            lambda
                                x: x.location_id == self.current_scanning_location_id and x.product_id == self.current_scanning_product_id)

                    if line_already_exist and self.current_scanning_product_id.tracking == 'serial':
                        if self.current_scanning_lot_id.id not in line_already_exist.serial_number_ids.ids:
                            count = len(line_already_exist.serial_number_ids) + 1
                            line_already_exist.scanned_qty = count
                            line_already_exist.serial_number_ids |= self.current_scanning_lot_id
                    if not line_already_exist:
                        if self.current_scanning_product_id.tracking == 'lot':
                            vals.update({'lot_id': lot.id})
                        if self.current_scanning_product_id.tracking == 'serial':
                            vals.update({'serial_number_ids': [(4, lot.id)],
                                         'scanned_qty': 1})
                        if not self.current_scanning_lot_id:
                            return self.messege_return("Warning",
                                                       "Please scan the Lot/Serial Number.")
                        self.write({'session_line_ids': [(0, 0, vals)]})
                if not lot and not location and not product:
                    return self.messege_return("Warning",
                                               "Product, Lot/Serial Number or Location with scanned barcode is not found!")
                if not lot and location and product and product.tracking == 'serial':
                    return self.messege_return("Warning",
                                               "Please scan Serial Number of the product.")
            else:
                return self.messege_return("Warning",
                                           "Please Start/Resume the session to continue.")
        else:
            return self.messege_return("Notification",
                                       "Contact your approver to enable the barcode scanning for this session.")

    @api.depends('user_ids')
    def _compute_user_ids_count(self):
        for rec in self:
            rec.user_ids_count = len(rec.user_ids)

    def _compute_session_adjustment_count(self):
        for rec in self:
            rec.session_adjustment_count = len(
                rec.inventory_count_id.inventory_adj_ids.filtered(lambda adj: adj.session_id == rec)
            )

    @api.depends('user_ids.name', 'assigned_location_ids.display_name', 'location_id.display_name')
    def _compute_kanban_display_names(self):
        for rec in self:
            rec.kanban_user_names = ", ".join(rec.user_ids.mapped('name')) if rec.user_ids else "-"
            if rec.assigned_location_ids:
                rec.kanban_location_names = ", ".join(rec.assigned_location_ids.mapped('display_name'))
            else:
                rec.kanban_location_names = rec.location_id.display_name or "-"

    def _compute_color(self):
        for rec in self:
            if rec.state == 'In Progress':
                if rec.current_state in ('Start', 'Resume'):
                    rec.color = 2
                elif rec.current_state == 'Pause':
                    rec.color = 3
            if rec.session_ids:
                rec.color = 1
            else:
                rec.color = 0

    def _compute_time_taken(self):
        for rec in self:
            if rec.state in ('In Progress', 'Done', 'Submitted'):
                session_details = self.env['setu.inventory.session.details'].search([('session_id', '=', rec.id)])
                if session_details:
                    duration_in_seconds = sum(session_details.mapped('duration_seconds'))
                    whole_minutes = int(duration_in_seconds / 60)
                    seconds = duration_in_seconds % 60
                    hours = int(whole_minutes / 60)
                    minutes = whole_minutes % 60
                    time_stamp = str(hours).zfill(2) + ':' + str(minutes).zfill(2) + ':' + str(seconds).zfill(2)
                    rec.time_taken = time_stamp
                else:
                    rec.time_taken = '00:00:00'
            else:
                rec.time_taken = ''

    @api.depends('session_line_ids.state')
    def _compute_rejected_lines_count(self):
        for rec in self:
            rejected_lines = rec.session_line_ids.filtered(lambda l: l.state == 'Reject')
            rec.rejected_lines_count = len(rejected_lines) if rejected_lines else 0

    def _compute_child_session_ids(self):
        for rec in self:
            rec.count_child_session_ids = len(self.session_ids)

    def _compute_open_session_again(self):
        for session in self:
            if session.session_line_ids.filtered(lambda s: s.state == 'Reject'):
                session.open_session_again = True
            else:
                session.open_session_again = False

    def create_re_session(self):
        view_id = self.sudo().env.ref(
            'setu_inventory_count_management.setu_inventory_session_resession_create_validate_form_view')
        return {
            'name': 'Rejected Lines Found!!!',
            'view_mode': 'form',
            'view_id': view_id.id,
            'res_model': 'setu.inventory.session.validate.wizard',
            'type': 'ir.actions.act_window',
            'target': 'new'
        }

    def open_new_session(self):
        if self.session_line_ids.filtered(lambda s: s.state == 'Pending Review'):
            raise ValidationError(
                _('Please check and set the state in all session lines of this session to open this session again.'))
        rejected_lines = self.session_line_ids.filtered(lambda s: s.state == 'Reject')
        new_session = self.env['setu.inventory.count.session'].create({
            'inventory_count_id': self.inventory_count_id.id,
            'location_id': self.location_id.id,
            'assigned_location_ids': [(6, 0, self.assigned_location_ids.ids)],
            'warehouse_id': self.warehouse_id.id,
            'use_barcode_scanner': self.use_barcode_scanner,
            'state': 'Draft',
            'current_state': 'Created',
            'session_submit_date': False,
            'session_start_date': False,
            'session_end_date': False,
            'current_scanning_location_id': False,
            'current_scanning_product_id': False,
            'current_scanning_lot_id': False,
        })
        for line in rejected_lines:
            new_session_line = line.copy()
            new_session_line.session_id = new_session
            new_session_line.scanned_qty = 0
            new_session_line.serial_number_ids = False
        new_session.session_id = self
        new_session.user_ids = self.user_ids

    def check_unscanned_session(self):
        self.ensure_one()
        self._check_user_is_configured_approver()
        if self.approval_scope != 'session_level' or self.session_strategy == 'product_wise':
            return True
        locations = self.assigned_location_ids or self.session_line_ids.mapped('location_id')
        if not locations and self.location_id:
            locations = self.location_id + self.location_id.child_ids
        if not locations:
            raise ValidationError(
                _('No locations found from session lines. Please scan products first.'))

        quants = self.env['stock.quant'].search([('location_id', 'in', locations.ids)])
        counted_product_ids = set(self.session_line_ids.mapped('product_id.id'))
        counted_lot_ids = set(self.session_line_ids.mapped('lot_id.id') + self.session_line_ids.mapped('serial_number_ids.id'))
        quants_to_add = quants.filtered(
            lambda x: x.product_id.id not in counted_product_ids or
            (x.product_id.id in counted_product_ids and x.lot_id and x.lot_id.id not in counted_lot_ids)
        )

        vals_list = [{
            'inventory_count_id': self.inventory_count_id.id,
            'session_id': self.id,
            'product_id': q.product_id.id,
            'lot_id': q.lot_id.id if q.lot_id else False,
            'location_id': q.location_id.id,
            'quantity': q.quantity,
        } for q in quants_to_add]
        if vals_list:
            self.env['setu.unscanned.product.lines'].create(vals_list)
        if self.unscanned_product_lines_ids:
            return self.action_open_unscanned_products()
        return {'type': 'ir.actions.client', 'tag': 'reload'}


    def action_open_unscanned_products(self):
        self.ensure_one()
        view_id = self.sudo().env.ref('setu_inventory_count_management.setu_unscanned_product_lines')
        return {
            'name': 'Unscanned Products',
            'view_mode': 'list',
            'view_id': view_id.id,
            'res_model': 'setu.unscanned.product.lines',
            'type': 'ir.actions.act_window',
            'domain': [('session_id', '=', self.id)],
        }

    def _compute_session_history_count(self):
        for rec in self:
            if rec.current_state == 'Created':
                rec.session_history_count = 0
            else:
                session_details = self.env['setu.inventory.session.details'].search([('session_id', '=', self.id)])
                rec.session_history_count = len(session_details)

    def action_view_session_history(self):
        return {
            'name': 'History',
            'view_mode': 'list',
            'view_id': self.sudo().env.ref(
                'setu_inventory_count_management.setu_inventory_session_details_tree_view').id,
            'res_model': 'setu.inventory.session.details',
            'type': 'ir.actions.act_window',
            'domain': [('session_id', '=', self.id)]
        }

    @api.depends('session_line_ids', 'session_line_ids.scanned_qty', 'session_line_ids.difference_qty', 'user_ids')
    def _compute_session_stats(self):
        for rec in self:
            rec.planned_products = len(rec.session_line_ids)
            rec.assigned_products = len(rec.user_ids)
            rec.counted_quantity = sum(rec.session_line_ids.mapped('scanned_qty'))
            rec.variance = sum(rec.session_line_ids.mapped('difference_qty'))

    @api.depends('session_line_ids', 'session_line_ids.product_id', 'session_line_ids.product_scanned')
    def _compute_scanned_products(self):
        for session in self:
            lines = session.session_line_ids
            session.total_products = len(lines.mapped('product_id'))
            product_dict = {product_id.id: [0, 0] for product_id in lines.mapped('product_id')}
            for line in lines:
                if product_dict.get(line.product_id.id, False):
                    product_dict[line.product_id.id][0] += 1
                    if line.product_scanned:
                        product_dict[line.product_id.id][1] += 1
            total_scanned_products = 0
            for product, scan_value in product_dict.items():
                if scan_value[0] > 0 and scan_value[0] == scan_value[1]:
                    total_scanned_products += 1
            to_be_scanned = session.total_products - total_scanned_products
            session.total_scanned_products = total_scanned_products
            session.to_be_scanned = to_be_scanned

    def _should_send_session_assignment_notification(self):
        """Tell whether assignment emails/inbox posts should run for this session."""
        self.ensure_one()
        if not self.inventory_count_id:
            return False
        planner = self.inventory_count_id.planner_id
        if planner:
            return planner.notify_users_on_session_assignment
        # Counts not created from a planner: still notify (wizard / manual assignment).
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['name'] = self.env['ir.sequence'].next_by_code('setu.inventory.count.session.seq')
        sessions = super(SetuInventoryCountSession, self).create(vals_list)
        for session in sessions:
            if session.user_ids and session._should_send_session_assignment_notification():
                session._send_notification_to_users()
        return sessions

    def write(self, vals):
        """Override write to send notifications when users are assigned"""
        user_ids_before = {}
        if 'user_ids' in vals:
            user_ids_before = {
                rec.id: set(rec.user_ids.ids)
                for rec in self
            }

        res = super().write(vals)

        if 'user_ids' not in vals:
            return res

        for rec in self:
            if not rec._should_send_session_assignment_notification():
                continue

            before_ids = user_ids_before.get(rec.id, set())
            after_ids = set(rec.user_ids.ids)
            newly_assigned = after_ids - before_ids
            if newly_assigned:
                rec._send_notification_to_users(newly_assigned)

        return res

    def _send_notification(self, users, template_xmlid=None, context_data=None, fallback_message=None):
        """Generic method to send email + inbox notification."""
        self.ensure_one()
        if not users:
            return

        template = self.env.ref(template_xmlid, raise_if_not_found=False) if template_xmlid else False
        company = self.company_id.sudo()
        mail_from = (
                            getattr(company, 'email_formatted', None) or company.email or ''
                    ).strip() or (
                            self.env.user.partner_id.email or ''
                    )

        email_base = {}
        if mail_from:
            email_base.update({
                'email_from': mail_from,
                'reply_to': mail_from,
            })

        for user in users:
            partner = user.partner_id
            if not partner:
                continue

            email = (partner.email or '').strip()
            emailed = False

            # ✅ Send Email
            if template and email:
                try:
                    template.sudo().with_context(
                        lang=user.lang or partner.lang or self.env.lang,
                        **(context_data or {})
                    ).send_mail(
                        self.id,
                        force_send=True,
                        email_values={
                            'email_to': email,
                            **email_base
                        },
                    )
                    emailed = True
                except Exception:
                    _logger.exception("Email sending failed for user %s", user.id)

            # ✅ Inbox / fallback notification
            if user.notification_type == 'inbox' or not emailed:
                if fallback_message:
                    self.message_post(
                        body=fallback_message,
                        partner_ids=[partner.id],
                        message_type='notification',
                        subtype_xmlid='mail.mt_comment',
                    )

    def _send_notification_to_users(self, user_ids=None):
        """Notify assigned users."""
        if not self._should_send_session_assignment_notification():
            return

        users = self.env['res.users'].browse(user_ids) if user_ids else self.user_ids

        message = _("You have been assigned to Inventory Count Session '%s'.") % self.display_name

        self._send_notification(
            users=users,
            template_xmlid='setu_inventory_count_management.mail_template_notify_users_session_assignment',
            context_data={
                'user_name': False,  # handled per user via template
            },
            fallback_message=message,
        )

    def _notify_approver_on_submit(self):
        """Notify approver on submit."""
        self.ensure_one()

        message = _(
            "Approval request email sent to approver '%s' (%s)."
        ) % (self.approver_id.display_name, self.approver_id.partner_id.email)

        self._send_notification(
            users=self.approver_id,
            template_xmlid='setu_inventory_count_management.mail_template_notify_approver_session_submit',
            context_data={
                'submitter_name': self.env.user.name,
                'submitter_email': self.env.user.partner_id.email,
                'approver_name': self.approver_id.name,
            },
            fallback_message=message,
        )

    def start(self):
        if self.state == 'Cancel':
            raise ValidationError(_("Administrator has already Cancelled the Session."))
        if self.current_state == 'Start':
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        running_session = self.sudo().search([
            ('id', '!=', self.id),
            ('user_ids', 'in', self.user_ids.ids),
            ('current_state', 'in', ['Start', 'Resume'])
        ])
        if running_session:
            raise ValidationError(_("One or more users in this session are already active in another running session. "
                                    "Users cannot Start/Resume more than one session at a time."))
        self.current_state = 'Start'
        date_today = fields.Datetime.now()
        self.session_start_date = date_today
        self.sudo().env['setu.inventory.session.details'].create({
            'session_id': self.id,
            'start_date': date_today
        })
        self.state = 'In Progress'
        self.sudo().inventory_count_id.state = 'In Progress'
        if not self.session_id:
            for line in self.inventory_count_id.line_ids:
                line.sudo().qty_in_stock = line.theoretical_qty

    def pause(self):
        if self.current_state == 'Pause':
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        if self.current_state == 'End':
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        else:
            self.current_state = 'Pause'
            unfinished_history = self.env['setu.inventory.session.details'].search(
                [('session_id', '=', self.id), ('end_date', '=', False)])
            date_today = fields.Datetime.now()
            unfinished_history.end_date = date_today

    def resume(self):
        if self.current_state in ['Resume', 'End']:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        running_session = self.sudo().search([
            ('id', '!=', self.id),
            ('user_ids', 'in', self.user_ids.ids),
            ('current_state', 'in', ['Start', 'Resume'])
        ])
        if running_session:
            raise ValidationError(_("One or more users in this session are already active in another running session. "
                                    "Users cannot Start/Resume more than one session at a time."))
        self.current_state = 'Resume'
        date_today = fields.Datetime.now()
        self.env['setu.inventory.session.details'].create({'session_id': self.id, 'start_date': date_today})

    def _merge_to_count_lines(self, from_session_approve=False):
        """Merge session lines into inventory count lines with serial handling."""
        self.ensure_one()

        inventory_count = self.inventory_count_id

        lines, count_state = self._get_lines_to_merge(from_session_approve)
        if not lines:
            return

        count_line_map = self._prepare_count_line_map(inventory_count)
        serial_index = self._build_serial_index(inventory_count)
        moves_by_product = self._get_moves_by_product(lines)
        quant_map = self._get_quant_map(lines)

        not_found_serial_map = {}

        for line in lines:
            self._process_single_line(
                line,
                inventory_count,
                count_line_map,
                serial_index,
                moves_by_product,
                quant_map,
                count_state,
                not_found_serial_map,
            )

        self._apply_not_found_serials(inventory_count, not_found_serial_map)

    def _get_lines_to_merge(self, from_session_approve):
        if self.approval_scope == 'session_level' and from_session_approve:
            lines = self.session_line_ids.filtered(lambda l: l.state == 'Approve')
            return lines, 'Approve'
        else:
            lines = self.session_line_ids.filtered(lambda l: l.state != 'Cancel')
            return lines, 'Pending Review'

    def _prepare_count_line_map(self, inventory_count):
        return {
            (cl.product_id.id, cl.location_id.id, cl.lot_id.id or False): cl
            for cl in inventory_count.line_ids
        }

    def _build_serial_index(self, inventory_count):
        serial_index = {}
        all_lines = inventory_count.session_ids.mapped('session_line_ids')

        for sl in all_lines:
            if sl.tracking == 'serial' and sl.state != 'Reject' and sl.session_id.state != 'Cancel':
                for serial_id in sl.serial_number_ids.ids:
                    serial_index.setdefault(serial_id, set()).add(sl.id)

        return serial_index

    def _get_moves_by_product(self, lines):
        product_ids = lines.mapped('product_id').ids
        earliest_date = min(lines.mapped('date_of_scanning'))

        moves = self.env['stock.move.line'].sudo().search([
            ('state', '=', 'done'),
            ('product_id', 'in', product_ids),
            ('move_id.picking_type_id.code', '=', 'outgoing'),
            ('date', '>=', earliest_date),
        ])

        moves_by_product = {}
        for mv in moves:
            moves_by_product.setdefault(mv.product_id.id, self.env['stock.move.line'])
            moves_by_product[mv.product_id.id] |= mv

        return moves_by_product

    def _get_quant_map(self, lines):
        quant_map = {}

        quants = self.env['stock.quant'].sudo().search([
            ('product_id', 'in', lines.mapped('product_id').ids),
            ('location_id', 'in', lines.mapped('location_id').ids),
            ('quantity', '=', 1),
        ])

        for q in quants:
            if q.lot_id:
                key = (q.product_id.id, q.location_id.id)
                quant_map.setdefault(key, self.env['stock.lot'])
                quant_map[key] |= q.lot_id

        return quant_map

    def _process_single_line(
            self,
            line,
            inventory_count,
            count_line_map,
            serial_index,
            moves_by_product,
            quant_map,
            count_state,
            not_found_serial_map,
    ):
        line.product_scanned = True

        users = line.user_ids or line.session_id.user_ids
        user_cmd = [(4, uid) for uid in users.ids] if users else []

        moves = moves_by_product.get(line.product_id.id)
        if moves:
            moves.write({'count_id': inventory_count.id})

        count_line = self._get_or_create_count_line(line, count_line_map)
        self._validate_serial_duplicates(line, serial_index)
        vals = self._prepare_count_line_vals(line, count_line, user_cmd, count_state)

        if line.tracking == 'serial':
            vals['serial_number_ids'] = [(6, 0, (count_line.serial_number_ids | line.serial_number_ids).ids)]

        count_line.write(vals)
        line.inventory_count_line_id = count_line.id

        if line.tracking == 'serial':
            self._handle_missing_serials(line, count_line, quant_map, not_found_serial_map)

    def _get_or_create_count_line(self, line, count_line_map):
        lot_id = line.lot_id.id if line.tracking == 'lot' else False
        key = (line.product_id.id, line.location_id.id, lot_id)

        count_line = count_line_map.get(key)
        if not count_line:
            count_line = self.create_new_count_line(line)
            count_line_map[key] = count_line

        return count_line

    def _validate_serial_duplicates(self, line, serial_index):
        if line.tracking != 'serial':
            return

        duplicate_ids = [
            s for s in line.serial_number_ids.ids
            if len(serial_index.get(s, [])) > 1
        ]

        if duplicate_ids:
            lots = self.env['stock.lot'].browse(duplicate_ids)
            raise UserError(_(
                'Serial Number "%s" is scanned multiple times.'
            ) % ", ".join(lots.mapped('name')))

    def _prepare_count_line_vals(self, line, count_line, user_cmd, count_state):
        theoretical_qty = line._get_theoretical_qty(count_line)

        counted_qty = (
            line.scanned_qty
            if self.session_id
            else line._get_counted_qty(line, count_line)
        )

        return {
            'theoretical_qty': theoretical_qty,
            'qty_in_stock': theoretical_qty,
            'counted_qty': counted_qty,
            'user_ids': user_cmd,
            'state': count_state,
        }

    def _handle_missing_serials(self, line, count_line, quant_map, not_found_serial_map):
        expected = quant_map.get(
            (line.product_id.id, line.location_id.id),
            self.env['stock.lot']
        )

        found = count_line.serial_number_ids
        missing = expected - found

        if missing:
            key = (line.product_id.id, line.location_id.id)
            not_found_serial_map[key] = missing
        else:
            count_line.write({'not_found_serial_number_ids': [(5, 0, 0)]})

    def _apply_not_found_serials(self, inventory_count, not_found_serial_map):
        for (prod_id, loc_id), lots in not_found_serial_map.items():
            cl = inventory_count.line_ids.filtered(
                lambda l: l.product_id.id == prod_id and l.location_id.id == loc_id
            )
            if cl:
                cl.write({
                    'not_found_serial_number_ids': [(6, 0, lots.ids)]
                })

    def submit(self):
        if self.current_state in ['End']:
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        self.current_state = 'End'
        date_now = fields.Datetime.now()
        unfinished_history = self.sudo().env['setu.inventory.session.details'].search(
            [('session_id', '=', self.id), ('end_date', '=', False)])
        unfinished_history.write({'end_date': date_now})

        self.current_scanning_location_id = False
        self.current_scanning_product_id = False
        self.current_scanning_lot_id = False
        self.session_submit_date = date_now
        self.state = 'Submitted'
        self._notify_approver_on_submit()
        if self.approval_scope != 'session_level':
            self._merge_to_count_lines(from_session_approve=False)

        self.inventory_count_id.action_submit_session(self)

    def _create_new_line(self, line):
        new_line = self.env['setu.stock.inventory.count.line'].create({
            'inventory_count_id': self.inventory_count_id.id,
            'product_id': line.product_id.id,
            'tracking': line.tracking,
            'serial_number_ids': [(6, 0, line.serial_number_ids.ids)] if line.serial_number_ids else False,
            'lot_id': line.lot_id.id,
            'location_id': line.location_id.id,
            'theoretical_qty': 0,
            'qty_in_stock': 0,
            'counted_qty': 0,
            'user_ids': line.user_ids
        })
        return new_line

    def create_new_count_line(self, line):
        new_count_line = self._create_new_line(line)
        qty = line.scanned_qty
        theoretical_qty = line._get_theoretical_qty(new_count_line)
        new_count_line.write({
            'theoretical_qty': theoretical_qty,
            'qty_in_stock': theoretical_qty,
            'counted_qty': qty
        })
        return new_count_line

    def approve_all_lines(self):
        self.ensure_one()
        self._check_user_is_configured_approver()
        wiz = self.env['setu.inventory.warning.message.wizard'].create({
            'message': "Are you sure that you want to Approve all session lines? (Even rejected lines will also be approved)"
        })
        return {
            'name': 'Warning!!!',
            'view_mode': 'form',
            'view_id': self.sudo().env.ref(
                'setu_inventory_count_management.setu_inventory_warning_message_wizard_form_view').id,
            'res_model': 'setu.inventory.warning.message.wizard',
            'type': 'ir.actions.act_window',
            'res_id': wiz.id,
            'target': 'new'
        }

    def action_open_child_sessions(self):
        sessions_to_open = self.session_ids
        action = \
            self.sudo().sudo().env.ref('setu_inventory_count_management.inventory_count_session_act_window').read()[0]
        if len(sessions_to_open) > 1:
            action['domain'] = [('id', 'in', sessions_to_open.ids)]
        elif len(sessions_to_open) == 1:
            action['views'] = [
                (self.sudo().env.ref('setu_inventory_count_management.inventory_count_session_form_view').id, 'form')]
            action['res_id'] = sessions_to_open.ids[0]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    def action_open_session_inventory_adjustments(self):
        self.ensure_one()
        inventory_adjs = self.inventory_count_id.inventory_adj_ids.filtered(lambda adj: adj.session_id == self)
        action = self.sudo().env.ref('setu_inventory_count_management.setu_stock_inventory_act_window').read()[0]
        if len(inventory_adjs) > 1:
            action['domain'] = [('id', 'in', inventory_adjs.ids)]
        elif len(inventory_adjs) == 1:
            action['views'] = [
                (self.sudo().env.ref('setu_inventory_count_management.setu_stock_inventory_form_view').id, 'form')
            ]
            action['res_id'] = inventory_adjs.ids[0]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    def action_approve(self):
        self.ensure_one()
        self._check_user_is_configured_approver()
        if self.state != 'Submitted':
            raise ValidationError(_("You can approve only a submitted session."))
        if self.approval_scope != 'session_level':
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        # Merge only approved session lines and mark count lines approved
        self._merge_to_count_lines(from_session_approve=True)
        for count_line in self.inventory_count_id.line_ids:
            self._set_calculation_mistake_value(
                count_line,
                count_line.counted_qty,
            )
        self.state = 'Done'

        # Call count approval logic to check if all sessions are done
        self.inventory_count_id.action_approve(session=self)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_reject(self):
        self.ensure_one()
        self._check_user_is_configured_approver()
        if self.state != 'Submitted':
            raise ValidationError(_("You can reject only a submitted session."))
        if self.approval_scope != 'session_level':
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        # Whole session rejected -> Create revision for all lines or just variance?
        # Standard behavior in this module seems to be creating a revision session.
        self.inventory_count_id.action_reject(session=self)
        self.state = 'Cancel'
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _set_calculation_mistake_value(self, count_line, final_qty=False):
        """
        Evaluate user mistakes once per count line.
        No recursion. No overrides.
        """
        if final_qty is False:
            return
        for line in count_line.session_line_ids:
            line.with_context(auto_user_mistake_update=True).write({
                'user_calculation_mistake': (line.scanned_qty != final_qty),
            })

    def _validate_session(self):
        if self.state == 'Done':
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }
        session_lines = self.session_line_ids.filtered(lambda x: x.product_id)
        for line in session_lines:
            tracking = line.product_id.tracking
            if tracking == 'lot':
                count_line = self.inventory_count_id.line_ids.filtered(
                    lambda
                        l: l.product_id == line.product_id and l.location_id == line.location_id and l.lot_id == line.lot_id)
            elif tracking == 'serial':
                count_line = self.inventory_count_id.line_ids.filtered(
                    lambda l: l.product_id == line.product_id and l.location_id == line.location_id
                              and any(b in l.serial_number_ids.ids for b in line.serial_number_ids.ids))
            else:
                count_line = self.inventory_count_id.line_ids.filtered(
                    lambda l: l.product_id == line.product_id and l.location_id == line.location_id)

            # Single session: update count line directly (multi-session requires approval first)
            if count_line and line.is_system_generated and not self.is_multi_session:
                count_line.counted_qty = line.scanned_qty
        self.state = 'Done'

        if self.approval_scope != 'session_level':
            self._remove_rejected_count_lines()

    def _remove_rejected_count_lines(self):
        rejected_lines = self.session_line_ids.filtered(lambda l: l.state == 'Reject')
        count_line_obj = self.env['setu.stock.inventory.count.line']
        for line in rejected_lines:
            domain = [
                ('inventory_count_id', '=', self.inventory_count_id.id),
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', line.location_id.id),
            ]
            if line.product_id.tracking == 'lot':
                domain.append(('lot_id', '=', line.lot_id.id))
            count_line_obj.search(domain).unlink()

    def validate_session(self):
        """Validate session with optimized classification and serial handling."""
        self.ensure_one()
        self._check_user_is_configured_approver()

        pending_lines, system_lines, rejected_lines = self._classify_session_lines()
        if pending_lines:
            raise ValidationError(_(
                'There are some lines with Pending Review. '
                'Please review all lines before validating the session.'
            ))

        count_line_map = self._prepare_system_generated_map()
        self._apply_system_generated_lines(system_lines, count_line_map)
        action = self._handle_rejected_lines(rejected_lines)
        if action:
            return action

        self._finalize_validation(rejected_lines)

    # -------------------------------------------------
    # 1. CLASSIFY LINES
    # -------------------------------------------------
    def _classify_session_lines(self):
        pending_lines = []
        system_lines = []
        rejected_lines = []

        for line in self.session_line_ids:
            state = line.state

            if state == 'Pending Review':
                pending_lines.append(line)
            elif state == 'Approve' and line.is_system_generated:
                system_lines.append(line)
            elif state == 'Reject':
                rejected_lines.append(line)
        return pending_lines, system_lines, rejected_lines


    def _prepare_system_generated_map(self):
        inventory_count = self.inventory_count_id
        return {
            (
                cl.product_id.id,
                cl.location_id.id,
                cl.lot_id.id or False
            ): cl
            for cl in inventory_count.line_ids
            if cl.is_system_generated
        }

    def _apply_system_generated_lines(self, system_lines, count_line_map):
        for line in system_lines:
            key = (
                line.product_id.id,
                line.location_id.id,
                line.lot_id.id or False
            )
            count_line = count_line_map.get(key)
            if not count_line:
                continue

            # direct assignment (faster than write)
            count_line.counted_qty = line.scanned_qty
            if count_line.product_id.tracking == 'serial':
                self._merge_serials(count_line, line)

    def _merge_serials(self, count_line, session_line):
        existing_serials = set(count_line.serial_number_ids.ids)
        new_serials = set(session_line.serial_number_ids.ids)

        merged_serials = list(existing_serials | new_serials)
        remaining_not_found = list(
            set(count_line.not_found_serial_number_ids.ids) - new_serials
        )

        count_line.write({
            'serial_number_ids': [(6, 0, merged_serials)],
            'not_found_serial_number_ids': [(6, 0, remaining_not_found)],
        })

    def _handle_rejected_lines(self, rejected_lines):
        if (
                rejected_lines
                and self.re_open_session_bool
                and self.approval_scope != 'session_level'
        ):
            env = self.sudo().env
            return {
                'name': 'Rejected Lines Found!!!',
                'type': 'ir.actions.act_window',
                'res_model': 'setu.inventory.session.validate.wizard',
                'view_mode': 'form',
                'view_id': env.ref(
                    'setu_inventory_count_management.'
                    'setu_inventory_session_reject_resession_validate_form_view'
                ).id,
                'target': 'new',
            }
        return False

    def _finalize_validation(self, rejected_lines):
        inventory_count = self.inventory_count_id
        self._validate_session()

        if self.approval_scope == 'session_level':
            self._merge_to_count_lines(from_session_approve=True)
            if rejected_lines:
                inventory_count.action_reject(session=self)

        inventory_count.action_approve(session=self)

    def _create_count_line_from_session_line(self, session_line):
        """Create a count line from session line for multi-session"""
        count_line_vals = {
            'inventory_count_id': self.inventory_count_id.id,
            'product_id': session_line.product_id.id,
            'location_id': session_line.location_id.id,
            'lot_id': session_line.lot_id.id if session_line.lot_id else False,
            'counted_qty': session_line.scanned_qty,
            'theoretical_qty': session_line.theoretical_qty,
            'state': 'Approve',
            'serial_number_ids': [(6, 0, session_line.serial_number_ids.ids)],
            'not_found_serial_number_ids': [(6, 0, session_line.not_found_serial_number_ids.ids)],
            'is_system_generated': session_line.is_system_generated,
        }
        return self.env['setu.stock.inventory.count.line'].create(count_line_vals)

    def reject_all_lines(self):
        self.ensure_one()
        self._check_user_is_configured_approver()
        wiz = self.env['setu.inventory.warning.message.wizard'].create({
            'message': "Are you sure that you want to Reject all session lines? (Even approved lines will also be rejected)"
        })
        return {
            'name': 'Warning!!!',
            'view_mode': 'form',
            'view_id': self.sudo().env.ref(
                'setu_inventory_count_management.setu_inventory_warning_reject_message_wizard_form_view').id,
            'res_model': 'setu.inventory.warning.message.wizard',
            'type': 'ir.actions.act_window',
            'res_id': wiz.id,
            'target': 'new'
        }

    def cancel_session(self):
        if self.state not in ('Submitted', 'Done'):
            self.state = 'Cancel'
            cousin_sessions = self.sudo().search(
                [('inventory_count_id', '=', self.inventory_count_id.id), ('state', '!=', 'Cancel')])
            if not cousin_sessions:
                self.inventory_count_id.state = 'Draft'

        else:
            raise ValidationError(_('Cannot cancel session in Done or Submitted stage.'))

    def _compute_re_open_session(self):
        for rec in self:
            if self.state in ('Submitted', 'Done') and self.rejected_lines_count > 0:
                if rec.session_ids and rec.session_ids.filtered(lambda s: s.state != 'Cancel'):
                    rec.re_open_session_bool = False
                else:
                    rec.re_open_session_bool = True
            else:
                rec.re_open_session_bool = False

    def unlink(self):
        from_count = self.env.context.get('from_count', False)
        if from_count:
            return super(SetuInventoryCountSession, self).unlink()
        raise ValidationError(
            _('You cannot delete Inventory Count Sessions. To delete Inventory Count Sessions, delete their Inventory Count. Deleting the Inventory Count will delete all its sessions.'))

    def return_product_action(self, ids, products_type):
        action = {
            'name': self.name + ' --> ' + products_type,
            'view_mode': 'list,form',
            'res_model': 'product.product',
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', ids)]
        }
        return action

    def open_total_products(self):
        ids = self.session_line_ids.mapped('product_id').ids
        return self.return_product_action(ids, 'All Products')

    def get_product_dict(self):
        lines = self.session_line_ids
        product_dict = {product_id.id: [0, 0] for product_id in lines.mapped('product_id')}
        for line in lines:
            product_dict[line.product_id.id][0] += 1
            if line.product_scanned:
                product_dict[line.product_id.id][1] += 1
        return product_dict

    def open_products_to_be_scanned(self):
        ids = set()
        product_dict = self.get_product_dict()
        for product, scan_value in product_dict.items():
            if scan_value[0] != scan_value[1]:
                ids.add(product)
        return self.return_product_action(list(ids), 'Products To Be Scanned')

    def open_scanned_products(self):
        ids = set()
        product_dict = self.get_product_dict()
        for product, scan_value in product_dict.items():
            if scan_value[0] == scan_value[1]:
                ids.add(product)
        return self.return_product_action(list(ids), 'Scanned Products')

    def open_location(self):
        self._compute_time_taken()
        if not self.location_id and self.assigned_location_ids:
            return {
                'name': self.name + ' --> ' + 'Assigned Locations',
                'view_mode': 'list,form',
                'res_model': 'stock.location',
                'type': 'ir.actions.act_window',
                'domain': [('id', 'in', self.assigned_location_ids.ids)]
            }
        loc_id = self.location_id.id
        return {
            'name': self.name + ' --> ' + 'Location',
            'view_mode': 'form',
            'res_model': 'stock.location',
            'type': 'ir.actions.act_window',
            'res_id': loc_id
        }

    def open_inventory_count(self):
        count_id = self.inventory_count_id.id
        return {
            'name': self.name + ' --> ' + 'Inventory Count',
            'view_mode': 'form',
            'views': [(self.sudo().env.ref('setu_inventory_count_management.setu_stock_inventory_count_form_view').id,
                       'form')],
            'res_model': 'setu.stock.inventory.count',
            'type': 'ir.actions.act_window',
            'res_id': count_id
        }

    def open_user(self):
        users = self.user_ids.ids
        action = {
            'name': self.name + ' --> ' + 'Users',
            'view_mode': 'list,form',
            'res_model': 'res.users',
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', users)]
        }
        return action

    def open_approver_id(self):
        action = self.open_user()
        action.update({
            'domain': [('id', 'in', [self.approver_id.id])]
        })
        return action
