# -*- coding: utf-8 -*-
from datetime import datetime
from odoo import models, fields, api
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)


class SetuInventoryDashboard(models.AbstractModel):
    _name = 'setu.inventory.dashboard'
    _description = 'Inventory Count Dashboard'

    def _get_active_company_ids(self):
        """Company ids constrained by active context and user access."""
        allowed_ctx = self.env.context.get('allowed_company_ids')
        if allowed_ctx is None:
            company_ids = list(self.env.companies.ids)
        elif isinstance(allowed_ctx, (list, tuple)):
            company_ids = list(allowed_ctx)
        else:
            company_ids = [allowed_ctx]

        if not company_ids and self.env.company:
            company_ids = [self.env.company.id]

        user_allowed_ids = set(self.env.user.company_ids.ids)
        if user_allowed_ids:
            company_ids = [cid for cid in company_ids if cid in user_allowed_ids]

        return list(dict.fromkeys(company_ids))

    def _get_valid_counts(self, counts):
        """Filter counts to only include valid states"""
        return counts.filtered(lambda c: c.state in ['Approved', 'Inventory Adjusted'])

    def _get_date_range(self, start_date, end_date):
        """Reusable method to parse and normalize date range"""
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
        return start_dt, end_dt

    def _build_base_domains(self, start_date, end_date, warehouse_ids=None, count_ids=None):
        """Build common domains for sessions and counts"""
        company_ids = self._get_active_company_ids()
        session_domain = [
            ('session_start_date', '>=', start_date),
            ('session_submit_date', '<=', end_date),
            ('state', 'not in', ['Draft', 'In Progress', 'Cancel']),
        ]

        count_domain = [
            ('inventory_count_date', '>=', start_date),
            ('inventory_count_date', '<=', end_date),
            ('state', 'in', ['Approved', 'Inventory Adjusted']),
        ]
        if company_ids:
            session_domain.append(('company_id', 'in', company_ids))
            count_domain.append(('company_id', 'in', company_ids))

        if warehouse_ids:
            session_domain.append(('warehouse_id', 'in', warehouse_ids))
            count_domain.append(('warehouse_id', 'in', warehouse_ids))

        if count_ids:
            count_domain.append(('id', 'in', count_ids))
            session_domain.append(('inventory_count_id', 'in', count_ids))

        return session_domain, count_domain

    def _get_filtered_sessions(self, domain, user_ids=None):
        """Get sessions with optional user filtering"""
        if user_ids:
            domain += ['|', ('user_ids', 'in', user_ids), ('approver_id', 'in', user_ids)]
        return self.env['setu.inventory.count.session'].sudo().search(domain)

    def _count_line_matches_user(self, line, user_ids):
        """True when selected user is a scanner or count approver."""
        return (
            any(user.id in user_ids for user in line.session_line_ids.mapped('session_id.user_ids'))
            or (line.inventory_count_id.approver_id and line.inventory_count_id.approver_id.id in user_ids)
        )

    def _is_user_mistake_line(self, session_line):
        """Session line is a user mistake if either session or count line is marked."""
        return bool(
            session_line.user_calculation_mistake
            or (session_line.inventory_count_line_id and session_line.inventory_count_line_id.user_calculation_mistake)
        )

    def _get_user_performance_rows(self, counts, user_ids=None):
        """Build unified rows for user performance by approval scope."""
        rows = []
        for count in counts:
            if count.approval_scope == 'session_level':
                lines = count.session_ids.mapped('session_line_ids').filtered(lambda line: line.product_scanned)
                for line in lines:
                    responsible_users = line.user_ids
                    if user_ids:
                        responsible_users = responsible_users.filtered(lambda user: user.id in user_ids)
                    for user in responsible_users:
                        rows.append({
                            'user_name': user.name,
                            'is_mistake': self._is_user_mistake_line(line),
                        })
            else:
                lines = count.line_ids.filtered(lambda line: line.state in ('Approve', 'Reject'))
                for line in lines:
                    responsible_users = line.user_ids
                    if user_ids:
                        responsible_users = responsible_users.filtered(lambda user: user.id in user_ids)
                    for user in responsible_users:
                        rows.append({
                            'user_name': user.name,
                            'is_mistake': bool(line.user_calculation_mistake),
                        })
        return rows

    def _get_filtered_counts(self, count_domain, sessions):
        """Get counts filtered by sessions"""
        if sessions:
            count_domain.append(('session_ids', 'in', sessions.ids))
        return self.env['setu.stock.inventory.count'].sudo().search(count_domain)

    def _format_duration(self, total_seconds):
        """Format seconds to HH:MM:SS"""
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @api.model
    def get_dashboard_data(self, start_date, end_date, warehouse_ids=None, user_ids=None, count_ids=None):
        """Get dashboard data for inventory count management"""
        try:
            start_dt, end_dt = self._get_date_range(start_date, end_date)
            session_domain, count_domain = self._build_base_domains(start_dt, end_dt, warehouse_ids, count_ids)

            # Get filtered sessions and counts
            sessions = self._get_filtered_sessions(session_domain, user_ids)
            counts = self._get_filtered_counts(count_domain, sessions)
            counts = self._get_valid_counts(counts)
            # Get pending sessions
            pending_sessions = self._get_filtered_sessions(
                session_domain + [('state', '=', 'Submitted')],
                user_ids
            )

            # Calculate KPIs
            return {
                'total_sessions_completed': self._get_total_sessions_completed(sessions),
                'pending_adjustments': self._get_pending_adjustments(counts, user_ids),
                'total_products_counted': self._get_total_products_counted(counts,user_ids),
                'global_accuracy': self._get_global_accuracy(counts,user_ids),
                'total_discrepancy_qty': self._get_total_discrepancy_qty(counts,user_ids),
                'total_inventory_loss': self._get_total_inventory_loss(counts,user_ids),
                'approvals_pending': self._get_approvals_pending(pending_sessions),
            }
        except Exception as e:
            _logger.error("Error in get_dashboard_data: %s", str(e))
            # Return default values on error
            return {
                'total_sessions_completed': 0,
                'pending_adjustments': 0,
                'total_products_counted': 0,
                'global_accuracy': 0.0,
                'total_discrepancy_qty': 0,
                'total_inventory_loss': 0.0,
                'approvals_pending': 0,
            }

    def _get_total_sessions_completed(self, sessions):
        """Count of all sessions in filter"""
        return len(sessions.filtered(lambda s: s.state in ['Done', 'Submitted']))

    def _get_avg_time_per_session(self, sessions):
        """Average time per session"""
        completed_sessions = sessions.filtered(lambda s: s.state in ['Done', 'Submitted'])
        if not completed_sessions:
            return self._format_duration(0)

        total_seconds = 0
        for session in completed_sessions:
            session_details = self.env['setu.inventory.session.details'].search([('session_id', '=', session.id)])
            total_seconds += sum(session_details.mapped('duration_seconds'))

        avg_seconds = total_seconds / len(completed_sessions)
        return self._format_duration(avg_seconds)

    def _get_pending_adjustments(self, counts, user_ids=None):
        """Total pending inventory adjustments linked to filtered counts."""
        adjustment_domain = [
            ('inventory_count_id', 'in', counts.ids),
            ('state', 'in', ['draft', 'confirm']),
        ]
        adjustments = self.env['setu.stock.inventory'].sudo().search(adjustment_domain)
        if user_ids:
            adjustments = adjustments.filtered(
                lambda adj: (
                    any(user.id in user_ids for user in adj.session_id.user_ids)
                    or any(user.id in user_ids for user in adj.inventory_count_id.session_ids.mapped('user_ids'))
                )
            )
        return len(adjustments)

    def _get_total_products_counted(self, counts, user_ids=None):
        """Unique products counted by selected users"""
        count_lines = counts.mapped("line_ids")
        if user_ids:
            count_lines = count_lines.filtered(
                lambda cl: self._count_line_matches_user(cl, user_ids)
            )
        product_ids = count_lines.mapped("product_id").ids
        return len(set(product_ids))

    def _get_global_accuracy(self, counts, user_ids=None):
        """Calculate accuracy ratio based on user mistakes."""
        rows = self._get_user_performance_rows(counts, user_ids)
        if not rows:
            return 0.0
        mistake_count = sum(1 for row in rows if row['is_mistake'])
        accuracy_ratio = ((len(rows) - mistake_count) / len(rows)) * 100
        return round(accuracy_ratio, 2)

    def _get_total_discrepancy_qty(self, counts, user_ids=None):
        """Total number of discrepancies found by selected users"""
        if not counts:
            return 0
        count_lines = counts.mapped("line_ids")
        if user_ids:
            count_lines = count_lines.filtered(
                lambda cl: self._count_line_matches_user(cl, user_ids)
            )
        return len(count_lines.filtered(lambda l: l.is_discrepancy_found))

    def _get_total_inventory_loss(self, counts, user_ids=None):
        """Total inventory loss value for selected users"""
        if not counts:
            return 0.0
        count_lines = counts.mapped("line_ids")
        if user_ids:
            count_lines = count_lines.filtered(
                lambda cl: self._count_line_matches_user(cl, user_ids)
            )
        loss_lines = count_lines.filtered(
            lambda l: l.is_discrepancy_found and l.difference_qty < 0.0)
        return abs(sum(loss_lines.mapped('discrepancy_value')))

    def _get_approvals_pending(self, sessions):
        """Number of sessions pending approval"""
        return len(sessions)

    @api.model
    def get_warehouse_list(self):
        """Get list of warehouses for filter"""
        company_ids = self._get_active_company_ids()
        warehouse_domain = [('company_id', 'in', company_ids)] if company_ids else []
        warehouses = self.env['stock.warehouse'].search(warehouse_domain)
        return [{'id': w.id, 'name': w.name} for w in warehouses]

    @api.model
    def get_user_list(self):
        """Get inventory users only (exclude approver/manager)."""
        company_ids = self._get_active_company_ids()
        domain = [('active', '=', True), ('share', '=', False)]
        if company_ids:
            domain += ['|', ('company_id', 'in', company_ids), ('company_ids', 'in', company_ids)]
        user_group = self.env.ref(
            'setu_inventory_count_management.group_setu_inventory_count_user',
            raise_if_not_found=False,
        )
        approver_group = self.env.ref(
            'setu_inventory_count_management.group_setu_inventory_count_approver',
            raise_if_not_found=False,
        )
        manager_group = self.env.ref(
            'setu_inventory_count_management.group_setu_inventory_count_manager',
            raise_if_not_found=False,
        )
        if user_group:
            domain.append(('groups_id', 'in', [user_group.id]))
        excluded_group_ids = [group.id for group in (approver_group, manager_group) if group]
        if excluded_group_ids:
            domain.append(('groups_id', 'not in', excluded_group_ids))
        users = self.env['res.users'].search(domain)
        return [{'id': u.id, 'name': u.name} for u in users]

    @api.model
    def get_count_list(self, user_ids):
        """Get list of inventory counts for filter, filtered by selected users and company."""
        company_ids = self._get_active_company_ids()
        domain = [('state', 'in', ['Approved', 'Inventory Adjusted'])]
        if company_ids:
            domain.append(('company_id', 'in', company_ids))
        counts = self.env['setu.stock.inventory.count'].sudo().search(domain)
        if user_ids:
            counts = counts.filtered(
                lambda count: (
                    any(user.id in user_ids for user in count.session_ids.mapped('user_ids'))
                    or (count.approver_id and count.approver_id.id in user_ids)
                )
            )
        return [{'id': c.id, 'name': c.name} for c in counts]

    def _get_chart_data_domains(self, start_date, end_date, warehouse_ids=None, user_ids=None, count_ids=None):
        """Build common domains for chart data"""
        start_dt, end_dt = self._get_date_range(start_date, end_date)
        company_ids = self._get_active_company_ids()

        session_domain = [
            ('session_start_date', '>=', start_dt),
            ('session_submit_date', '<=', end_dt),
            ('session_id', '=', False),
            ('state', 'not in', ['Draft', 'In Progress', 'Cancel']),
        ]

        count_domain = [
            ('inventory_count_date', '>=', start_dt),
            ('inventory_count_date', '<=', end_dt),
        ]
        if company_ids:
            session_domain.append(('company_id', 'in', company_ids))
            count_domain.append(('company_id', 'in', company_ids))

        if warehouse_ids:
            session_domain.append(('warehouse_id', 'in', warehouse_ids))
            count_domain.append(('warehouse_id', 'in', warehouse_ids))

        if count_ids:
            count_domain.append(('id', 'in', count_ids))
            session_domain.append(('inventory_count_id', 'in', count_ids))

        return session_domain, count_domain, start_dt, end_dt

    def _get_user_mistakes_data(self, performance_rows):
        """Get user mistakes vs accuracy data in percentages."""
        user_to_stats = defaultdict(lambda: {'accurate': 0, 'mistake': 0, 'total': 0})

        for row in performance_rows:
            key = row['user_name']
            user_to_stats[key]['total'] += 1
            if row['is_mistake']:
                user_to_stats[key]['mistake'] += 1
            else:
                user_to_stats[key]['accurate'] += 1

        users_labels = list(user_to_stats.keys())
        return {
            'labels': users_labels,
            'accurate': [
                round((user_to_stats[name]['accurate'] / (user_to_stats[name]['total'] or 1)) * 100, 2)
                for name in users_labels
            ],
            'mistake': [
                round((user_to_stats[name]['mistake'] / (user_to_stats[name]['total'] or 1)) * 100, 2)
                for name in users_labels
            ],
        }

    def _get_discrepancy_by_location_data(self, count_lines):
        """Get discrepancy data grouped by location"""
        loc_to_count = defaultdict(int)
        for line in count_lines:
            if line.is_discrepancy_found:
                key = line.location_id.display_name or 'N/A'
                loc_to_count[key] += 1

        loc_labels = list(loc_to_count.keys())
        return {
            'labels': loc_labels,
            'values': [loc_to_count[key] for key in loc_labels],
        }

    def _get_discrepancy_trend_data(self, count_lines):
        """Get discrepancy trend over time"""
        company_ids = self._get_active_company_ids()
        if company_ids:
            count_lines = count_lines.filtered(
                lambda line: line.inventory_count_id.company_id.id in company_ids
            )
        date_to_value = defaultdict(float)
        for line in count_lines:
            count_date = line.inventory_count_id.inventory_count_date
            if count_date:
                date_to_value[count_date] += line.discrepancy_value or 0.0

        sorted_dates = sorted(date_to_value.keys())
        return {
            'labels': [d.strftime('%Y-%m-%d') for d in sorted_dates],
            'values': [round(date_to_value[d], 2) for d in sorted_dates],
        }

    def _get_top_products_loss_data(self, count_lines):
        """Get top 10 products by loss"""
        loss_lines = count_lines.filtered(lambda cl: cl.discrepancy_value < 0)
        prod_to_loss = defaultdict(float)

        for line in loss_lines:
            product_name = line.product_id.display_name
            prod_to_loss[product_name] += line.discrepancy_value

        top_items = sorted(prod_to_loss.items(), key=lambda x: x[1])[:10]
        return {
            'labels': [name for name, _ in top_items],
            'values': [round(value, 2) for _, value in top_items],
        }

    def _get_mistake_reasons_data(self, performance_rows):
        """Get mistake reasons distribution"""
        user_mistakes = sum(1 for row in performance_rows if row['is_mistake'])
        system_mistakes = len(performance_rows) - user_mistakes

        total = user_mistakes + system_mistakes
        user_percent = round((user_mistakes / (total or 1)) * 100, 2)
        system_percent = round((system_mistakes / (total or 1)) * 100, 2)

        return {
            'labels': ['User Mistakes', 'System Mistakes'],
            'values': [user_percent, system_percent],
        }

    @api.model
    def get_chart_data(self, start_date, end_date, warehouse_ids=None, user_ids=None, count_ids=None):
        """Returns datasets for all charts based on the same filters as the KPIs."""
        try:
            session_domain, count_domain, start_dt, end_dt = self._get_chart_data_domains(
                start_date, end_date, warehouse_ids, user_ids, count_ids
            )

            # Get sessions and counts
            sessions = self._get_filtered_sessions(session_domain, user_ids)
            counts = self.env['setu.stock.inventory.count'].sudo().search(count_domain)

            # Get session lines and count lines
            session_lines = sessions.mapped('session_line_ids')
            counts = self._get_valid_counts(counts)
            count_lines = counts.mapped('line_ids')

            # Apply user filters to lines
            if user_ids:
                session_lines = session_lines.filtered(
                    lambda sl: any(user.id in user_ids for user in sl.user_ids)
                )
                count_lines = count_lines.filtered(
                    lambda cl: self._count_line_matches_user(cl, user_ids)
                )

            performance_rows = self._get_user_performance_rows(counts, user_ids)

            # Build chart data
            return {
                'users': self._get_user_mistakes_data(performance_rows),
                'discrepancy_by_location': self._get_discrepancy_by_location_data(count_lines),
                'discrepancy_trend': self._get_discrepancy_trend_data(count_lines),
                'top_products_loss': self._get_top_products_loss_data(count_lines),
                'mistake_reasons': self._get_mistake_reasons_data(performance_rows),
            }
        except Exception as e:
            _logger.error("Error in get_chart_data: %s", str(e))
            # Return default empty chart data on error
            return {
                'users': { 'labels': [], 'accurate': [], 'mistake': [] },
                'discrepancy_by_location': { 'labels': [], 'values': [] },
                'discrepancy_trend': { 'labels': [], 'values': [] },
                'top_products_loss': { 'labels': [], 'values': [] },
                'mistake_reasons': { 'labels': [], 'values': [] },
            }

    def _get_table_data_domains(self, start_date, end_date, warehouse_ids=None, count_ids=None):
        """Build common domains for table data"""
        start_dt, end_dt = self._get_date_range(start_date, end_date)
        company_ids = self._get_active_company_ids()

        session_domain = [
            ('session_start_date', '>=', start_dt),
            ('session_start_date', '<=', end_dt),
        ]

        count_domain = [
            ('inventory_count_date', '>=', start_dt),
            ('inventory_count_date', '<=', end_dt),
            ('state','in',['Approved', 'Inventory Adjusted'])
        ]
        if company_ids:
            session_domain.append(('company_id', 'in', company_ids))
            count_domain.append(('company_id', 'in', company_ids))

        if warehouse_ids:
            session_domain.append(('warehouse_id', 'in', warehouse_ids))
            count_domain.append(('warehouse_id', 'in', warehouse_ids))

        if count_ids:
            count_domain.append(('id', 'in', count_ids))
            session_domain.append(('inventory_count_id', 'in', count_ids))

        return session_domain, count_domain

    def _get_open_sessions(self, domain, user_ids=None):
        """Get data for Open Sessions table"""
        try:
            local_domain = domain + [('state', 'in', ['In Progress', 'Submitted'])]
            if user_ids:
                local_domain.append(('user_ids', 'in', user_ids))
            sessions = self.env['setu.inventory.count.session'].sudo().search(
                local_domain, limit=6, order='session_start_date desc'
            )

            return [{
                'id': s.id,
                'name': s.name or 'N/A',
                'warehouse': s.warehouse_id.name if s.warehouse_id else 'N/A',
                'users': ', '.join(s.user_ids.mapped('name')) if s.user_ids else 'N/A',
                'start_time': s.session_start_date.strftime('%Y-%m-%d %H:%M') if s.session_start_date else 'N/A',
            } for s in sessions]
        except Exception as e:
            _logger.error("Error in _get_open_sessions: %s", str(e))
            return []

    def _get_recent_adjustments(self, count_domain, user_ids=None):
        """Get validated adjustments generated from inventory counts."""
        try:
            count_model = self.env['setu.stock.inventory.count'].sudo()
            inventory_model = self.env['setu.stock.inventory'].sudo()
            company_ids = self._get_active_company_ids()

            counts = count_model.search(count_domain)

            if user_ids:
                counts = counts.filtered(
                    lambda c: (
                        any(user.id in user_ids for user in c.session_ids.mapped('user_ids'))
                        or (c.approver_id and c.approver_id.id in user_ids)
                    )
                )

            inventory_domain = [('state', '=', 'done'), ('inventory_count_id', 'in', counts.ids)]
            if company_ids:
                inventory_domain.append(('company_id', 'in', company_ids))

            inventories = inventory_model.search(
                inventory_domain,
                order='date desc, id desc',
                limit=10
            )

            lines = inventories.mapped('line_ids').filtered(lambda line: (line.difference_qty or 0.0) != 0.0)

            return [{
                'row_id': line.id,
                'id': line.inventory_id.id or 0,
                'model': 'setu.stock.inventory',
                'name': line.inventory_id.name or 'N/A',
                'product': line.product_id.display_name or 'N/A',
                'theoretical': line.theoretical_qty or 0,
                'counted': line.product_qty or 0,
                'adjustment_qty': line.difference_qty or 0,
                'adjustment_value': f"₹{abs(line.discrepancy_value or 0):.2f}",
            } for line in lines[:10]]
        except Exception as e:
            _logger.error("Error in _get_recent_adjustments: %s", str(e))
            return []

    def _get_high_risk_products(self, count_domain, user_ids=None):
        """Get unified product risk table data."""
        try:
            counts = self.env['setu.stock.inventory.count'].sudo().search(count_domain, order='inventory_count_date desc')
            all_lines = counts.mapped('line_ids')

            if user_ids:
                all_lines = all_lines.filtered(
                    lambda l: self._count_line_matches_user(l, user_ids)
                )

            product_stats = {}
            for line in all_lines:
                product = line.product_id
                if not product:
                    continue

                if product.id not in product_stats:
                    product_stats[product.id] = {
                        'product_id': product.id,
                        'name': product.display_name,
                        'total_scanned_count': 0,
                        'discrepancy_frequency': 0,
                        'total_loss_amount': 0.0,
                        'total_discrepancy_qty': 0.0,
                    }

                stats = product_stats[product.id]
                stats['total_scanned_count'] += 1

                if line.is_discrepancy_found:
                    stats['discrepancy_frequency'] += 1
                    stats['total_discrepancy_qty'] += abs(line.difference_qty or 0.0)
                    # Financial impact remains loss-focused.
                    if (line.difference_qty or 0.0) < 0.0:
                        stats['total_loss_amount'] += abs(line.discrepancy_value or 0.0)

            risk_rows = []
            for stats in product_stats.values():
                if not stats['discrepancy_frequency']:
                    continue
                discrepancy_ratio = (
                    (stats['discrepancy_frequency'] / stats['total_scanned_count']) * 100.0
                    if stats['total_scanned_count'] else 0.0
                )
                avg_discrepancy_qty = stats['total_discrepancy_qty'] / stats['discrepancy_frequency']
                risk_rows.append({
                    'id': stats['product_id'],
                    'model': 'product.product',
                    'name': stats['name'],
                    'discrepancy_frequency': stats['discrepancy_frequency'],
                    'total_loss_amount': round(stats['total_loss_amount'], 2),
                    'avg_discrepancy_qty': round(avg_discrepancy_qty, 2),
                    'discrepancy_ratio': round(discrepancy_ratio, 2),
                })

            sorted_rows = sorted(
                risk_rows,
                key=lambda row: (
                    row['discrepancy_frequency'],
                    row['discrepancy_ratio'],
                    row['total_loss_amount'],
                ),
                reverse=True,
            )
            return sorted_rows[:10]
        except Exception as e:
            _logger.error("Error in _get_high_risk_products: %s", str(e))
            return []

    @api.model
    def get_table_data(self, start_date, end_date, warehouse_ids=None, user_ids=None, count_ids=None):
        """Get data for the drill-down tables."""
        try:
            session_domain, count_domain = self._get_table_data_domains(
                start_date, end_date, warehouse_ids, count_ids
            )

            return {
                'open_sessions': self._get_open_sessions(session_domain, user_ids),
                'recent_adjustments': self._get_recent_adjustments(count_domain, user_ids),
                'high_risk_products': self._get_high_risk_products(count_domain, user_ids),
            }
        except Exception as e:
            _logger.error("Error in get_table_data: %s", str(e))
            return {
                'open_sessions': [],
                'recent_adjustments': [],
                'high_risk_products': [],
            }

