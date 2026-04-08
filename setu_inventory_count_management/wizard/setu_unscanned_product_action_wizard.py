# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class SetuUnscannedProductActionWizard(models.TransientModel):
    _name = 'setu.unscanned.product.action.wizard'
    _description = "setu unscanned product action wizard"

    unscanned_product_line_ids = fields.Many2many('setu.unscanned.product.lines', 'unscanned_product_lines_rel',
                                                  string="Unscanned Product Lines")
    action = fields.Selection(
        [('make_it_0', 'Make It Zero'), ('do_nothing', 'Do Nothing'), ('remove_action', 'Remove Action')])

    def action_open_wizard(self):
        records = self.env['setu.unscanned.product.lines'].browse(self.env.context.get('active_ids', []))
        action = {
            'name': 'Unscanned Products',
            'type': 'ir.actions.act_window',
            "view_mode": "form",
            'res_model': 'setu.unscanned.product.action.wizard',
            'target': 'new',
            'context': {'default_unscanned_product_line_ids': records.ids}
        }
        # Try to get the view if it exists, otherwise use default form view
        try:
            view_id = self.sudo().env.ref(
                'setu_inventory_count_management.setu_unscanned_product_action_wizard_form_view').id
            action['view_id'] = view_id
        except ValueError:
            # View not found, Odoo will use default form view
            pass
        return action

    def set_action(self):
        if not self.unscanned_product_line_ids:
            raise UserError(_("No unscanned product lines selected."))

        if not self.action:
            raise UserError(_("Please select an action."))

        # Check if any count is already approved
        for line in self.unscanned_product_line_ids:
            if line.inventory_count_id.state in ['Inventory Adjusted',
                                                 'Cancel'] or line.inventory_count_id.inventory_adj_ids:
                raise UserError(_("Count %s is already adjusted or cancelled.") % line.inventory_count_id.name)

        # Update action on all lines
        self.unscanned_product_line_ids.write({'action': self.action})

        count_lines = []
        session_lines = []
        for line in self.unscanned_product_line_ids:
            if self.action == 'make_it_0':
                if line.session_id:
                    session_lines.append({
                        'session_id': line.session_id.id,
                        'inventory_count_id': line.inventory_count_id.id,
                        'product_id': line.product_id.id,
                        'location_id': line.location_id.id,
                        'lot_id': line.lot_id.id if line.product_id.tracking == 'lot' else False,
                        'serial_number_ids': [
                            (6, 0, [line.lot_id.id])] if line.product_id.tracking == 'serial' else False,
                        'theoretical_qty': line.quantity,
                        'scanned_qty': 0,
                        'product_scanned': True,
                        'is_system_generated': True,
                        'state': 'Approve',
                        'unscanned_product_line_id': line.id,
                    })
                else:
                    product_found = line.inventory_count_id.line_ids.filtered(
                        lambda x: x.product_id.id == line.product_id.id)
                    lot_found = product_found.filtered(
                        lambda x: x.lot_id.id == line.lot_id.id)
                    serial_found = product_found.filtered(lambda x: x._has_serial_number(line.lot_id.id))
                    if not product_found or (line.product_id.tracking == 'lot' and not lot_found) or (
                            line.product_id.tracking == 'serial' and not serial_found):
                        serial_not_found = next((item for item in count_lines if
                                                 item.get('product_id') == line.product_id.id and item.get(
                                                     'location_id') == line.location_id.id and item[
                                                     'not_found_serial_number_ids'] and line.lot_id.id not in
                                                 item['not_found_serial_number_ids'][0][
                                                     2]), None)
                        if serial_not_found:
                            current_ids = serial_not_found['not_found_serial_number_ids'][0][2]
                            serial_not_found['not_found_serial_number_ids'] = [(6, 0, current_ids + [line.lot_id.id])]
                            serial_not_found.update({'theoretical_qty': serial_not_found['theoretical_qty'] + 1,
                                                     'qty_in_stock': serial_not_found['qty_in_stock'] + 1})
                        else:
                            count_lines.append({'inventory_count_id': line.inventory_count_id.id,
                                                'product_id': line.product_id.id,
                                                'tracking': line.product_id.tracking,
                                                'not_found_serial_number_ids': [(6, 0, [
                                                    line.lot_id.id])] if line.product_id.tracking == 'serial' else False,
                                                'lot_id': line.lot_id.id if line.product_id.tracking == 'lot' else False,
                                                'location_id': line.location_id.id,
                                                'theoretical_qty': line.quantity,
                                                'qty_in_stock': line.quantity,
                                                'counted_qty': 0,
                                                'unscanned_product_line_id': line.id,
                                                'state': 'Approve'})
                    elif serial_found:
                        if line.lot_id.id not in serial_found.not_found_serial_number_ids.ids:
                            serial_found.write({
                                'not_found_serial_number_ids': [(4, line.lot_id.id)],
                                'new_count_lot_ids': [(3, line.lot_id.id)]
                            })
            elif self.action == 'remove_action':
                self._remove_related_line_for_unscanned_line(line)
            else:
                # action == 'do_nothing'
                self._remove_related_line_for_unscanned_line(line)

        if count_lines:
            created_lines = self.env['setu.stock.inventory.count.line'].create(count_lines)
            for line_data, count_line_id in zip(count_lines, created_lines.ids):
                self.env['setu.unscanned.product.lines'].browse(
                    line_data['unscanned_product_line_id']
                ).write({'inventory_count_line_id': count_line_id})
        if session_lines:
            created_lines = self.env['setu.inventory.count.session.line'].create(session_lines)
            for line_data, session_line_id in zip(session_lines, created_lines.ids):
                self.env['setu.unscanned.product.lines'].browse(
                    line_data['unscanned_product_line_id']
                ).write({'session_line_id': session_line_id})

        # Return action to close the wizard
        return {'type': 'ir.actions.act_window_close'}

    def _remove_related_line_for_unscanned_line(self, line):
        if line.session_id:
            if line.session_line_id:
                line.session_line_id.unlink()
            line.write({'session_line_id': False})
            return

        count_line = line.inventory_count_line_id
        if not count_line and line.product_id.tracking == 'serial':
            count_line = line.inventory_count_id.line_ids.filtered(
                lambda x: x.product_id.id == line.product_id.id
                          and x.location_id.id == line.location_id.id
                          and line.lot_id.id in x.not_found_serial_number_ids.ids
            )[:1]

        if not count_line:
            line.write({'inventory_count_line_id': False})
            return

        if line.product_id.tracking == 'serial' and len(count_line.not_found_serial_number_ids) > 1:
            count_line.write({
                'not_found_serial_number_ids': [(3, line.lot_id.id)],
                'new_count_lot_ids': [(4, line.lot_id.id)],
            })
            if count_line.unscanned_product_line_id == line:
                count_line.unscanned_product_line_id = False
        else:
            count_line.unlink()

        line.write({'inventory_count_line_id': False})
