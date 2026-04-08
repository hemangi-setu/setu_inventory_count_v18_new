# -*- coding: utf-8 -*-
import datetime
from datetime import datetime

from odoo import fields, models,api


class InvSessionDetails(models.Model):
    _name = 'setu.inventory.session.details'
    _description = 'Inventory Session Details'

    duration = fields.Char(compute="_compute_duration", string="Duration",store=True)

    start_date = fields.Datetime(string="Start Date")
    end_date = fields.Datetime(string="End Date")

    duration_seconds = fields.Integer(compute="_compute_duration", string="Duration seconds",store=True)

    session_id = fields.Many2one(comodel_name="setu.inventory.count.session", string="Session")

    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for history in self:
            start_date = history.start_date
            end_date = history.end_date
            if not history.end_date:
                end_date = fields.Datetime.now()
            if start_date and end_date:
                difference = end_date - start_date
                history.duration = str(difference)
                history.duration_seconds = int(difference.total_seconds())
            else:
                history.duration = ''
                history.duration_seconds = 0
