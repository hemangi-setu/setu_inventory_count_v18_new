# -*- coding: utf-8 -*-
from odoo import fields, models


class SetuInventoryValidateWiz(models.TransientModel):
    _name = 'setu.inventory.session.validate.wizard'
    _description = 'Setu Inventory  Session Validate Wizard'

    session_id = fields.Many2one(
        comodel_name="setu.inventory.count.session",
        string="Session"
    )
    session_state = fields.Selection(
        related="session_id.state",
        string="Session State"
    )
    user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Users"
    )

    def create_re_count(self):
        count = self.env['setu.stock.inventory.count'].sudo().browse(self.env.context.get('active_id', False))
        count.open_new_count(self.user_ids)

    def create_re_session(self):
        session = self.env['setu.inventory.count.session'].browse(self.env.context.get('active_id', False))
        session.open_new_session()
        session._validate_session()

    def no_re_session(self):
        session = self.env['setu.inventory.count.session'].browse(self.env.context.get('active_id', False))
        session._validate_session()

    def continue_re_session(self):
        self.create_re_session()
