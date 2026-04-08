# -*- coding: utf-8 -*-
from datetime import datetime

from markupsafe import Markup
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from odoo.fields import Date


class StockInvCount(models.Model):
    _name = 'setu.stock.inventory.count'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _description = 'Stock Inventory Count'

    name = fields.Char(string="Name")
    inventory_count_date = fields.Date(default=fields.Date.context_today, string="Date")
    state = fields.Selection(selection=[('Rejected', 'Rejected'), ('Draft', 'Draft'),
                                        ('In Progress', 'In Progress'), ('To Be Approved', 'To Be Approved'),
                                        ('Approved', 'Approved'), ('Inventory Adjusted', 'Inventory Adjusted'),
                                        ('Cancel', 'Cancel')], default="Draft", string="State")

    # Session Configuration
    session_strategy = fields.Selection([
        ('location_wise', 'Location Wise'),
        ('product_wise', 'Product Wise')
    ], string="Session Strategy", default='location_wise', required=True)
    # Backward compatibility alias for existing code paths.
    count_strategy = fields.Selection(related='session_strategy', string="Count Strategy", readonly=False, store=True)

    product_load_type = fields.Selection([
        ('manual', 'Manual'),
        ('location_all_qty', 'Location All Qty (include zero stock)'),
        ('location_available_qty', 'Location Available Qty')
    ], string="Product Load Type", default='manual')

    product_load_type_product_wise = fields.Selection([
        ('manual', 'Manual'),
        ('user_assignment_products', 'User Assignment Products')
    ], string="Product Load Type")

    def _get_effective_product_load_type(self):
        """Return strategy-specific load type used by runtime logic."""
        self.ensure_one()
        if self.session_strategy == 'product_wise':
            return self.product_load_type_product_wise or 'manual'
        return self.product_load_type or 'manual'

    def _normalize_product_load_type_vals(self, vals):
        """Keep product load type fields consistent across UI/API/create/write."""
        normalized_vals = dict(vals)
        strategy = normalized_vals.get('session_strategy')
        if not strategy and self:
            strategy = self[0].session_strategy

        # Determine if we are creating or switching strategies to apply enforcement
        is_create = not self
        is_switching = 'session_strategy' in normalized_vals

        if strategy == 'location_wise':
            if 'product_load_type' in normalized_vals:
                if normalized_vals['product_load_type'] not in ('manual', 'location_all_qty', 'location_available_qty'):
                    normalized_vals['product_load_type'] = 'manual'
            elif is_create or is_switching:
                normalized_vals['product_load_type'] = 'manual'

            if is_create or is_switching:
                normalized_vals['product_ids'] = [(5, 0, 0)]
                normalized_vals['category_ids'] = [(5, 0, 0)]

        elif strategy == 'product_wise':
            if 'product_load_type_product_wise' in normalized_vals:
                if normalized_vals['product_load_type_product_wise'] not in ('manual', 'user_assignment_products'):
                    normalized_vals['product_load_type_product_wise'] = 'manual'
            elif is_create or is_switching:
                normalized_vals['product_load_type_product_wise'] = 'manual'

        return normalized_vals

    def _normalize_adjustment_strategy_vals(self, vals):
        """Force valid adjustment strategy based on approval scope."""
        normalized_vals = dict(vals)
        approval_scope = normalized_vals.get('approval_scope')
        if not approval_scope and self:
            approval_scope = self[0].approval_scope
        if approval_scope == 'count_level':
            normalized_vals['adjustment_strategy'] = 'count_level'
        return normalized_vals

    use_max_products = fields.Boolean(string="Limit Products per Session", default=False)
    max_products_per_session = fields.Integer(string="Max Products per Session", default=0)
    use_barcode_scanner = fields.Boolean(string="Use barcode scanner", default=False)
    barcode_scan = fields.Boolean(related='use_barcode_scanner', string="Barcode Scan", readonly=False)

    # Product/Category Selection
    product_ids = fields.Many2many('product.product', string="Products")
    category_ids = fields.Many2many('product.category', string="Categories")

    # Approval Flow
    approval_scope = fields.Selection([
        ('session_level', 'Session Level'),
        ('count_level', 'Count Level')
    ], string="Approval Scope", default='session_level', required=True)

    adjustment_strategy = fields.Selection([
        ('count_level', 'Count Level'),
        ('session_level', 'Session Level')
    ], string="Adjustment Strategy", default='count_level', required=True)

    approver_id = fields.Many2one(comodel_name="res.users", string="Approver")
    approver_ids = fields.Many2many(comodel_name="res.users", compute='_compute_approver_id',
                                    string="Approvers")

    # Core relations
    warehouse_id = fields.Many2one(comodel_name="stock.warehouse", string="Warehouse")
    location_id = fields.Many2one('stock.location', string="Location")
    company_id = fields.Many2one(comodel_name="res.company", related="warehouse_id.company_id", string="Company",
                                 store=True)
    currency_id = fields.Many2one(related='company_id.currency_id', string="Currency", store=True)
    user_id = fields.Many2one(comodel_name="res.users", default=lambda self: self.env.user.id, string="User")
    planner_id = fields.Many2one(comodel_name="setu.stock.inventory.count.planner", string='Planner', readonly=True)
    count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", readonly=True, copy=False, string="Count")

    # One2many relations
    unscanned_product_lines_ids = fields.One2many('setu.unscanned.product.lines', 'inventory_count_id',
                                                  string="Unscanned Products")
    line_ids = fields.One2many('setu.stock.inventory.count.line', 'inventory_count_id', string="Inventory Count Lines")
    session_ids = fields.One2many('setu.inventory.count.session', 'inventory_count_id', string="Sessions Details")
    inventory_adj_ids = fields.One2many('setu.stock.inventory', 'inventory_count_id',
                                        string="Inventory Adjustment Details")
    count_ids = fields.One2many('setu.stock.inventory.count', 'count_id', copy=False, string='Counts')
    stock_move_line_ids = fields.One2many('stock.move.line', 'count_id', string="Move Line")

    # Compute fields for UI/Logic
    non_cancelled_session = fields.Boolean(compute="_compute_non_cancelled_session", string="Non cancelled session")
    start_inventory_bool = fields.Boolean(compute="_compute_start_inventory_bool", string="Is Start Inventory")
    create_count_bool = fields.Boolean(compute="_compute_create_count_bool", string="Create Count")
    create_session_bool = fields.Boolean(compute="_compute_create_session_bool", string="Is Create Session")
    count_session_ids = fields.Integer(compute="_compute_count_session_ids", string="Session Count")
    completed_session_count = fields.Integer(compute="_compute_session_progress", string="Completed Sessions")
    session_progress_percent = fields.Float(compute="_compute_session_progress", string="Session Progress (%)")
    re_count_ids = fields.Integer(compute="_compute_count_ids", string="Re-Count")
    rejected_lines_count = fields.Integer(compute="_compute_rejected_lines_count", string="Rejected lines count")
    discrepancy_lines_count = fields.Integer(
        compute="_compute_discrepancy_lines_count",
        string="Discrepancy Lines",
    )
    discrepancy_ratio = fields.Float(compute="_compute_discrepancy_ratio", string="Discrepancy Ratio", store=True)
    total_discrepancy_value = fields.Float(compute="_compute_total_discrepancy_value", string="Total Discrepancy Value")
    user_mistake_ratio = fields.Float(compute="_compute_user_mistake_ratio", string="User Mistake Ration", store=True)
    all_count_lines_reviewed = fields.Boolean(
        compute="_compute_all_count_lines_reviewed",
        string="All Count Lines Reviewed",
    )

    has_multi_session = fields.Boolean(
        compute="_compute_has_multi_session",
        string="Has Multi Session",
        help="True if this count has any multi-session (is_multi_session) sessions."
    )

    @api.onchange('use_max_products')
    def _onchange_use_max_products(self):
        if not self.use_max_products:
            self.max_products_per_session = 0

    @api.onchange('session_strategy')
    def _onchange_session_strategy(self):
        if self.session_strategy == 'location_wise':
            self.product_ids = [(5, 0, 0)]
            self.category_ids = [(5, 0, 0)]
            if self.product_load_type not in ('manual', 'location_all_qty', 'location_available_qty'):
                self.product_load_type = 'manual'
        if self.session_strategy == 'product_wise':
            if self.product_load_type_product_wise not in ('manual', 'user_assignment_products'):
                self.product_load_type_product_wise = 'manual'

    @api.onchange('approval_scope')
    def _onchange_approval_scope(self):
        if self.approval_scope == 'count_level':
            self.adjustment_strategy = 'count_level'

    @api.onchange('product_load_type_product_wise')
    def _onchange_product_load_type_product_wise(self):
        if self.session_strategy == 'product_wise' and self.product_load_type_product_wise not in (
                'manual', 'user_assignment_products'
        ):
            self.product_load_type_product_wise = 'manual'

    @api.onchange('product_load_type')
    def _onchange_product_load_type(self):
        if self.product_load_type not in ('manual', 'location_all_qty', 'location_available_qty'):
            self.product_load_type = 'manual'

    @api.constrains('inventory_count_date')
    def _check_inventory_count_date(self):
        if self.inventory_count_date < Date.today():
            raise ValidationError(_('You cannot select date from past.'))

    @api.constrains('session_strategy', 'product_load_type', 'product_load_type_product_wise')
    def _check_product_load_type_by_strategy(self):
        for rec in self:
            if rec.session_strategy == 'location_wise' and rec.product_load_type not in (
                    'manual', 'location_all_qty', 'location_available_qty'
            ):
                raise ValidationError(
                    _("For Location Wise session strategy, Product Load Type must be Manual, Location All Qty, or "
                      "Location Available Qty.")
                )
            if rec.session_strategy == 'product_wise' and rec.product_load_type_product_wise not in (
                    'manual', 'user_assignment_products'
            ):
                raise ValidationError(
                    _("For Product Wise session strategy, Product Load Type must be Manual or User Assignment "
                      "Products.")
                )

    @api.constrains('approval_scope', 'adjustment_strategy')
    def _check_adjustment_strategy_by_approval_scope(self):
        for rec in self:
            if rec.approval_scope == 'count_level' and rec.adjustment_strategy != 'count_level':
                raise ValidationError(_("For Count Level approval, Adjustment Strategy must be Count Level."))

    @api.depends('session_ids.state')
    def _compute_non_cancelled_session(self):
        for rec in self:
            if rec.session_ids and rec.session_ids.filtered(lambda s: s.state != 'Cancel'):
                rec.non_cancelled_session = True
            else:
                rec.non_cancelled_session = False

    def _compute_has_multi_session(self):
        """Compute if this count has any multi-session (is_multi_session) sessions."""
        for rec in self:
            rec.has_multi_session = bool(rec.session_ids.filtered(lambda s: s.is_multi_session))

    def complete_counting(self):
        if self.session_ids.filtered(lambda s: s.state not in ('Cancel', 'Done')):
            raise ValidationError(_(
                "Please submit and validate all the incomplete sessions before completing the counting."))
        if self.approval_scope == 'session_level' and self.adjustment_strategy == 'session_level':
            self.state = 'Approved'
        else:
            self.state = 'To Be Approved'

    def _compute_discrepancy_ratio(self):
        for rec in self:
            lines = rec.line_ids
            if not lines:
                rec.discrepancy_ratio = 0
                continue

            product_map = {}

            for line in lines:
                pid = line.product_id.id
                product_map[pid] = (
                        product_map.get(pid, False)
                        or line.is_discrepancy_found
                )

            total = len(product_map)
            rec.discrepancy_ratio = (
                sum(product_map.values()) * 100 / total
                if total else 0
            )

    def action_open_discrepancy_lines(self):
        discrepancy_lines = self.line_ids.filtered(lambda l: l.is_discrepancy_found)
        ids = discrepancy_lines.ids if discrepancy_lines else []
        view_id = self.sudo().env.ref('setu_inventory_count_management.setu_stock_inventory_count_line_tree_view')
        return {'name': 'Discrepancy Lines',
                'view_mode': 'list',
                'view_id': view_id.id,
                'res_model': 'setu.stock.inventory.count.line',
                'type': 'ir.actions.act_window',
                'domain': [('id', 'in', ids)]}

    @api.depends('line_ids.user_calculation_mistake', 'line_ids.product_id')
    def _compute_user_mistake_ratio(self):
        for rec in self:
            if not rec.line_ids:
                rec.user_mistake_ratio = 0.0
                continue

            product_map = {}

            # single pass
            for line in rec.line_ids:
                pid = line.product_id.id
                product_map[pid] = (
                        product_map.get(pid, False)
                        or line.user_calculation_mistake
                )

            total_products = len(product_map)
            mistake_products = sum(product_map.values())

            rec.user_mistake_ratio = (
                mistake_products * 100.0 / total_products
                if total_products else 0.0
            )

    def approve_all_lines(self):
        message = "Are you sure that you want to Approve all session lines? (Even rejected lines will also be approved)"
        wiz = self.env['setu.inventory.warning.message.wizard'].create({'message': message})
        view_id = self.sudo().env.ref(
            'setu_inventory_count_management.setu_inventory_warning_approve_message_wizard_form_view')

        return {'name': 'Warning!!!',
                'view_mode': 'form',
                'view_id': view_id.id,
                'res_model': 'setu.inventory.warning.message.wizard',
                'type': 'ir.actions.act_window',
                'res_id': wiz.id,
                'target': 'new'}

    def reject_all_lines(self):
        message = "Are you sure that you want to Reject all session lines? (Even approved lines will also be rejected)"
        wiz = self.env['setu.inventory.warning.message.wizard'].create({'message': message})
        view_id = self.sudo().env.ref(
            'setu_inventory_count_management.setu_inventory_count_warning_reject_message_wizard_form_view')

        return {'name': 'Warning!!!',
                'view_mode': 'form',
                'view_id': view_id.id,
                'res_model': 'setu.inventory.warning.message.wizard',
                'type': 'ir.actions.act_window',
                'res_id': wiz.id,
                'target': 'new'}

    def action_open_count_validate_wizard(self):
        self.ensure_one()
        if self.state != 'To Be Approved':
            raise ValidationError(_("You can validate only when the count is in 'To Be Approved' state."))
        message = _("Are you sure you want to validate this Inventory Count?")
        wiz = self.env['setu.inventory.warning.message.wizard'].create({'message': message})
        view_id = self.sudo().env.ref(
            'setu_inventory_count_management.setu_inventory_count_validate_message_wizard_form_view')
        return {
            'name': 'Warning!!!',
            'view_mode': 'form',
            'view_id': view_id.id,
            'res_model': 'setu.inventory.warning.message.wizard',
            'type': 'ir.actions.act_window',
            'res_id': wiz.id,
            'target': 'new',
        }

    def action_open_user_mistake_lines(self):
        user_mistake_lines = self.line_ids.filtered(lambda l: l.user_calculation_mistake)
        ids = user_mistake_lines.ids if user_mistake_lines else []
        view_id = self.sudo().env.ref('setu_inventory_count_management.setu_stock_inventory_count_line_tree_view')
        return {'name': 'User Calculation Mistake Lines',
                'view_mode': 'list',
                'view_id': view_id.id,
                'res_model': 'setu.stock.inventory.count.line',
                'type': 'ir.actions.act_window',
                'domain': [('id', 'in', ids)]}

    def reset_to_draft(self):
        self.state = 'Draft'
        if not self.count_id:
            self.line_ids.unlink()
        else:
            self.line_ids.state = 'Pending Review'
            self.line_ids.counted_qty = 0

    def cancel(self):
        sessions = self.session_ids.filtered(lambda s: s.state != 'Cancel')
        if sessions:
            sessions_str = "\n".join(set(sessions.mapped('name')))
            raise ValidationError(
                _("This Inventory Count cannot be cancelled because few of the sessions are already running, "
                  "\n%s" % sessions_str))
        if self.state == 'Draft':
            self.state = 'Cancel'
            for session in self.session_ids:
                session.state = 'Cancel'
            for line in self.line_ids:
                line.qty_in_stock = line.theoretical_qty

    def _compute_rejected_lines_count(self):
        for rec in self:
            rejected_lines = rec.line_ids.filtered(lambda l: l.state == 'Reject')
            rec.rejected_lines_count = len(rejected_lines) if rejected_lines else 0

    @api.depends('line_ids.is_discrepancy_found', 'line_ids.state')
    def _compute_discrepancy_lines_count(self):
        for rec in self:
            rec.discrepancy_lines_count = len(
                rec.line_ids.filtered(lambda l: l.is_discrepancy_found and l.state != 'Reject')
            )

    def _compute_create_count_bool(self):
        for rec in self:
            if rec.state in ('Approved', 'Inventory Adjusted',
                             'Done') and rec.rejected_lines_count > 0 and not rec.count_ids:
                rec.create_count_bool = True
            else:
                rec.create_count_bool = False

    def _compute_create_session_bool(self):
        for rec in self:
            # Keep Create Session available until counting is completed.
            rec.create_session_bool = rec.state in ('Draft', 'In Progress')

    @api.depends('session_ids.state')
    def _compute_start_inventory_bool(self):
        for rec in self:
            rec.start_inventory_bool = True
            if rec.inventory_adj_ids and rec.inventory_adj_ids.filtered(lambda a: a.state not in ('cancel')):
                rec.start_inventory_bool = False
                continue
            adj_lines = rec.line_ids.filtered(lambda l: l.is_discrepancy_found and l.state == 'Approve')
            if not adj_lines:
                rec.start_inventory_bool = False

    @api.depends('session_ids.state')
    def _compute_count_session_ids(self):
        for rec in self:
            session = rec.session_ids.filtered(lambda l: l.state not in ('Cancel'))
            rec.count_session_ids = len(session)

    @api.depends('line_ids.state')
    def _compute_all_count_lines_reviewed(self):
        for rec in self:
            if rec.approval_scope != 'count_level':
                rec.all_count_lines_reviewed = False
                continue
            lines = rec.line_ids
            if not lines:
                rec.all_count_lines_reviewed = False
                continue
            rec.all_count_lines_reviewed = all(line.state in ('Approve', 'Reject') for line in lines)

    @api.depends('session_ids.state')
    def _compute_session_progress(self):
        for rec in self:
            sessions = rec.session_ids.filtered(lambda s: s.state != 'Cancel')
            total_sessions = len(sessions)
            completed_sessions = len(sessions.filtered(lambda s: s.state in ('Done', 'Submitted')))
            rec.completed_session_count = completed_sessions
            rec.session_progress_percent = (completed_sessions * 100.0 / total_sessions) if total_sessions else 0.0

    @api.depends('line_ids.discrepancy_value', 'line_ids.is_discrepancy_found', 'line_ids.state', 'line_ids.difference_qty')
    def _compute_total_discrepancy_value(self):
        for rec in self:
            # Inventory loss value should exclude rejected lines and count only negative discrepancies.
            loss_lines = rec.line_ids.filtered(
                lambda l: l.state != 'Reject' and l.is_discrepancy_found and l.difference_qty < 0
            )
            rec.total_discrepancy_value = sum(abs(val) for val in loss_lines.mapped('discrepancy_value'))

    def _compute_count_ids(self):
        for rec in self:
            rec.re_count_ids = len(rec.count_ids)

    def get_products_from_setu_reports(self):
        action = \
            self.sudo().env.ref('setu_inventory_count_management.get_products_from_setu_reports_act_window').read()[0]
        wizard = self.env['get.products.from.adv.inv.rep.wizard'].create({})
        wizard.warehouse_ids = self.warehouse_id
        action.update({'res_id': wizard.id})
        return action

    def action_open_sessions(self):
        sessions_to_open = self.session_ids
        action = self.env['ir.actions.act_window']._for_xml_id(
            'setu_inventory_count_management.inventory_count_session_act_window')
        if len(sessions_to_open) > 1:
            action['domain'] = [('id', 'in', sessions_to_open.ids)]
        elif len(sessions_to_open) == 1:
            action['views'] = [
                (self.sudo().env.ref('setu_inventory_count_management.inventory_count_session_form_view').id, 'form')]
            action['res_id'] = sessions_to_open.ids[0]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    def action_open_counts(self):
        count_to_open = self.count_ids
        action = self.sudo().env.ref('setu_inventory_count_management.new_inventory_count_act_window').read()[0]
        if len(count_to_open) > 1:
            action['domain'] = [('id', 'in', count_to_open.ids)]
        elif len(count_to_open) == 1:
            action['views'] = [(self.sudo().env.ref(
                'setu_inventory_count_management.setu_stock_inventory_count_form_view').id, 'form')]
            action['res_id'] = count_to_open.ids[0]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    def action_open_inventory_adj(self):
        inventory_adjs = self.inventory_adj_ids
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

    @api.model_create_multi
    def create(self, vals_list):
        current_user = self.env.user
        can_self_assign_as_approver = current_user.has_group(
            'setu_inventory_count_management.group_setu_inventory_count_approver'
        ) or current_user.has_group(
            'setu_inventory_count_management.group_setu_inventory_count_manager'
        )
        for vals in vals_list:
            vals.update(self._normalize_product_load_type_vals(vals))
            vals.update(self._normalize_adjustment_strategy_vals(vals))
            if not vals.get('approver_id') and can_self_assign_as_approver:
                vals['approver_id'] = current_user.id
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('setu.inventory.count.seq') or _('New')
        return super(StockInvCount, self).create(vals_list)

    def write(self, vals):
        normalized_vals = self._normalize_product_load_type_vals(vals)
        normalized_vals = self._normalize_adjustment_strategy_vals(normalized_vals)
        return super(StockInvCount, self).write(normalized_vals)

    def action_generate_sessions(self):
        self.ensure_one()
        if not self.session_strategy:
            raise ValidationError(_("Please select a Session Strategy."))
        view_id = self.env.ref('setu_inventory_count_management.setu_inventory_session_creator_form_view')
        return {
            'name': _('Create Session'),
            'type': 'ir.actions.act_window',
            'res_model': 'setu.inventory.session.creator',
            'view_mode': 'form',
            'view_id': view_id.id,
            'target': 'new',
            'context': {
                'default_inventory_count_id': self.id,
                'default_session_strategy': self.session_strategy,
                'default_product_load_type': self._get_effective_product_load_type(),
                'default_company_id': self.company_id.id,
                'default_warehouse_id': self.warehouse_id.id,
                'default_parent_count_id': self.id
            }
        }

    def _get_products_to_count(self):
        """Returns a list of products (and locations if location_wise) to be counted."""
        domain = []
        load_type = self._get_effective_product_load_type()
        if load_type == 'user_assignment_products':
            if self.product_ids:
                domain.append(('id', 'in', self.product_ids.ids))
            if self.category_ids:
                domain.append(('categ_id', 'child_of', self.category_ids.ids))

        # If manual, we expect product_ids to be filled
        if load_type == 'manual':
            if not self.product_ids:
                return []
            domain.append(('id', 'in', self.product_ids.ids))

        if load_type in ['location_all_qty', 'location_available_qty']:
            # Load from location
            loc_domain = [('location_id', 'child_of', self.location_id.id)]
            if load_type == 'location_available_qty':
                loc_domain.append(('quantity', '>', 0))

            quants = self.env['stock.quant'].search(loc_domain)
            products = quants.mapped('product_id')
            # For location_wise, we might want to keep the quant info
            if self.session_strategy == 'location_wise':
                return quants
            return products

        return self.env['product.product'].search(domain)

    def _generate_location_wise_sessions(self, items):
        """Generates sessions grouped by location."""
        # items could be quants or products depending on load type
        if self._get_effective_product_load_type() in ['location_all_qty', 'location_available_qty']:
            # items are quants
            location_groups = {}
            for quant in items:
                if quant.location_id not in location_groups:
                    location_groups[quant.location_id] = []
                location_groups[quant.location_id].append(quant.product_id)

            for location, products in location_groups.items():
                self._create_sessions_for_location(location, products)
        else:
            # items are products, use the main location
            if not self.location_id:
                raise ValidationError(_("Location is required for Location Wise strategy."))
            self._create_sessions_for_location(self.location_id, items)

    def _create_sessions_for_location(self, location, products):
        """Create sessions per location with optimized batch creation."""

        Session = self.env['setu.inventory.count.session']
        SessionLine = self.env['setu.inventory.count.session.line']

        max_p = (
            self.max_products_per_session
            if self.use_max_products and self.max_products_per_session > 0
            else len(products)
        )

        for i in range(0, len(products), max_p):
            chunk = products[i:i + max_p]

            # Create session
            session = Session.create({
                'inventory_count_id': self.id,
                'location_id': location.id,
                'assigned_location_ids': [(6, 0, [location.id])],
                'warehouse_id': self.warehouse_id.id,
                'use_barcode_scanner': self.barcode_scan,
            })

            # Batch create session lines (single query)
            line_vals = [
                {
                    'session_id': session.id,
                    'product_id': prod.id,
                    'location_id': location.id,
                }
                for prod in chunk
            ]

            SessionLine.create(line_vals)

    def _generate_product_wise_sessions(self, products):
        """Generate sessions distributing products across them (optimized)."""

        Session = self.env['setu.inventory.count.session']
        SessionLine = self.env['setu.inventory.count.session.line']

        max_p = (
            self.max_products_per_session
            if self.use_max_products and self.max_products_per_session > 0
            else len(products)
        )

        for i in range(0, len(products), max_p):
            chunk = products[i:i + max_p]

            # Create session (single query)
            session = Session.create({
                'inventory_count_id': self.id,
                'warehouse_id': self.warehouse_id.id,
                'use_barcode_scanner': self.barcode_scan,
            })

            # Prepare batch values
            line_vals = [
                {
                    'session_id': session.id,
                    'product_id': prod.id,
                }
                for prod in chunk
            ]

            # Batch create (ONE query instead of N queries)
            SessionLine.create(line_vals)

    def _get_active_sessions(self):
        self.ensure_one()
        return self.session_ids.filtered(lambda s: s.state != 'Cancel')

    def _all_sessions_completed_for_count_approval(self):
        self.ensure_one()
        sessions = self._get_active_sessions()
        # Count can be finalized only when every active session is fully validated.
        return bool(sessions) and all(session.state == 'Done' for session in sessions)

    def _session_has_variance(self, session):
        session.ensure_one()
        return any(
            line.is_discrepancy_found
            or line.state == 'Reject'
            or line.scanned_qty != line.theoretical_qty
            for line in session.session_line_ids
        )

    def _create_revision_session(self, session):
        self.ensure_one()
        session.ensure_one()
        revision = session.copy({
            'state': 'Draft',
            'current_state': 'Created',
            'is_revision': True,
            'revision_of_id': session.id,
            'session_submit_date': False,
            'session_start_date': False,
            'session_end_date': False,
            'current_scanning_location_id': False,
            'current_scanning_product_id': False,
            'current_scanning_lot_id': False,
            'session_line_ids': [],
        })
        lines_to_copy = session.session_line_ids.filtered(
            lambda line: line.state == 'Reject'
        )
        if not lines_to_copy:
            return revision
        for line in lines_to_copy:
            line.copy({
                'session_id': revision.id,
                'scanned_qty': 0,
                'state': 'Pending Review',
                'product_scanned': False,
            })
        return revision

    def action_submit_session(self, session):
        """Centralized session submission state transition."""
        self.ensure_one()
        session.ensure_one()
        if session.inventory_count_id != self:
            raise ValidationError(_("The session does not belong to this count."))

        self.state = 'In Progress'
        if self.approval_scope == 'session_level':
            session.write({'state': 'Submitted'})
            return True

        # For count-level approval, session is considered completed once user submits.
        session.write({'state': 'Done'})
        return True

    def action_approve(self, session=False):
        self.ensure_one()
        if session:
            session.ensure_one()
            if self.approval_scope != 'session_level':
                return True

            if self.adjustment_strategy == 'session_level':
                # Adjust only lines from THIS session that were approved
                self.create_inventory_adj(session=session)
            return True

        if self.approval_scope == 'session_level':
            if self.state != 'To Be Approved':
                raise ValidationError(_("You can validate only when the count is in 'To Be Approved' state."))
            self.write({'state': 'Approved'})
            return True

        if self.approval_scope != 'count_level':
            return True
        sessions_to_finalize = self._get_active_sessions().filtered(lambda s: s.state in ('Submitted', 'Done'))
        sessions_to_finalize.write({'state': 'Done'})
        self.write({'state': 'Approved'})
        session_model = self.env['setu.inventory.count.session']
        for count_line in self.line_ids:
            session_model._set_calculation_mistake_value(
                count_line,
                count_line.counted_qty,
            )

        if self.adjustment_strategy == 'count_level':
            self.create_inventory_adj()
        return True

    def _create_re_count(self, rejected_lines):
        """Creates a new count for rejected lines."""
        self.ensure_one()
        new_count = self.copy({
            # Fresh document number; link to parent via count_id (shown in form / kanban tag).
            'name': _('New'),
            'state': 'Draft',
            'count_id': self.id,
            'line_ids': [],
            'session_ids': [],
            'inventory_count_date': datetime.now().date(),

        })
        if self.session_strategy == 'product_wise':
            new_count.write({
                'product_ids': [(6, 0, rejected_lines.mapped('product_id.id'))],
                'category_ids': [(5, 0, 0)],
            })
        elif self.session_strategy == 'location_wise':
            rejected_locations = rejected_lines.mapped('location_id')
            new_count.write({
                'location_id': rejected_locations[:1].id if rejected_locations else self.location_id.id,
            })
        return new_count

    def action_create_re_count(self):
        self.ensure_one()
        rejected_lines = self.line_ids.filtered(lambda l: l.state == 'Reject')
        if not rejected_lines:
            raise ValidationError(_("No rejected count lines found to create a re-count."))
        if self.count_ids:
            return self.action_open_counts()

        new_count = self._create_re_count(rejected_lines)
        rejected_users = rejected_lines.mapped('user_ids')
        rejected_locations = rejected_lines.mapped('location_id')

        session_vals = {
            'inventory_count_id': new_count.id,
            'warehouse_id': new_count.warehouse_id.id,
            'use_barcode_scanner': new_count.use_barcode_scanner,
            'user_ids': [(6, 0, rejected_users.ids)],
        }
        if new_count.session_strategy == 'location_wise':
            session_vals.update({
                'location_id': rejected_locations[:1].id if rejected_locations else new_count.location_id.id,
                'assigned_location_ids': [(6, 0, rejected_locations.ids)],
            })

        new_session = self.env['setu.inventory.count.session'].create(session_vals)
        session_line_vals = []
        for line in rejected_lines:
            session_line_vals.append((0, 0, {
                'inventory_count_id': new_count.id,
                'product_id': line.product_id.id,
                'location_id': line.location_id.id if line.location_id else False,
                'lot_id': line.lot_id.id if line.lot_id else False,
                'theoretical_qty': line.qty_in_stock,
                'is_multi_session': False,
            }))
        if session_line_vals:
            new_session.write({'session_line_ids': session_line_vals})
        return new_count.action_open_sessions()

    def action_reject(self, session=False):
        self.ensure_one()
        if session:
            session.ensure_one()
            if self.approval_scope != 'session_level':
                return True
            # Case: Session level rejection -> generate re-session
            self._create_revision_session(session)
            return True

        if self.approval_scope != 'count_level':
            return True

        # Case: Count level rejection -> currently set to create revision for ALL sessions?
        # Requirement: "re-count will be generated for rejected lines"
        # Since this button might reject the WHOLE count, we can treat all lines as rejected?
        # Or just use finalize logic if they already marked lines as rejected.
        rejected_lines = self.line_ids.filtered(lambda l: l.state == 'Reject')
        if not rejected_lines:
            # If no lines were rejected manually, maybe reject all?
            rejected_lines = self.line_ids

        self._create_re_count(rejected_lines)
        self.write({'state': 'Cancel'})
        return True

    def unlink(self):
        for count in self:
            if count.state != 'Draft':
                raise ValidationError(
                    _(f'You cannot delete the Inventory Count once it is in {count.state} state.'))
        if self.session_ids:
            self.session_ids.with_context(from_count=True).unlink()
        return super(StockInvCount, self).unlink()

    def create_inventory_adj(self, session=False):
        """Creates Odoo inventory adjustments for lines with discrepancies."""
        self.ensure_one()

        # Determine which lines to adjust
        if session:
            # Only adjust lines corresponding to this session's approved lines
            approved_session_lines = session.session_line_ids.filtered(lambda sl: sl.state == 'Approve')
            products = approved_session_lines.mapped('product_id')
            locations = approved_session_lines.mapped('location_id')
            lines_to_adjust = self.line_ids.filtered(
                lambda l: l.state == 'Approve' and l.is_discrepancy_found
                          and l.product_id in products and l.location_id in locations
            )
        else:
            # Adjust all approved lines with discrepancies
            lines_to_adjust = self.line_ids.filtered(lambda l: l.state == 'Approve' and l.is_discrepancy_found)

        if lines_to_adjust:
            self._create_inventory_adj(lines_to_adjust, session=session)
            try:
                self.message_post(
                    body=Markup(
                        "<div style='color:green; margin:10px 30px;;'>&bull; %s <strong>%s</strong> %s</div>") % (
                             _('Discrepancy found.'),
                             _('Inventory Adjustment'),
                             _('is created.')
                         ))
            except Exception as e:
                pass
        else:
            try:
                self.message_post(
                    body=Markup(
                        "<div style='color:blue; margin:10px 30px;;'>&bull; %s <strong>%s</strong> %s</div>") % (
                             _('No discrepancies to adjust.'),
                             _('Inventory Adjustment'),
                             _('skipped.')
                         ))
            except Exception as e:
                pass
        return True

    def get_all_counts(self):
        self.ensure_one()
        current = self
        count_ids = set()
        while current:
            count_ids.add(current.id)
            current = current.count_id
        return count_ids

    def _create_inventory_adj(self, count_lines, session=False):
        if count_lines:
            adjustment_location_id = self.location_id.id or count_lines[:1].location_id.id
            if not adjustment_location_id:
                raise ValidationError(
                    _("Cannot create Inventory Adjustment because no location is available on the count or discrepancy lines.")
                )
            lines = []
            for l in count_lines:
                if l.product_id.tracking != 'serial':
                    lines.append((
                        0, 0, {'product_id': l.product_id.id, 'product_uom_id': l.product_id.uom_id.id,
                               'location_id': l.location_id.id, 'product_qty': l.counted_qty,
                               'prod_lot_id': l.lot_id.id if l.lot_id else False,
                               'theoretical_qty': l.qty_in_stock}))
                else:
                    if l.serial_number_ids:
                        quants = self.env['stock.quant'].sudo().search([
                            ('location_id', '=', l.location_id.id),
                            ('product_id', '=', l.product_id.id),
                            ('lot_id', 'in', l.serial_number_ids.ids)
                        ])
                        existing_lots = quants.mapped('lot_id')
                        settlement_serial_ids = l.serial_number_ids - existing_lots

                        # We already know these lots don't exist in the location, no need to search again
                        for s in settlement_serial_ids:
                            lines.append((0, 0, {
                                'product_id': l.product_id.id,
                                'product_uom_id': l.product_id.uom_id.id,
                                'location_id': l.location_id.id,
                                'product_qty': 1,
                                'serial_number_ids': [(6, 0, s.ids)],
                                'theoretical_qty': 0
                            }))
                    if l.not_found_serial_number_ids:
                        for m in l.not_found_serial_number_ids:
                            lot_exists = self.env['stock.quant'].sudo().search(
                                [('location_id', '=', l.location_id.id),
                                 ('lot_id', '=', m.id),
                                 ('quantity', '>', 0),
                                 ('product_id', '=', l.product_id.id)]).mapped('lot_id')
                            lines.append((
                                0, 0, {'product_id': l.product_id.id, 'product_uom_id': l.product_id.uom_id.id,
                                       'location_id': l.location_id.id, 'product_qty': 0,
                                       'prod_lot_id': l.lot_id.id if l.lot_id else False,
                                       'serial_number_ids': [(6, 0, m.ids)],
                                       'theoretical_qty': m.product_qty if lot_exists else 0}))

            adj = self.env['setu.stock.inventory'].create({
                'location_id': adjustment_location_id,
                'name': 'ADJ - ' + self.name,
                'inventory_count_id': self.id,
                'session_id': session.id if session else False,
                'partner_id': self.approver_id.id,
                'date': self.inventory_count_date,
                'line_ids': lines
            })
            adj.inventory_count_id = self
            adj.action_start()
            adj.product_ids = count_lines.mapped('product_id')

    @api.depends('warehouse_id')
    def _compute_warehouse_id(self):
        for record in self:
            if record.warehouse_id:
                warehouse_id = record.warehouse_id
                view_location_id = record.warehouse_id.view_location_id
                locations = self.env['stock.location'].sudo().search(
                    [('warehouse_id', '=', warehouse_id.id), ('usage', '=', 'internal')])
                record.locations_ids = locations if locations else False
            else:
                locations = record.env['stock.location'].sudo().search(
                    [('usage', '=', 'internal'), ('company_id', 'in', self.env.companies.ids)])
                record.locations_ids = locations

    @api.onchange('location_id')
    def onchange_location_id(self):
        if self.location_id:
            domain = [('view_location_id', 'parent_of', self.location_id.id)]
            wh = self.env['stock.warehouse'].search(domain)
            if wh:
                self.warehouse_id = wh

    @api.onchange('warehouse_id')
    def onchange_warehouse_id(self):
        if self.warehouse_id:
            return {'value': {
                'location_id': self.warehouse_id.lot_stock_id.id}}

    @api.depends('approver_id')
    def _compute_approver_id(self):
        for record in self:
            approver_group = self.env.ref('setu_inventory_count_management.group_setu_inventory_count_approver')
            admin_group = self.env.ref('setu_inventory_count_management.group_setu_inventory_count_manager')
            users = self.env['res.users'].search([
                '|',
                ('groups_id', 'in', [approver_group.id]),
                ('groups_id', 'in', [admin_group.id]),
                ('company_ids', 'in', self.env.companies.ids),
            ])
            ids = users.ids if users else []
            record.approver_ids = ids

    @api.model
    def get_counted_products(self, domain, user_ids=None):
        domain = domain + [('state', 'in', ['Approved', 'Inventory Adjusted'])]
        counts = self.search(domain)
        line_domain = [('inventory_count_id', 'in', counts.ids)]
        if user_ids:
            line_domain.append(('user_ids', 'in', user_ids))
        count_lines = self.env['setu.stock.inventory.count.line'].search(line_domain)
        return count_lines.mapped('product_id').ids

    def check_unscanned(self):
        if self.session_strategy == 'product_wise':
            return True
        self.ensure_one()
        locations = self.line_ids.mapped('location_id')
        if not locations:
            locations = self.session_ids.mapped('session_line_ids.location_id')
        if not locations:
            locations = self.session_ids.mapped('assigned_location_ids')
        if not locations and self.location_id:
            locations = self.location_id + self.location_id.child_ids
        if not locations and self.warehouse_id and self.warehouse_id.lot_stock_id:
            locations = self.warehouse_id.lot_stock_id + self.warehouse_id.lot_stock_id.child_ids
        if not locations:
            raise ValidationError(
                _('No locations found from count lines. Please create sessions and scan products first.'))
        quants = self.env['stock.quant'].search([('location_id', 'in', locations.ids)])
        # Cache lists outside the loop to avoid re-evaluation
        counted_product_ids = set(self.line_ids.mapped('product_id.id'))
        counted_lot_ids = set(self.line_ids.mapped('lot_id.id') + self.line_ids.mapped('serial_number_ids.id'))

        quants_to_add = quants.filtered(
            lambda x: x.product_id.id not in counted_product_ids or
                      (x.product_id.id in counted_product_ids and x.lot_id and x.lot_id.id not in counted_lot_ids)
        )

        # Bulk create
        vals_list = [{
            'inventory_count_id': self.id,
            'product_id': q.product_id.id,
            'lot_id': q.lot_id.id if q.lot_id else False,
            'location_id': q.location_id.id,
            'quantity': q.quantity
        } for q in quants_to_add]

        if vals_list:
            self.env['setu.unscanned.product.lines'].create(vals_list)

    def create_unscanned_product_lines(self, quant):
        new_line = self.env['setu.unscanned.product.lines'].create({
            'inventory_count_id': self.id,
            'product_id': quant.product_id.id,
            'lot_id': quant.lot_id.id if quant.lot_id else False,
            'location_id': quant.location_id.id,
            'quantity': quant.quantity
        })

    def action_open_unscanned_products(self):
        view_id = self.sudo().env.ref('setu_inventory_count_management.setu_unscanned_product_lines')
        return {'name': 'Unscanned Products',
                'view_mode': 'list',
                'view_id': view_id.id,
                'res_model': 'setu.unscanned.product.lines',
                'type': 'ir.actions.act_window',
                'domain': [('inventory_count_id', '=', self.id)]}
