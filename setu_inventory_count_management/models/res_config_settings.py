# -*- coding: utf-8 -*-
from odoo import fields, models, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    auto_inventory_adjustment = fields.Boolean(string="Auto Inventory Adjustment?",config_parameter='setu_inventory_count_management.auto_inventory_adjustment')