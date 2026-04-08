# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class SessionCreator(models.TransientModel):
    _name = 'setu.inventory.session.creator'
    _description = 'Inventory Session Creator'

    is_multi_session = fields.Boolean(default=False, string="Is multi Session")

    inventory_count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", string="Inventory Count")

    user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Users",
        domain=lambda self: self._get_allowed_assignment_user_domain(),
    )
    product_ids = fields.Many2many(comodel_name="product.product", string="Products")
    category_ids = fields.Many2many(comodel_name="product.category", string="Product Categories")
    assignment_basis = fields.Selection([
        ('product', 'Product'),
        ('category', 'Category'),
    ], string="Selection Type", default='product')
    location_ids = fields.Many2many(
        comodel_name="stock.location",
        relation="setu_session_creator_location_rel",
        column1="wizard_id",
        column2="location_id",
        string="Locations",
    )

    parent_count_id = fields.Many2one(comodel_name="setu.stock.inventory.count", string="Parent Count")
    warehouse_id = fields.Many2one(comodel_name="stock.warehouse", string="Warehouse")
    session_strategy = fields.Selection([
        ('location_wise', 'Location Wise'),
        ('product_wise', 'Product Wise')
    ], string="Session Strategy")
    product_load_type = fields.Selection([
        ('manual', 'Manual'),
        ('location_all_qty', 'Location All Qty (include zero stock)'),
        ('location_available_qty', 'Location Available Qty'),
        ('user_assignment_products', 'User Assignment Products')
    ], string="Product Load Type")
    company_id = fields.Many2one(comodel_name="res.company", string="Company")

    def _get_allowed_assignment_user_domain(self):
        inventory_user_group = self.env.ref(
            'setu_inventory_count_management.group_setu_inventory_count_user',
            raise_if_not_found=False,
        )
        domain = [('share', '=', False), ('company_ids', 'in', self.env.companies.ids)]
        if inventory_user_group:
            domain.append(('groups_id', 'in', [inventory_user_group.id]))
        return domain

    def _check_assigned_users_are_inventory_users(self):
        invalid_users = [
            u for u in self.user_ids
            if not u.has_group('setu_inventory_count_management.group_setu_inventory_count_user')
        ]
        if invalid_users:
            raise ValidationError(_("Only users with Inventory Count User rights can be assigned to sessions."))

    def _get_selected_products(self):
        self.ensure_one()
        if self.assignment_basis == 'product':
            return self.product_ids
        if self.assignment_basis == 'category':
            if not self.category_ids:
                return self.env['product.product']
            return self.env['product.template'].search([
                ('categ_id', 'in', self.category_ids.ids),
                ('is_storable', '=', True),
            ]).product_variant_ids

    @api.onchange('assignment_basis')
    def _onchange_assignment_basis(self):
        if self.assignment_basis == 'product':
            self.category_ids = [(5, 0, 0)]
        elif self.assignment_basis == 'category':
            self.product_ids = [(5, 0, 0)]

    @api.onchange('session_strategy', 'product_load_type')
    def _onchange_strategy_and_load_type(self):
        if self.session_strategy == 'location_wise':
            self.product_ids = [(5, 0, 0)]
            self.category_ids = [(5, 0, 0)]
        if self.product_load_type != 'user_assignment_products':
            self.assignment_basis = 'product'
            self.category_ids = [(5, 0, 0)]

    def _split_line_vals(self, line_vals, chunk_size):
        if not line_vals:
            return [[]]
        if not chunk_size or chunk_size <= 0:
            return [line_vals]
        return [line_vals[i:i + chunk_size] for i in range(0, len(line_vals), chunk_size)]

    def _build_combined_location_line_vals(self, count_id):
        """Build line values across all selected locations efficiently."""
        self.ensure_one()

        if count_id.product_load_type not in ('location_all_qty', 'location_available_qty'):
            selected_products = self._get_selected_products()
            return [
                {
                    'product_id': product.id,
                    'inventory_count_id': count_id.id,
                    'location_id': root_location.id,
                }
                for root_location in self.location_ids
                for product in selected_products
            ]

        # OPTIMIZATION: Single DB query for all quants, filtering 'is_storable' at PostgreSQL level.
        quant_domain = [
            ('location_id', 'child_of', self.location_ids.ids),
            ('location_id.usage', '=', 'internal'),
            ('product_id.is_storable', '=', True),
        ]
        if count_id.product_load_type == 'location_available_qty':
            quant_domain.append(('quantity', '>', 0))

        # search_read returns raw dicts, bypassing ORM instantiation overhead
        quants = self.env['stock.quant'].sudo().search_read(
            quant_domain,
            ['product_id', 'location_id']
        )

        # Use a Set comprehension to efficiently get unique (product_id, location_id) tuples
        unique_pairs = {
            (q['product_id'][0], q['location_id'][0])
            for q in quants if q.get('product_id') and q.get('location_id')
        }

        return [
            {
                'product_id': product_id,
                'inventory_count_id': count_id.id,
                'location_id': location_id,
            }
            for product_id, location_id in unique_pairs
        ]

    def confirm(self, users=False):
        if not self.user_ids:
            raise ValidationError(_("Please add User(s)."))
        self._check_assigned_users_are_inventory_users()
        if self.session_strategy == 'location_wise' and not self.location_ids:
            raise ValidationError(_("Please add at least one location for Location Wise strategy."))

        count_id = self.inventory_count_id
        max_products = count_id.max_products_per_session if count_id.use_max_products else 0
        session_payloads = []

        if self.session_strategy == 'product_wise':
            if self.product_load_type == 'user_assignment_products':
                products = self._get_selected_products()
                if not products:
                    if self.assignment_basis == 'category':
                        raise ValidationError(_("Product is not available in selected category."))
                    raise ValidationError(_("Please select at least one product."))

                line_vals = [{
                    'product_id': product.id,
                    'inventory_count_id': count_id.id,
                    'location_id': False,
                } for product in products]

                # Case 2: Split session per products with assigned users and unique products per session
                # If limit is 0 or not defined, load all in one session
                chunks = self._split_line_vals(line_vals, max_products)
                for chunk in chunks:
                    session_payloads.append({
                        'assigned_location_ids': [],
                        'location_id': False,
                        'line_vals': chunk,
                    })
            else:
                # Case 1: Product-wise, manual
                # Create one session for selected users. Limit is checked during scanning.
                session_payloads.append({
                    'assigned_location_ids': [],
                    'location_id': False,
                    'line_vals': [],
                })

        elif self.session_strategy == 'location_wise':
            assigned_location_ids = self.location_ids.ids
            if self.product_load_type == 'manual':
                # Create one combined session for all selected locations.
                session_payloads.append({
                    'assigned_location_ids': assigned_location_ids,
                    'location_id': False,
                    'line_vals': [],
                })
            else:
                # Load products for all selected locations in one pool and split only by limit.
                line_vals = self._build_combined_location_line_vals(count_id)
                if not line_vals:
                    raise ValidationError(_("Product is not available in selected location."))
                chunks = self._split_line_vals(line_vals, max_products)
                for chunk in chunks:
                    session_payloads.append({
                        'assigned_location_ids': assigned_location_ids,
                        'location_id': False,
                        'line_vals': chunk,
                    })

        if not session_payloads:
            raise ValidationError(
                _("No products or locations found to create sessions for the selected configuration."))

        # Create sessions
        user_list = self.user_ids.ids or (users.ids if users else [])

        is_multi = len(session_payloads) > 1

        # OPTIMIZATION: Batch create. Prepare all dictionary objects and create them in a single query.
        # This replaces the slow loop creating sessions and subsequently doing a .write() for the lines.
        sessions_to_create = []
        for payload in session_payloads:
            session_vals = {
                'is_multi_session': is_multi,
                'inventory_count_id': count_id.id,
                'location_id': payload.get('location_id'),
                'warehouse_id': count_id.warehouse_id.id,
                'use_barcode_scanner': count_id.use_barcode_scanner,
                'assigned_location_ids': [(6, 0, payload.get('assigned_location_ids', []))],
                'user_ids': [(6, 0, user_list)],
                'session_line_ids': [
                    (0, 0, {
                        'product_id': line.get('product_id'),
                        'inventory_count_id': line.get('inventory_count_id'),
                        'location_id': line.get('location_id'),
                    }) for line in payload.get('line_vals', [])
                ]
            }
            sessions_to_create.append(session_vals)

        # 1 Single execute call mapped directly to postgres
        if sessions_to_create:
            self.env['setu.inventory.count.session'].create(sessions_to_create)

        self.inventory_count_id.write({'state': 'In Progress'})
