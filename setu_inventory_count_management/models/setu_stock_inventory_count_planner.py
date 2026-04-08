# -*- coding: utf-8 -*-
from datetime import datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta
import logging

from odoo import fields, models, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StockInvCountPlanner(models.Model):
    _name = 'setu.stock.inventory.count.planner'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _description = 'Stock Inventory Count Planner'

    use_barcode_scanner = fields.Boolean(default=False, string="Use barcode scanner")
    active = fields.Boolean(default=True, string="Active")

    name = fields.Char(string="Name", required=True)

    # Frequency Management
    frequency_type = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('custom', 'Custom Days')
    ], string="Frequency", default='daily', required=True)
    planing_frequency = fields.Integer(string="Custom Frequency Days",
                                       help="Number of days for custom frequency")
    past_history_days = fields.Integer(string="Past History Days", default="365")

    inventory_count_date = fields.Date(default=fields.Date.today, string="Date")

    # Execution DateTime Configuration (combined date + time)
    start_from = fields.Datetime(string="Start From",
                                 default=lambda self: fields.Datetime.now().replace(hour=9, minute=0),
                                 help="Start datetime for the planner execution")
    next_execution_datetime = fields.Datetime(string="Next Execution DateTime",
                                              compute='_compute_next_execution_datetime',
                                              store=True, readonly=False,
                                              help="Next execution datetime (date + time)")
    previous_execution_datetime = fields.Datetime(string="Previous Execution DateTime", readonly=True)

    # Planner Type
    planner_type = fields.Selection([
        ('location_wise', 'Location-wise Planner'),
        ('product_wise', 'Product-wise Planner')
    ], string="Planner Type", default='location_wise', required=True,
        help="Location-wise: Count all products within selected locations\n"
             "Product-wise: Count selected products across all locations")

    # Max Products per Session
    max_products_per_session = fields.Integer(string="Max Products per Session",
                                              help="Maximum products per session. Leave 0 for all products.")
    use_max_products = fields.Boolean(string="Limit Products per Session", default=False,
                                      help="Enable to limit products per session")

    # Session generation is now based on max_products_per_session configuration
    # No separate type field - sessions are split automatically if max_products_per_session is set

    state = fields.Selection([('draft', 'Draft'), ('verified', 'Verified')],
                             default="draft", string="Status", help="To identify process status")

    approver_id = fields.Many2one(comodel_name="res.users", string="Approver")
    approval_scope = fields.Selection([
        ('session_level', 'Session Level'),
        ('count_level', 'Count Level')
    ], string="Approval Strategy", default='session_level', required=True)
    adjustment_strategy = fields.Selection([
        ('count_level', 'Count Level'),
        ('session_level', 'Session Level')
    ], string="Adjustment Strategy", default='count_level', required=True)
    warehouse_id = fields.Many2one(comodel_name="stock.warehouse", string="Warehouse", required=True)
    location_id = fields.Many2one(comodel_name="stock.location", string="Location")

    # Location-wise Planner fields
    location_ids = fields.Many2many(
        'stock.location',
        string='Locations',
        relation="setu_inventory_count_planner_location_rel",
        column1="planner_id",
        column2="location_id",
        domain="[('id', 'in', locations_ids), ('usage', '=', 'internal')]",
        help="Select locations for Location-wise Planner"
    )
    product_load_type = fields.Selection([
        ('manual', 'Manual'),
        ('location_all_qty', 'Location All Qty (include zero stock)'),
        ('location_available_qty', 'Location Available Qty')
    ], string="Product Load Type", default='manual',
        help="Manual: Select products manually\n"
             "Location All Qty: Load all products from location including zero stock\n"
             "Location Available Qty: Load only products with available quantity")
    product_load_type_product_wise = fields.Selection([
        ('manual', 'Manual'),
        ('user_assignment_products', 'User Assignment Products')
    ], string="Product Load Type", default='manual')
    include_child_locations = fields.Boolean(
        string="Include Child Locations",
        default=True,
        help="If enabled, products will be loaded from child locations as well"
    )

    # Product-wise Planner fields
    product_ids = fields.Many2many(comodel_name="product.product", string="Products")
    product_category_ids = fields.Many2many(comodel_name="product.category", string="Product Categories")
    include_sub_categories = fields.Boolean(
        string="Include Sub Categories",
        default=False,
        help="If enabled, products from child categories of the selected categories will also be included."
    )

    # Notification Configuration
    notify_approver_on_count_creation = fields.Boolean(
        string="Notify Approver on Count Creation",
        default=False,
        help="Send email notification to approver when inventory count is created"
    )
    notify_users_on_session_assignment = fields.Boolean(
        string="Notify Users on Session Assignment",
        default=False,
        help="Send email notification to users when they are assigned to sessions"
    )

    locations_ids = fields.Many2many(
        'stock.location',
        string='Available Locations',
        relation="setu_inventory_count_planner_available_location_rel",
        column1="planner_id",
        column2="location_id",
        compute='_compute_warehouse_id',
        store=True
    )
    approver_ids = fields.Many2many(comodel_name="res.users", compute='_compute_approver_id', store=True,
                                    string="Approvers")
    company_id = fields.Many2one(comodel_name="res.company", related="warehouse_id.company_id",
                                 string="Company", store=True)

    @api.onchange('approval_scope')
    def _onchange_approval_scope(self):
        if self.approval_scope == 'count_level':
            self.adjustment_strategy = 'count_level'

    @api.model_create_multi
    def create(self, vals_list):
        """Set default start_from datetime if not provided"""
        for vals in vals_list:
            if 'start_from' not in vals:
                # Default to today at 9:00 AM
                default_time = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
                vals['start_from'] = default_time
        records = super().create(vals_list)
        # Trigger computation of next execution datetime
        for record in records:
            record._compute_next_execution_datetime()
        return records

    # Session type computation removed - sessions are generated based on max_products_per_session configuration

    @api.depends('frequency_type', 'planing_frequency', 'start_from', 'previous_execution_datetime')
    def _compute_next_execution_datetime(self):
        """Calculate next execution datetime based on frequency, preserving the time from start_from"""
        for record in self:
            if not record.start_from:
                # Set default if not set (today at 9:00 AM)
                default_time = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
                record.next_execution_datetime = default_time
                continue

            # Use previous execution datetime or start_from as base
            base_datetime = record.previous_execution_datetime or record.start_from

            # Extract time from base_datetime to preserve execution time
            execution_time = base_datetime.time()

            # Calculate next date based on frequency
            if record.frequency_type == 'daily':
                next_date = base_datetime.date() + timedelta(days=1)
            elif record.frequency_type == 'weekly':
                next_date = base_datetime.date() + timedelta(weeks=1)
            elif record.frequency_type == 'monthly':
                next_date = base_datetime.date() + relativedelta(months=1)
            elif record.frequency_type == 'yearly':
                next_date = base_datetime.date() + relativedelta(years=1)
            elif record.frequency_type == 'custom':
                days = record.planing_frequency or 1
                next_date = base_datetime.date() + timedelta(days=days)
            else:
                next_date = base_datetime.date() + timedelta(days=1)

            # Combine next date with execution time from start_from
            record.next_execution_datetime = datetime.combine(next_date, execution_time)

    @api.onchange('frequency_type', 'planing_frequency')
    def _onchange_frequency(self):
        if self.frequency_type == 'custom' and not self.planing_frequency:
            self.planing_frequency = 1
        elif self.frequency_type != 'custom':
            self.planing_frequency = 0

    @api.onchange('planner_type', 'product_load_type_product_wise')
    def _onchange_product_wise_load_type(self):
        if self.planner_type != 'product_wise':
            self.product_load_type_product_wise = 'manual'
            return
        if self.product_load_type_product_wise == 'manual':
            self.product_ids = [(5, 0, 0)]
            self.product_category_ids = [(5, 0, 0)]
            self.include_sub_categories = False

    @api.constrains('frequency_type', 'planing_frequency')
    def _check_frequency(self):
        for record in self:
            if record.frequency_type == 'custom' and record.planing_frequency <= 0:
                raise ValidationError('Please Enter Proper Frequency Days for Custom Frequency.')

    def reset_to_draft(self):
        self.state = 'draft'

    @api.depends('warehouse_id')
    def _compute_warehouse_id(self):
        warehouses = self.mapped('warehouse_id')
        all_locations = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            '|',
            ('warehouse_id', 'in', warehouses.ids),
            ('company_id', 'in', self.env.companies.ids)
        ])
        for record in self:
            if record.warehouse_id:
                record.locations_ids = all_locations.filtered(
                    lambda l: l.warehouse_id == record.warehouse_id
                )
            else:
                record.locations_ids = all_locations.filtered(
                    lambda l: l.company_id in self.env.companies
                )

    @api.onchange('warehouse_id')
    def onchange_warehouse_id(self):
        """Clear location_ids when warehouse changes"""
        # Clear selected locations when warehouse changes (whether set or cleared)
        if self.location_ids:
            self.location_ids = [(5, 0, 0)]
        # Also clear the single location_id field if set
        if self.location_id:
            self.location_id = False

    @api.onchange('location_id')
    def onchange_location_id(self):
        if self.location_id:
            domain = [('view_location_id', 'parent_of', self.location_id.id)]
            wh = self.env['stock.warehouse'].search(domain)
            return {'value': {
                'warehouse_id': wh.id}}

    @api.depends('approver_id')
    def _compute_approver_id(self):
        group = self.sudo().env.ref('setu_inventory_count_management.group_setu_inventory_count_approver',
                                    raise_if_not_found=False)
        approver_ids = group.users.ids if group else []
        for record in self:
            record.approver_ids = approver_ids

    def auto_create_inventory_count_record(self):
        """
        Scheduler method to automatically create inventory counts for verified planners.
        Runs hourly to handle multiple planners with different execution times and frequencies.
        Checks both date and time to execute planners at their scheduled time.
        """
        now = fields.Datetime.now()
        # Find all verified planners that are due for execution (datetime <= now)
        domain = [
            ('next_execution_datetime', '<=', now),
            ('state', '=', 'verified'),
            ('active', '=', True)
        ]
        records = self.search(domain, order='next_execution_datetime asc')

        if not records:
            return True

        # Process each planner
        for record in records:
            try:
                # Double-check the planner is still valid before execution
                if record.state == 'verified' and record.active:
                    # Verify the execution datetime is still valid
                    if record.next_execution_datetime and record.next_execution_datetime <= now:
                        record.create_inventory_count_record()
            except Exception as e:
                # Log error but continue with other planners
                self.env.cr.rollback()
                _logger.error("Error creating inventory count for planner %s: %s", record.name, str(e))
                continue

        return True

    def verify_inventory_count_planing(self):
        if self.frequency_type == 'custom' and self.planing_frequency <= 0:
            raise ValidationError('Please Enter Proper Frequency Days for Custom Frequency.')
        if self.planner_type == 'location_wise' and not self.location_ids:
            raise ValidationError('Please select at least one location for Location-wise Planner.')
        if self.planner_type == 'product_wise' and self.product_load_type_product_wise == 'user_assignment_products' and not self.product_ids and not self.product_category_ids:
            raise ValidationError('Please select Products or Product Categories for Product-wise Planner.')
        if not self.warehouse_id:
            raise ValidationError('Please select a Warehouse.')
        if not self.approver_id:
            raise ValidationError('Please select an Approver.')
        self.write({'state': 'verified'})
        return True

    def create_inventory_count(self):
        self.create_inventory_count_record()
        return True

    def create_inventory_count_record(self):
        """Create exactly one inventory count per planner run and auto-generate sessions.

        Both location-wise and product-wise strategies produce a single ``setu.stock.inventory.count``
        record; location-wise adds sessions (and optional splits) for each selected location.
        """
        inventory_count_obj = self.env['setu.stock.inventory.count']
        now = fields.Datetime.now()

        if self.planner_type == 'location_wise':
            # Single count for all planner locations; sessions are still created per location
            vals = self._prepare_count_vals_for_location(self.location_ids[0])
            count = inventory_count_obj.create(vals)

            for location in self.location_ids:
                product_location_data = []
                if self.product_load_type in ('location_all_qty', 'location_available_qty'):
                    product_location_data = self._auto_load_products_for_count(count, location)
                self._auto_generate_sessions_for_count(count, location, product_location_data)

            if self.notify_approver_on_count_creation:
                self._send_notification_to_approver(count)
        else:
            # Product-wise: Create single count with selected products/categories
            product_ids = self.env['product.product']
            if self.product_load_type_product_wise == 'user_assignment_products':
                product_ids = self._get_products_for_product_wise()
                # Validate that products were found
                if not product_ids:
                    raise ValidationError('No products found. Please select products or product categories.')

            vals = self._prepare_count_vals_for_product_wise(product_ids)
            count = inventory_count_obj.create(vals)

            # Auto-generate sessions for product-wise with product data
            # Pass product_ids to session creation so products can be assigned in sessions
            self._auto_generate_sessions_for_count(
                count,
                False,
                product_ids=product_ids if self.product_load_type_product_wise == 'user_assignment_products' else None,
            )

            # Send notification to approver if configured
            if self.notify_approver_on_count_creation:
                self._send_notification_to_approver(count)

        # Update execution datetime
        # previous_execution_datetime: The actual execution time
        self.write({
            'previous_execution_datetime': now,
        })
        self._compute_next_execution_datetime()

    def _auto_load_products_for_count(self, count, location):
        """
        Auto-load products based on product_load_type and return product-quant-location mapping.
        Products are NOT assigned to count lines - only to session lines.
        If include_child_locations is enabled, products from child locations are included with their actual locations.
        """
        # Determine location domain based on include_child_locations flag
        if self.include_child_locations:
            # Include products from the location and all its child locations
            location_domain = [('location_id', 'child_of', location.id)]
        else:
            # Only include products from the exact location (no child locations)
            location_domain = [('location_id', '=', location.id)]

        if self.product_load_type == 'location_available_qty':
            location_domain.append(('quantity', '>', 0))
        elif self.product_load_type != 'location_all_qty':
            return []

            # Odoo 18 Best Practice: Use the modern tuple-returning _read_group
        query_results = self.env['stock.quant']._read_group(
            domain=location_domain,
            groupby=['product_id', 'location_id'],
            aggregates=['quantity:sum']
        )

        product_location_qty_list = []
        for product, actual_location, qty_sum in query_results:
            product_location_qty_list.append({
                'product_id': product.id,
                'product': product,
                'location_id': actual_location.id,
                'actual_location': actual_location,
                'theoretical_qty': qty_sum
            })

        return product_location_qty_list

    def _auto_generate_sessions_for_count(self, count, location, product_location_data=None, product_ids=None):
        """Auto-generate sessions for count based on location and max_products_per_session configuration"""
        session_obj = self.env['setu.inventory.count.session']

        if location:
            # Location-wise: Create sessions per location (split by max_products_per_session if configured)
            self._create_session_for_location(count, location, product_location_data)
        else:
            # Product-wise: Split by max products if limit is set, otherwise single session
            if self.product_load_type_product_wise == 'manual':
                self._create_single_session_for_products(count, product_ids=None)
                return
            if count.max_products_per_session > 0:
                self._create_sessions_by_product_limit(count, product_ids=product_ids)
            else:
                # Single session with all products
                self._create_single_session_for_products(count, product_ids=product_ids)

    def _create_session_for_location(self, count, location, product_location_data=None):
        """Create sessions for a specific location, splitting by max_products_per_session if needed
        Products are assigned directly in sessions with their actual locations from quants"""
        session_obj = self.env['setu.inventory.count.session']

        # If product_location_data is provided (from auto-load), use it
        # Products are NOT assigned to count level - only in sessions
        if product_location_data:
            # Use the product-location data from auto-load
            product_location_list = product_location_data
        else:
            # No products loaded - create empty session
            # Products can be added later via wizard or manual entry
            # is_multi_session based on max_products_per_session configuration
            is_multi = count.max_products_per_session > 0 if count.max_products_per_session else False
            session_vals = {
                'is_multi_session': is_multi,
                'inventory_count_id': count.id,
                'location_id': location.id,
                'assigned_location_ids': [(6, 0, [location.id])],
                'warehouse_id': count.warehouse_id.id,
                'use_barcode_scanner': count.use_barcode_scanner,
            }
            session_obj.create(session_vals)
            return

        # Always create at least one session per location, even if no products yet
        if not product_location_list:
            # is_multi_session based on max_products_per_session configuration
            is_multi = count.max_products_per_session > 0 if count.max_products_per_session else False
            session_vals = {
                'is_multi_session': is_multi,
                'inventory_count_id': count.id,
                'location_id': location.id,
                'assigned_location_ids': [(6, 0, [location.id])],
                'warehouse_id': count.warehouse_id.id,
                'use_barcode_scanner': count.use_barcode_scanner,
            }
            session_obj.create(session_vals)
            return

        # Split products if max_products_per_session is set
        max_products = count.max_products_per_session if count.max_products_per_session > 0 else len(
            product_location_list)
        product_chunks = [product_location_list[i:i + max_products] for i in
                          range(0, len(product_location_list), max_products)]
        # is_multi_session is True if multiple sessions are created (more than 1 chunk)
        is_multi = len(product_chunks) > 1

        for idx, product_chunk in enumerate(product_chunks):
            session_line_vals = []
            for product_data in product_chunk:
                actual_location = product_data.get('actual_location', location)
                actual_location_id = actual_location.id if hasattr(actual_location, 'id') else actual_location

                session_line_vals.append((0, 0, {
                    'product_id': product_data['product_id'],
                    'inventory_count_id': count.id,
                    'inventory_count_line_id': False,
                    'location_id': actual_location_id,
                    'theoretical_qty': product_data.get('theoretical_qty', 0.0),
                    'is_multi_session': is_multi,
                }))

            session_vals = {
                'is_multi_session': is_multi,
                'inventory_count_id': count.id,
                'location_id': location.id,
                'assigned_location_ids': [(6, 0, [location.id])],
                'warehouse_id': count.warehouse_id.id,
                'use_barcode_scanner': count.use_barcode_scanner,
                'session_line_ids': session_line_vals,  # Assign lines natively during creation
            }
            session_obj.create(session_vals)

    def _create_sessions_by_product_limit(self, count, product_ids=None):
        """Create multiple sessions splitting products by max_products_per_session"""
        session_obj = self.env['setu.inventory.count.session']
        # Get products from parameter or from count lines (products are not stored at count level anymore)
        if product_ids:
            products = product_ids
        else:
            products = count.line_ids.mapped('product_id')
        max_products = count.max_products_per_session

        if not products or max_products <= 0:
            return

        product_chunks = [products[i:i + max_products] for i in range(0, len(products), max_products)]
        # is_multi_session is True if multiple sessions are created (more than 1 chunk)
        is_multi = len(product_chunks) > 1

        for idx, product_chunk in enumerate(product_chunks):
            session_vals = {
                'is_multi_session': is_multi,
                'inventory_count_id': count.id,
                'location_id': False,  # Location not set at count level - will be set at session line level
                'warehouse_id': count.warehouse_id.id,
                'use_barcode_scanner': count.use_barcode_scanner,
            }
            session = session_obj.create(session_vals)

            # Create session lines
            session_line_vals = []
            for product in product_chunk:
                session_line_vals.append((0, 0, {
                    'product_id': product.id,
                    'inventory_count_id': count.id,
                    'is_multi_session': is_multi,
                }))

            if session_line_vals:
                session.write({'session_line_ids': session_line_vals})

    def _create_single_session_for_products(self, count, product_ids=None):
        """Create a single session for all products"""
        session_obj = self.env['setu.inventory.count.session']

        session_vals = {
            'is_multi_session': False,
            'inventory_count_id': count.id,
            'location_id': False,  # Location not set at count level - will be set at session line level
            'warehouse_id': count.warehouse_id.id,
            'use_barcode_scanner': count.use_barcode_scanner,
        }
        session = session_obj.create(session_vals)

        # Create session lines for all products
        session_line_vals = []
        if product_ids:
            # Products provided directly (for product-wise planner)
            for product in product_ids:
                session_line_vals.append((0, 0, {
                    'product_id': product.id,
                    'inventory_count_id': count.id,
                    'inventory_count_line_id': False,  # No count line - products in sessions only
                    'location_id': False,  # Location will be determined during counting
                    'is_multi_session': False,
                }))
        else:
            # Get products from count lines (fallback for manual counts)
            for count_line in count.line_ids:
                session_line_vals.append((0, 0, {
                    'product_id': count_line.product_id.id,
                    'inventory_count_id': count.id,
                    'inventory_count_line_id': count_line.id,
                    'location_id': count_line.location_id.id if count_line.location_id else False,
                    'is_multi_session': False,
                }))

        if session_line_vals:
            session.write({'session_line_ids': session_line_vals})

    def _get_products_for_product_wise(self):
        """Get products based on product selection or category selection"""
        domain = [('is_storable', '=', True)]
        conditions = []

        if self.product_ids:
            conditions.append(('id', 'in', self.product_ids.ids))

        if self.product_category_ids:
            categ_ids = self.product_category_ids.ids
            if self.include_sub_categories:
                # child_of automatically handles the sub-tree lookup in SQL
                conditions.append(('categ_id', 'child_of', categ_ids))
            else:
                conditions.append(('categ_id', 'in', categ_ids))

        # Combine conditions with OR '|' if both are selected
        if len(conditions) == 2:
            domain = ['|'] + conditions + domain
        elif len(conditions) == 1:
            domain = conditions + domain
        else:
            return self.env['product.product']

        return self.env['product.product'].search(domain)

    def _send_notification_to_approver(self, count):
        """Send notification to approver using user's notification preference."""
        if not count.approver_id or not count.approver_id.partner_id:
            return

        try:
            approver = count.approver_id
            partner_email = (approver.partner_id.email or '').strip()
            company = count.company_id.sudo()
            mail_from = (
                getattr(company, 'email_formatted', None)
                or company.email
                or (count.create_uid.partner_id.email if count.create_uid and count.create_uid.partner_id else '')
            )

            # Always try sending email if approver has email.
            template = self.env.ref(
                'setu_inventory_count_management.mail_template_notify_approver_count_creation',
                raise_if_not_found=False
            )
            if template and partner_email:
                email_values = {'email_to': partner_email}
                if mail_from:
                    email_values.update({
                        'email_from': mail_from,
                        'reply_to': mail_from,
                    })
                template.sudo().with_context(
                    lang=approver.lang or approver.partner_id.lang or self.env.lang
                ).send_mail(
                    count.id,
                    force_send=True,
                    email_values=email_values,
                )

            if approver.notification_type == 'inbox':
                count.message_post(
                    body=_("A new Inventory Count '%s' has been created and assigned for your approval.") % (
                        count.display_name,
                    ),
                    message_type='notification',
                    partner_ids=[approver.partner_id.id],
                    subtype_id=self.env.ref('mail.mt_comment').id
                )
            elif not partner_email:
                # If no email exists, still notify in-app for visibility.
                count.message_post(
                    body=_("A new Inventory Count '%s' has been created and assigned for your approval.") % (
                        count.display_name,
                    ),
                    message_type='notification',
                    partner_ids=[approver.partner_id.id],
                    subtype_xmlid='mail.mt_comment',
                )
        except Exception as e:
            # Keep count creation stable but log the reason notification failed.
            _logger.exception(
                "Failed to send approver notification for inventory count %s: %s",
                count.display_name,
                e,
            )

    def _prepare_count_vals_for_location(self, location):
        """Prepare values for count creation (location-wise) - location not set at count level"""
        return {
            'planner_id': self.id,
            'approver_id': self.approver_id.id,
            'approval_scope': self.approval_scope,
            'adjustment_strategy': self.adjustment_strategy,
            'warehouse_id': self.warehouse_id.id,
            'session_strategy': 'location_wise',
            # location_id removed - sessions will have location instead
            # type removed - session generation based on max_products_per_session
            'use_barcode_scanner': self.use_barcode_scanner,
            'product_load_type': self.product_load_type,
            'use_max_products': self.use_max_products,
            'max_products_per_session': self.max_products_per_session if self.use_max_products else 0,
            'inventory_count_date': fields.Date.today(),
        }

    def _prepare_count_vals_for_product_wise(self, product_ids):
        """Prepare values for count creation (product-wise) - products not stored at count level"""
        return {
            'planner_id': self.id,
            'approver_id': self.approver_id.id,
            'approval_scope': self.approval_scope,
            'adjustment_strategy': self.adjustment_strategy,
            'warehouse_id': self.warehouse_id.id,
            'session_strategy': 'product_wise',
            # type removed - session generation based on max_products_per_session
            'use_barcode_scanner': self.use_barcode_scanner,
            # product_ids removed - products are assigned only in sessions
            'product_load_type': 'manual',
            'product_load_type_product_wise': self.product_load_type_product_wise or 'manual',
            'use_max_products': self.use_max_products,
            'max_products_per_session': self.max_products_per_session if self.use_max_products else 0,
            'inventory_count_date': fields.Date.today(),
        }
