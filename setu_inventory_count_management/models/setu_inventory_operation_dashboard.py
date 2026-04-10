# -*- coding: utf-8 -*-
from collections import defaultdict
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SetuInventoryOperationDashboard(models.AbstractModel):
    _name = 'setu.inventory.operation.dashboard'
    _description = 'Inventory Operation Dashboard'

    @api.model
    def get_operation_dashboard_data(
            self,
            start_date=None,
            end_date=None,
            warehouse_ids=None,
            user_ids=None,
            session_ids=None):
        """Single RPC source for Inventory Operation dashboard KPI cards."""
        try:
            if start_date and end_date:
                start_dt = fields.Date.to_date(start_date)
                end_dt = fields.Date.to_date(end_date)
                if start_dt and end_dt and start_dt > end_dt:
                    raise ValidationError("From date cannot be greater than To date.")

            session_domain = []
            if start_date:
                session_domain.append(('create_date', '>=', f"{start_date} 00:00:00"))
            if end_date:
                session_domain.append(('create_date', '<=', f"{end_date} 23:59:59"))
            if warehouse_ids:
                session_domain.append(('warehouse_id', 'in', warehouse_ids))
            if user_ids:
                session_domain.append(('user_ids', 'in', user_ids))
            if session_ids:
                session_domain.append(('id', 'in', session_ids))

            session_domain += [
                ('state', '!=', 'cancel'),
                ('warehouse_id.company_id', 'in', self.env.companies.ids)
            ]

            session_obj = self.env['setu.inventory.count.session'].sudo()
            line_obj = self.env['setu.inventory.count.session.line'].sudo()

            sessions = session_obj.search(session_domain)

            pending_approval_session = sessions.filtered(lambda s: s.state == 'Submitted')
            pending_approval = len(pending_approval_session)
            active_sessions = len(sessions.filtered(lambda s: s.state == 'In Progress'))
            re_sessions = len(sessions.filtered(lambda s: s.is_revision))

            session_line_domain = [('session_id', 'in', sessions.ids)] if sessions else [('id', '=', 0)]
            pending_review_lines = line_obj.search_count([('session_id', 'in', pending_approval_session.ids), ('state', '=', 'Pending Review')]) if pending_approval else 0
            rejected_lines = line_obj.search_count(session_line_domain + [('state', '=', 'Reject')])

            durations = []
            now_dt = fields.Datetime.now()
            for session in sessions:
                if not session.session_start_date:
                    continue
                end_dt = session.session_end_date or now_dt
                seconds = max(0.0, (end_dt - session.session_start_date).total_seconds())
                durations.append(seconds)

            avg_seconds = (sum(durations) / len(durations)) if durations else 0.0
            avg_hours = int(avg_seconds // 3600)
            avg_minutes = int((avg_seconds % 3600) // 60)
            avg_session_time = f"{avg_hours:02d}:{avg_minutes:02d}"

            user_workloads = self._get_operation_user_workloads(sessions, user_ids)
            rejection_by_location = self._get_operation_rejection_pct_by_location(sessions)
            pending_session_adjustments = self._get_operation_pending_session_adjustments(sessions)
            unscanned_sessions = self._get_operation_unscanned_sessions(sessions, user_ids=user_ids)
            user_scanned_vs_rejected = self._get_operation_user_scanned_vs_rejected(sessions, user_ids=user_ids)
            manager_activity = self._get_operation_manager_activity(sessions, user_ids=user_ids)

            return {
                'pending_approval': pending_approval,
                'active_sessions': active_sessions,
                'pending_review_lines': pending_review_lines,
                'avg_session_time': avg_session_time,
                're_sessions': re_sessions,
                'rejected_lines': rejected_lines,
                'user_workloads': user_workloads,
                'rejection_by_location': rejection_by_location,
                'pending_session_adjustments': pending_session_adjustments,
                'unscanned_sessions': unscanned_sessions,
                'user_scanned_vs_rejected': user_scanned_vs_rejected,
                'manager_activity': manager_activity,
            }
        except (ValidationError, UserError):
            raise
        except Exception as e:
            _logger.error("Error in get_operation_dashboard_data: %s", str(e))
            return {
                'pending_approval': 0,
                'active_sessions': 0,
                'pending_review_lines': 0,
                'avg_session_time': "00:00",
                're_sessions': 0,
                'rejected_lines': 0,
                'user_workloads': {'labels': [], 'values': []},
                'rejection_by_location': {'labels': [], 'values': []},
                'pending_session_adjustments': [],
                'unscanned_sessions': [],
                'user_scanned_vs_rejected': {'labels': [], 'scanned': [], 'rejected': [], 'user_ids': []},
                'manager_activity': [],
            }

    def _operation_session_qualifies_unscanned_list(self, session):
        """In-progress sessions with product backlog and/or assigned locations never scanned."""
        session.ensure_one()
        if session.state != 'Submitted':
            return False
        if session.to_be_scanned > 0:
            return True
        return self._operation_has_expected_location_without_scan(session)

    def _operation_has_expected_location_without_scan(self, session):
        """Assigned root locations with no scanned line in their subtree."""
        session.ensure_one()
        if not session.assigned_location_ids:
            return False
        location_obj = self.env['stock.location'].sudo()
        for assign in session.assigned_location_ids:
            child_ids = set(location_obj.search([('id', 'child_of', assign.id)]).ids)
            scanned_here = any(
                line.product_scanned and line.location_id and line.location_id.id in child_ids
                for line in session.session_line_ids
            )
            if not scanned_here:
                return True
        return False

    def _get_operation_unscanned_sessions(self, sessions, user_ids=None, limit=50):
        """Active sessions needing scans (products or locations)."""
        if not sessions:
            return []
        try:
            in_progress = sessions.filtered(lambda s: s.state == 'Submitted')
            if user_ids:
                in_progress = in_progress.filtered(
                    lambda s: any(u.id in user_ids for u in s.user_ids)
                )
            qualified = in_progress.filtered(
                lambda s: self._operation_session_qualifies_unscanned_list(s)
            )
            ordered = qualified.sorted(
                key=lambda s: (-len(s.unscanned_product_lines_ids), -s.to_be_scanned, -s.id)
            )
            rows = []
            for session in ordered[:limit]:
                users = ', '.join(session.user_ids.mapped('name')) if session.user_ids else '—'
                rows.append({
                    'id': session.id,
                    'session_name': session.display_name,
                    'user_names': users,
                    'total_products': session.total_products,
                    'unscanned_count': len(session.unscanned_product_lines_ids),
                })
            return rows
        except Exception as e:
            _logger.error("Error in _get_operation_unscanned_sessions: %s", str(e))
            return []

    def _get_operation_pending_session_adjustments(self, sessions, limit=40):
        """Session-linked inventory adjustments not yet validated (draft / in progress)."""
        if not sessions:
            return []
        try:
            sessions = sessions.filtered(lambda x: x.adjustment_strategy == 'session_level')
            adj_obj = self.env['setu.stock.inventory'].sudo()
            state_field = adj_obj._fields['state']
            sel = state_field.selection
            if callable(sel):
                sel = sel(adj_obj)
            state_selection = dict(sel)
            pending = adj_obj.search(
                [
                    ('session_id', 'in', sessions.ids),
                    ('state', 'in', ('draft', 'confirm')),
                ],
                order='write_date desc',
                limit=limit,
            )
            rows = []
            for adj in pending:
                currency = adj.currency_id
                symbol = (currency.symbol or '') if currency else ''
                disc_total = sum(abs(line.discrepancy_value or 0.0) for line in adj.line_ids)
                session = adj.session_id
                rows.append({
                    'id': adj.id,
                    'session_name': session.display_name if session else '—',
                    'line_count': adj.difference_line_count,
                    'discrepancy': f"{symbol}{disc_total:,.2f}",
                    'adjustment_name': adj.name or '—',
                    'status': state_selection.get(adj.state, adj.state),
                })
            return rows
        except Exception as e:
            _logger.error("Error in _get_operation_pending_session_adjustments: %s", str(e))
            return []

    def _get_operation_user_workloads(self, sessions, user_ids=None):
        """Active session count per user (workload balancing, idle users)."""
        active = sessions.filtered(lambda s: s.state in ['Draft', 'In Progress'])
        user_counts = defaultdict(int)
        for session in active:
            for user in session.user_ids:
                user_counts[user.id] += 1

        if user_ids:
            user_obj = self.env['res.users'].sudo()
            labels = []
            values = []
            user_ids_result = []
            for uid in user_ids:
                user = user_obj.browse(uid)
                if not user.exists():
                    continue
                labels.append(user.name or str(user.id))
                values.append(user_counts.get(user.id, 0))
                user_ids_result.append(user.id)
        else:
            if not user_counts:
                return {'labels': [], 'values': [], 'user_ids': []}
            sorted_items = sorted(
                user_counts.items(),
                key=lambda x: (-x[1], x[0]),
            )
            users = self.env['res.users'].sudo().browse([uid for uid, _ in sorted_items]).exists()
            id_to_user = {u.id: u for u in users}
            labels = []
            values = []
            user_ids_result = []
            for user_id, count in sorted_items:
                labels.append(id_to_user[user_id].name if user_id in id_to_user else str(user_id))
                values.append(count)
                user_ids_result.append(user_id)
        return {'labels': labels, 'values': values, 'user_ids': user_ids_result}

    def _get_operation_rejection_pct_by_location(self, sessions):
        """Rejected lines / scanned lines * 100 per location (session lines)."""
        if not sessions:
            return {'labels': [], 'values': [], 'location_ids': []}

        line_obj = self.env['setu.inventory.count.session.line'].sudo()
        lines = line_obj.search([('session_id', 'in', sessions.ids)])

        loc_scanned = defaultdict(int)
        loc_rejected = defaultdict(int)

        for line in lines:
            if not line.location_id:
                continue
            location_id = line.location_id.id
            is_scanned = bool(line.scanned_qty >= 0)
            if is_scanned:
                loc_scanned[location_id] += 1
            if line.state == 'Reject':
                loc_rejected[location_id] += 1

        location_ids = [lid for lid, cnt in loc_scanned.items() if cnt]
        if not location_ids:
            return {'labels': [], 'values': [], 'location_ids': []}

        location_obj = self.env['stock.location'].sudo()
        locations = location_obj.browse(location_ids).exists()
        id_to_loc = {loc.id: loc for loc in locations}

        pairs = []
        for lid in location_ids:
            scanned = loc_scanned.get(lid, 0)
            rejected = loc_rejected.get(lid, 0)
            if not scanned:
                continue
            pct = min(100.0, round((rejected / (scanned)) * 100.0, 2))
            loc_name = id_to_loc[lid].display_name if lid in id_to_loc else str(lid)
            if rejected > 0:
                pairs.append((loc_name, pct, lid))

        pairs.sort(key=lambda x: (-x[1], x[0]))
        return {
            'labels': [p[0] for p in pairs],
            'values': [p[1] for p in pairs],
            'location_ids': [p[2] for p in pairs],
        }

    def _get_operation_user_scanned_vs_rejected(self, sessions, user_ids=None):
        """Per-user session line counts: approved lines vs rejected lines."""
        if not sessions:
            return {'labels': [], 'scanned': [], 'rejected': [], 'user_ids': []}
        try:
            line_obj = self.env['setu.inventory.count.session.line'].sudo()
            lines = line_obj.search([('session_id', 'in', sessions.ids)])
            scanned_by_user = defaultdict(int)
            rejected_by_user = defaultdict(int)
            for line in lines:
                session = line.session_id
                users = line.user_ids if line.user_ids else session.user_ids
                if not users:
                    continue
                if line.state == 'Reject':
                    for user in users:
                        rejected_by_user[user.id] += 1
                elif line.state == 'Approve':
                    for user in users:
                        scanned_by_user[user.id] += 1

            if user_ids:
                user_obj = self.env['res.users'].sudo()
                labels = []
                scanned = []
                rejected = []
                selected_user_ids = []
                for uid in user_ids:
                    user = user_obj.browse(uid)
                    if not user.exists():
                        continue
                    labels.append(user.name or str(user.id))
                    scanned.append(scanned_by_user.get(uid, 0))
                    rejected.append(rejected_by_user.get(uid, 0))
                    selected_user_ids.append(uid)
                return {'labels': labels, 'scanned': scanned, 'rejected': rejected, 'user_ids': selected_user_ids}

            all_uids = set(scanned_by_user.keys()) | set(rejected_by_user.keys())
            if not all_uids:
                return {'labels': [], 'scanned': [], 'rejected': [], 'user_ids': []}
            sorted_uids = sorted(
                all_uids,
                key=lambda uid: (
                    -(scanned_by_user.get(uid, 0) + rejected_by_user.get(uid, 0)),
                    uid,
                ),
            )
            user_obj = self.env['res.users'].sudo()
            users = user_obj.browse(sorted_uids).exists()
            id_to_user = {u.id: u for u in users}
            labels = [id_to_user[i].name if i in id_to_user else str(i) for i in sorted_uids]
            scanned = [scanned_by_user.get(i, 0) for i in sorted_uids]
            rejected = [rejected_by_user.get(i, 0) for i in sorted_uids]
            return {'labels': labels, 'scanned': scanned, 'rejected': rejected, 'user_ids': sorted_uids}
        except Exception as e:
            _logger.error("Error in _get_operation_user_scanned_vs_rejected: %s", str(e))
            return {'labels': [], 'scanned': [], 'rejected': [], 'user_ids': []}

    def _get_operation_manager_activity(self, sessions, user_ids=None, limit=50):
        """In-progress sessions: user, session, location, last activity (session write_date)."""
        if not sessions:
            return []
        try:
            active = sessions.filtered(lambda s: s.state == 'In Progress')
            if user_ids:
                active = active.filtered(
                    lambda s: any(u.id in user_ids for u in s.user_ids)
                )
            ordered = active.sorted(
                key=lambda s: s.write_date or s.create_date,
                reverse=True,
            )
            rows = []
            for session in ordered[:limit]:
                users = ', '.join(session.user_ids.mapped('name')) if session.user_ids else '—'
                if session.current_scanning_location_id:
                    location = session.current_scanning_location_id.display_name
                elif session.location_id:
                    location = session.location_id.display_name
                elif session.assigned_location_ids:
                    location = ', '.join(session.assigned_location_ids.mapped('display_name')[:3])
                    if len(session.assigned_location_ids) > 3:
                        location = f"{location}, …"
                else:
                    location = '—'
                write_date = session.write_date
                if write_date:
                    write_date = fields.Datetime.context_timestamp(self, write_date)
                rows.append({
                    'id': session.id,
                    'user_names': users,
                    'session_name': session.display_name,
                    'location_name': location,
                    'write_date': fields.Datetime.to_string(write_date) if write_date else False,
                })
            return rows
        except Exception as e:
            _logger.error("Error in _get_operation_manager_activity: %s", str(e))
            return []
