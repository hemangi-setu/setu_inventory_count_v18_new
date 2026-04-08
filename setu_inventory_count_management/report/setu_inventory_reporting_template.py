# -*- coding: utf-8 -*-
from odoo import fields, models

from odoo.addons.setu_inventory_count_management.report.const import (
    inventory_count_approver_user_domain,
    inventory_count_report_location_domain,
    inventory_count_report_warehouse_domain,
)


class SetuReportTemplate(models.TransientModel):
    _name = 'setu.inventory.reporting.template'
    _description = 'Setu Inventory Reporting Template'

    start_date = fields.Date(string="Start Date")
    inventory_count_date = fields.Date(string="Inventory Count Date")
    end_date = fields.Date(string="End Date")

    theoretical_qty = fields.Float(string="Theoretical Quantity")
    counted_qty = fields.Float(string="Counted Quantity")
    discrepancy_qty = fields.Float(string="Discrepancy Quantity")

    product_id = fields.Many2one(comodel_name="product.product", string="Product")
    warehouse_id = fields.Many2one(comodel_name="stock.warehouse", string="Warehouse")
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location",
        domain=lambda self: inventory_count_report_location_domain(self.env),
    )
    user_id = fields.Many2one(comodel_name="res.users", string="User")

    user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Users",
        domain=lambda self: inventory_count_approver_user_domain(self.env),
    )
    warehouse_ids = fields.Many2many(
        comodel_name="stock.warehouse",
        string="Warehouses",
        domain=lambda self: inventory_count_report_warehouse_domain(self.env),
    )
    location_ids = fields.Many2many(
        comodel_name="stock.location",
        string="Locations",
        domain=lambda self: inventory_count_report_location_domain(self.env),
    )
    lot_id = fields.Many2one(comodel_name="stock.lot", string="Lot")
