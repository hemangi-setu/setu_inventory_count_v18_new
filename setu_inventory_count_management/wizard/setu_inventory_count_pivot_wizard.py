from odoo import fields, models

from odoo.addons.setu_inventory_count_management.report.const import (
    inventory_count_approver_user_domain,
    inventory_count_report_location_domain,
)


class InventoryCountPivotWizard(models.TransientModel):
    _name = "setu.inventory.count.pivot.wizard"
    _description = "Inventory Count Pivot Wizard"

    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")
    location_ids = fields.Many2many(
        comodel_name="stock.location",
        string="Locations",
        domain=lambda self: inventory_count_report_location_domain(self.env),
    )
    approver_ids = fields.Many2many(
        comodel_name="res.users",
        string="Approvers",
        domain=lambda self: inventory_count_approver_user_domain(self.env),
    )

    def action_generate_report(self):
        domain = []
        company_ids = self.env.companies.ids
        if not company_ids:
            company_ids = [self.env.company.id]
        domain.append(('company_id', 'in', company_ids))
        if self.start_date:
            domain.append(('date', '>=', self.start_date))
        if self.end_date:
            domain.append(('date', '<=', self.end_date))
        if self.location_ids:
            domain.append(('location_id', 'in', self.location_ids.ids))
        if self.approver_ids:
            domain.append(('approver_id', 'in', self.approver_ids.ids))

        return {
            'type': 'ir.actions.act_window',
            'name': 'Inventory Discrepancy Pivot Report',
            'res_model': 'setu.inventory.discrepancy.report',
            'view_mode': 'pivot',
            'target': 'current',
            'domain': domain,
        }