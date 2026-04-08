/** @odoo-module **/

import { registry } from '@web/core/registry';
import { useService } from "@web/core/utils/hooks";
import { session } from '@web/session';
import { loadJS } from "@web/core/assets";
// V18 Adaptation: Import Component and hooks - adjust based on your v18 OWL version
import { Component, onMounted, useState, onWillStart } from "@odoo/owl";

export class SetuInventoryDashboard extends Component {
    setup() {
        // V18 Adaptation: Try useService first, fallback to env.services if needed
        try {
            this.actionService = useService("action");
            this.notification = useService("notification");
            this.orm = useService('orm');
        } catch (e) {
            // Fallback for v18 if useService doesn't work
            this.actionService = this.env.services.action;
            this.notification = this.env.services.notification;
            this.orm = this.env.services.orm;
        }
        
        // Get company ID from session context (standard Odoo approach)
        this.current_company_id = session.user_context?.company_id || 
                                   (session.user_context?.allowed_company_ids && session.user_context.allowed_company_ids[0]) || 
                                   null;
        const context = session.user_context;
        this.formatNumber = (val) => {
            return Number(val || 0).toLocaleString();
        };

        this.dashboardData = useState({
            totalSessionsCompleted: 0,
            avgTimePerSession: "00:00:00",
            totalProductsCounted: 0,
            globalAccuracy: 0,
            totalDiscrepancyQty: 0,
            totalInventoryLoss: 0,
            approvalsPending: 0
        });

        this.chartData = useState({
            users: { labels: [], accurate: [], mistake: [] },
            discrepancy_by_location: { labels: [], values: [] },
            discrepancy_trend: { labels: [], values: [] },
            top_products_loss: { labels: [], values: [] },
            mistake_reasons: { labels: [], values: [] }
        });

        this.tableData = useState({
            openSessions: [],
            recentAdjustments: [],
            highRiskProducts: []
        });

        // Initialize date state for template binding
        const today = new Date();
        const start_date = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().split('T')[0];
        const end_date = new Date(today.getFullYear(), today.getMonth() + 1, 0).toISOString().split('T')[0];
        
        this.dateState = useState({
            startDate: start_date,
            endDate: end_date
        });

        onWillStart(async () => {
            // Load initial data
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js");
            await this.loadDashboardData(start_date, end_date);
            await this.loadAllCharts(start_date, end_date, null, null, null);
            await this.loadTableData(start_date, end_date, null, null, null);
        });

        onMounted(async () => {
            await this.loadFilterOptions();
            this.initializeDashboard();

            // Force enable scrolling
            this.forceEnableScrolling();

            // Ensure charts are rendered after DOM is fully ready
            setTimeout(() => {
                this.renderAllCharts();
            }, 100);
        });
    }

    async loadDashboardData(startDate, endDate, warehouseIds = null, userIds = null, sessionIds = null) {
        try {
            const context = { ...session.user_context, start_date: startDate, end_date: endDate };
            const data = await this.orm.call(
                'setu.inventory.dashboard',
                'get_dashboard_data',
                [startDate, endDate, warehouseIds, userIds, sessionIds],
                { context }
            );

            this.dashboardData.totalSessionsCompleted = data.total_sessions_completed;
            this.dashboardData.avgTimePerSession = data.avg_time_per_session;
            this.dashboardData.totalProductsCounted = data.total_products_counted;
            this.dashboardData.globalAccuracy = data.global_accuracy;
            this.dashboardData.totalDiscrepancyQty = data.total_discrepancy_qty;
            this.dashboardData.totalInventoryLoss = data.total_inventory_loss;
            this.dashboardData.approvalsPending = data.approvals_pending;

        } catch (error) {
            console.error("Error loading dashboard data:", error);
            this.notification.add("Error loading dashboard data", { type: "danger" });
        }
    }

    chartInstances = {
        usersAccuracy: null,
        discrepancyLocation: null,
        discrepancyTrend: null,
        topProductsLoss: null,
        mistakeReasons: null,
    };

    async loadAllCharts(startDate, endDate, warehouseIds = null, userIds = null, sessionIds = null) {
        try {
            const context = { ...session.user_context, start_date: startDate, end_date: endDate };
            const data = await this.orm.call(
                'setu.inventory.dashboard',
                'get_chart_data',
                [startDate, endDate, warehouseIds, userIds, sessionIds],
                { context }
            );

            // Update chart data state with fallback for empty data
            this.chartData.users = data.users || { labels: ['No Data'], accurate: [0], mistake: [0] };
            this.chartData.discrepancy_by_location = data.discrepancy_by_location || { labels: ['No Data'], values: [0] };
            this.chartData.discrepancy_trend = data.discrepancy_trend || { labels: ['No Data'], values: [0] };
            this.chartData.top_products_loss = data.top_products_loss || { labels: ['No Data'], values: [0] };
            this.chartData.mistake_reasons = data.mistake_reasons || { labels: ['No Data'], values: [1] };

            // Render charts with updated data
            this.renderAllCharts();
        } catch (e) {
            console.error("loadAllCharts error:", e);
        }
    }

    async loadTableData(startDate, endDate, warehouseIds = null, userIds = null, sessionIds = null) {
        try {
            const context = { ...session.user_context, start_date: startDate, end_date: endDate };
            const data = await this.orm.call(
                'setu.inventory.dashboard',
                'get_table_data',
                [startDate, endDate, warehouseIds, userIds, sessionIds],
                { context }
            );

            this.tableData.openSessions = data.open_sessions || [];
            this.tableData.recentAdjustments = data.recent_adjustments || [];
            this.tableData.highRiskProducts = data.high_risk_products || [];

        } catch (error) {
            console.error("Error loading table data:", error);
            this.notification.add("Error loading drill-down tables", { type: "danger" });
        }
    }

    async loadFilterOptions() {
        try {
            const warehouseSelect = document.getElementById('warehouseFilter');
            const userSelect = document.getElementById('userFilter');
            const sessionSelect = document.getElementById('sessionFilter');

            if (warehouseSelect) {
                warehouseSelect.innerHTML = '<option value="">All Warehouses</option>';
            }
            if (userSelect) {
                userSelect.innerHTML = '<option value="">All Users</option>';
            }
            if (sessionSelect) {
                sessionSelect.innerHTML = '<option value="">All Sessions</option>';
            }

            const warehouses = await this.orm.call('setu.inventory.dashboard', 'get_warehouse_list', []);
            if (warehouseSelect) {
                warehouses.forEach(warehouse => {
                    const option = document.createElement('option');
                    option.value = warehouse.id;
                    option.textContent = warehouse.name;
                    warehouseSelect.appendChild(option);
                });
            }

            const users = await this.orm.call('setu.inventory.dashboard', 'get_user_list', []);
            if (userSelect) {
                users.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.id;
                    option.textContent = user.name;
                    userSelect.appendChild(option);
                });
            }

            const currentUserId = userSelect ? userSelect.value : null;
            const userIds = currentUserId ? [parseInt(currentUserId)] : null;

            const sessions = await this.orm.call('setu.inventory.dashboard', 'get_session_list', [userIds]);
            if (sessionSelect) {
                sessions.forEach(session => {
                    const option = document.createElement('option');
                    option.value = session.id;
                    option.textContent = session.name;
                    sessionSelect.appendChild(option);
                });
            }

        } catch (error) {
            console.error("Error loading filter options:", error);
        }
    }

    async initializeDashboard() {
        const startDateInput = document.getElementById('startDate');
        const endDateInput = document.getElementById('endDate');
        const warehouseFilter = document.getElementById('warehouseFilter');
        const userFilter = document.getElementById('userFilter');
        const sessionFilter = document.getElementById('sessionFilter');

        // Restore saved filters
        const savedFilters = JSON.parse(localStorage.getItem('inventoryDashboardFilters') || '{}');

        if (savedFilters.startDate && savedFilters.endDate) {
            startDateInput.value = savedFilters.startDate;
            endDateInput.value = savedFilters.endDate;
            this.dateState.startDate = savedFilters.startDate;
            this.dateState.endDate = savedFilters.endDate;
        } else {
            const today = new Date();
            const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
            const endOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0);

            const startDateStr = startOfMonth.toISOString().split('T')[0];
            const endDateStr = endOfMonth.toISOString().split('T')[0];
            startDateInput.value = startDateStr;
            endDateInput.value = endDateStr;
            this.dateState.startDate = startDateStr;
            this.dateState.endDate = endDateStr;
        }

        if (savedFilters.warehouseId && warehouseFilter) warehouseFilter.value = savedFilters.warehouseId;
        if (savedFilters.userId && userFilter) userFilter.value = savedFilters.userId;
        if (savedFilters.sessionId && sessionFilter) sessionFilter.value = savedFilters.sessionId;

        this.setupEventListeners();

        await this.loadDashboardData(
            startDateInput.value,
            endDateInput.value,
            savedFilters.warehouseId ? [parseInt(savedFilters.warehouseId)] : null,
            savedFilters.userId ? [parseInt(savedFilters.userId)] : null,
            savedFilters.sessionId ? [parseInt(savedFilters.sessionId)] : null
        );

        await this.loadAllCharts(
            startDateInput.value,
            endDateInput.value,
            savedFilters.warehouseId ? [parseInt(savedFilters.warehouseId)] : null,
            savedFilters.userId ? [parseInt(savedFilters.userId)] : null,
            savedFilters.sessionId ? [parseInt(savedFilters.sessionId)] : null
        );

        await this.loadTableData(
            startDateInput.value,
            endDateInput.value,
            savedFilters.warehouseId ? [parseInt(savedFilters.warehouseId)] : null,
            savedFilters.userId ? [parseInt(savedFilters.userId)] : null,
            savedFilters.sessionId ? [parseInt(savedFilters.sessionId)] : null
        );

        this.updateDisplay();
    }

    setupEventListeners() {
        if (this.eventListenersSetup) {
            return;
        }
        this.eventListenersSetup = true;

        const startDateInput = document.getElementById('startDate');
        const endDateInput = document.getElementById('endDate');
        const warehouseFilter = document.getElementById('warehouseFilter');
        const userFilter = document.getElementById('userFilter');
        const sessionFilter = document.getElementById('sessionFilter');

        const handleFilterChange = () => this.onFilterChange();
        const handleUserFilterChange = async () => {
            const userId = userFilter.value;
            const userIds = userId ? [parseInt(userId)] : null;

            const sessions = await this.orm.call('setu.inventory.dashboard', 'get_session_list', [userIds]);
            const sessionSelect = document.getElementById('sessionFilter');
            if (sessionSelect) {
                const currentValue = sessionSelect.value;
                sessionSelect.innerHTML = '<option value="">All Sessions</option>';
                sessions.forEach(session => {
                    const option = document.createElement('option');
                    option.value = session.id;
                    option.textContent = session.name;
                    sessionSelect.appendChild(option);
                });
                if (currentValue) {
                    sessionSelect.value = currentValue;
                }
            }
            await this.onFilterChange();
        };

        if (startDateInput) startDateInput.addEventListener('change', handleFilterChange);
        if (endDateInput) endDateInput.addEventListener('change', handleFilterChange);
        if (warehouseFilter) warehouseFilter.addEventListener('change', handleFilterChange);
        if (userFilter) userFilter.addEventListener('change', handleUserFilterChange);
        if (sessionFilter) sessionFilter.addEventListener('change', handleFilterChange);

        const kpiCards = document.querySelectorAll('.kpi-card');
        kpiCards.forEach(card => {
            card.addEventListener('click', () => this.onKpiCardClick(card));
        });
    }

    async onFilterChange() {
        const startDate = this.dateState?.startDate || document.getElementById('startDate')?.value;
        const endDate = this.dateState?.endDate || document.getElementById('endDate')?.value;
        const warehouseId = document.getElementById('warehouseFilter')?.value;
        const userId = document.getElementById('userFilter')?.value;
        const sessionId = document.getElementById('sessionFilter')?.value;

        localStorage.setItem('inventoryDashboardFilters', JSON.stringify({
            startDate,
            endDate,
            warehouseId,
            userId,
            sessionId
        }));

        if (!startDate || !endDate) {
            this.notification.add("Please select both start and end dates", { type: "warning" });
            return;
        }

        if (new Date(endDate) < new Date(startDate)) {
            this.notification.add("End date cannot be earlier than start date", { type: "danger" });
            return;
        }

        const warehouseIds = warehouseId ? [parseInt(warehouseId)] : null;
        const userIds = userId ? [parseInt(userId)] : null;
        const sessionIds = sessionId ? [parseInt(sessionId)] : null;

        await this.loadDashboardData(startDate, endDate, warehouseIds, userIds, sessionIds);
        await this.loadAllCharts(startDate, endDate, warehouseIds, userIds, sessionIds);
        await this.loadTableData(startDate, endDate, warehouseIds, userIds, sessionIds);
        this.updateDisplay();
    }

    onKpiCardClick(card) {
        const action = card.getAttribute('data-action');
        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;
        const warehouseId = document.getElementById('warehouseFilter').value;
        const userId = document.getElementById('userFilter').value;

        let domain = [];
        let count_domain = [];
        if (startDate && endDate) {
            domain.push(['session_start_date', '>=', startDate]);
            domain.push(['session_submit_date', '<=', endDate]);
            count_domain.push(['inventory_count_date', '>=', startDate]);
            count_domain.push(['inventory_count_date', '<=', endDate]);
        }
        if (warehouseId) {
            domain.push(['warehouse_id', '=', parseInt(warehouseId)]);
            count_domain.push(['warehouse_id', '=', parseInt(warehouseId)]);
        }

        switch (action) {
            case 'sessions':
                this.openSessions(domain);
                break;
            case 'products':
                this.openProducts(count_domain);
                break;
            case 'accuracy':
                this.openAccuracyReport(count_domain);
                break;
            case 'discrepancy':
                this.openDiscrepancyReport(count_domain);
                break;
            case 'loss':
                this.openInventoryLossReport(count_domain);
                break;
            case 'approvals':
                this.openApprovals(domain);
                break;
        }
    }

    openSessions(domain) {
        const userId = document.getElementById('userFilter').value;
        if (userId) {
            domain = [...domain, ['user_ids', 'in', [parseInt(userId)]]];
        }
        domain.push(['state', 'not in', ['Draft', 'In Progress', 'Cancel']]);
        this.actionService.doAction({
            name: 'Inventory Count Sessions',
            type: 'ir.actions.act_window',
            res_model: 'setu.inventory.count.session',
            // V18 Adaptation: Use 'tree' instead of 'list'
            view_mode: 'kanban,tree,form',
            views: [[false, 'kanban'], [false, 'tree'], [false, 'form']],
            domain: domain
        });
    }

    async openProducts(count_domain) {
        const userId = document.getElementById('userFilter').value;
        const userIds = userId ? [parseInt(userId)] : null;
        const product_ids = await this.orm.call(
            "setu.stock.inventory.count",
            "get_counted_products",
            [count_domain, userIds]
        );
        this.actionService.doAction({
            name: 'Counted Products',
            type: 'ir.actions.act_window',
            res_model: 'product.product',
            // V18 Adaptation: Use 'tree' instead of 'list'
            views: [[false, 'tree'], [false, 'form']],
            domain: [['id', 'in', product_ids]],
        });
    }

    openAccuracyReport(count_domain) {
        this.actionService.doAction({
            name: 'Inventory Count',
            type: 'ir.actions.act_window',
            res_model: 'setu.stock.inventory.count',
            // V18 Adaptation: Use 'tree' instead of 'list'
            view_mode: 'tree,form',
            views: [[false, 'tree'], [false, 'form']],
            domain: count_domain
        });
    }

    openDiscrepancyReport(count_domain) {
        const userId = document.getElementById('userFilter').value;
        const discrepancy_domain = [
            ...count_domain,
            ['line_ids.is_discrepancy_found', '=', true],
            ['state', 'in', ['Approved', 'Inventory Adjusted']]
        ];
        if (userId) {
            discrepancy_domain.push(['line_ids.user_ids', 'in', [parseInt(userId)]]);
        }
        this.actionService.doAction({
            name: 'Discrepancy',
            type: 'ir.actions.act_window',
            res_model: 'setu.stock.inventory.count',
            // V18 Adaptation: Use 'tree' instead of 'list'
            view_mode: 'tree,form',
            views: [[false, 'tree'], [false, 'form']],
            domain: discrepancy_domain
        });
    }

    openInventoryLossReport(count_domain) {
        const userId = document.getElementById('userFilter').value;
        const loss_domain = [
            ...count_domain,
            ['line_ids.is_discrepancy_found', '=', true],
            ['state', 'in', ['Approved', 'Inventory Adjusted']]
        ];
        if (userId) {
            loss_domain.push(['line_ids.user_ids', 'in', [parseInt(userId)]]);
        }
        this.actionService.doAction({
            name: 'Inventory Loss',
            type: 'ir.actions.act_window',
            res_model: 'setu.stock.inventory.count',
            // V18 Adaptation: Use 'tree' instead of 'list'
            view_mode: 'tree,form',
            views: [[false, 'tree'], [false, 'form']],
            domain: loss_domain
        });
    }

    openApprovals(domain) {
        const userId = document.getElementById('userFilter').value;
        domain = [...domain, ['state', '=', 'Submitted']];
        if (userId) {
            domain.push(['user_ids', 'in', [parseInt(userId)]]);
        }
        this.actionService.doAction({
            name: 'Pending Approvals',
            type: 'ir.actions.act_window',
            res_model: 'setu.inventory.count.session',
            // V18 Adaptation: Use 'tree' instead of 'list'
            view_mode: 'kanban,tree,form',
            views: [[false, 'kanban'], [false, 'tree'], [false, 'form']],
            domain: domain
        });
    }

    destroyIfExists(instanceKey) {
        const inst = this.chartInstances[instanceKey];
        if (inst) {
            inst.destroy();
            this.chartInstances[instanceKey] = null;
        }
    }

    renderAllCharts() {
        this.renderUsersAccuracyChart(this.chartData.users);
        this.renderDiscrepancyByLocation(this.chartData.discrepancy_by_location);
        this.renderDiscrepancyTrend(this.chartData.discrepancy_trend);
        this.renderTopProductsLoss(this.chartData.top_products_loss);
        this.renderMistakeReasons(this.chartData.mistake_reasons);
    }

    renderUsersAccuracyChart(dataset) {
        const ctx = document.getElementById('chart_users_accuracy');
        if (!ctx || typeof Chart === 'undefined') return;

        this.destroyIfExists('usersAccuracy');
        this.chartInstances.usersAccuracy = new Chart(ctx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: dataset.labels,
                datasets: [
                    {
                        label: 'Accurate',
                        data: dataset.accurate,
                        backgroundColor: '#10b981',
                        borderColor: '#059669',
                        borderWidth: 1,
                        borderRadius: 6
                    },
                    {
                        label: 'Mistakes',
                        data: dataset.mistake,
                        backgroundColor: '#ef4444',
                        borderColor: '#dc2626',
                        borderWidth: 1,
                        borderRadius: 6
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            usePointStyle: true,
                            padding: 15
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleFont: { size: 12 },
                        bodyFont: { size: 11 }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: {
                            display: true,
                            text: 'User',
                            font: { size: 12, weight: 'bold' }
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        title: {
                            display: true,
                            text: 'Count',
                            font: { size: 12, weight: 'bold' }
                        }
                    }
                },
            },
        });
    }

    renderDiscrepancyByLocation(dataset) {
        const ctx = document.getElementById('chart_discrepancy_location');
        if (!ctx) return;

        this.destroyIfExists('discrepancyLocation');
        this.chartInstances.discrepancyLocation = new Chart(ctx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: dataset.labels,
                datasets: [{
                    label: 'Discrepancy Found',
                    data: dataset.values,
                    backgroundColor: '#8b5cf6',
                    borderColor: '#7c3aed',
                    borderWidth: 1,
                    borderRadius: 4
                }],
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        bodyFont: { size: 11 }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        title: {
                            display: true,
                            text: 'Discrepancy Count',
                            font: { size: 12, weight: 'bold' }
                        }
                    },
                    y: {
                        grid: { display: false },
                        title: {
                            display: true,
                            text: 'Location',
                            font: { size: 12, weight: 'bold' }
                        }
                    }
                },
            },
        });
    }

    renderDiscrepancyTrend(dataset) {
        const ctx = document.getElementById('chart_discrepancy_trend');
        if (!ctx) return;

        this.destroyIfExists('discrepancyTrend');
        this.chartInstances.discrepancyTrend = new Chart(ctx.getContext('2d'), {
            type: 'line',
            data: {
                labels: dataset.labels,
                datasets: [{
                    label: 'Total Discrepancy Value',
                    data: dataset.values,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    borderWidth: 3,
                    tension: 0.4,
                    fill: true,
                    pointBackgroundColor: '#f59e0b',
                    pointBorderColor: '#ffffff',
                    pointBorderWidth: 2,
                    pointRadius: 5,
                    pointHoverRadius: 7
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            usePointStyle: true,
                            padding: 15
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleFont: { size: 12 },
                        bodyFont: { size: 11 }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        title: {
                            display: true,
                            text: 'Date',
                            font: { size: 12, weight: 'bold' }
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        title: {
                            display: true,
                            text: 'Discrepancy Value',
                            font: { size: 12, weight: 'bold' }
                        }
                    }
                },
            },
        });
    }

    renderTopProductsLoss(dataset) {
        const ctx = document.getElementById('chart_top_products_loss');
        if (!ctx) return;

        this.destroyIfExists('topProductsLoss');
        this.chartInstances.topProductsLoss = new Chart(ctx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: dataset.labels,
                datasets: [{
                    label: 'Loss Value',
                    data: dataset.values,
                    backgroundColor: '#ec4899',
                    borderColor: '#db2777',
                    borderWidth: 1,
                    borderRadius: 6
                }],
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        bodyFont: { size: 11 }
                    }
                },
                scales: {
                    x: {
                        reverse: true,
                        beginAtZero: true,
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        title: {
                            display: true,
                            text: 'Loss Value',
                            font: { size: 12, weight: 'bold' }
                        }
                    },
                    y: {
                        grid: { display: false },
                        title: {
                            display: true,
                            text: 'Product',
                            font: { size: 12, weight: 'bold' }
                        }
                    }
                },
            },
        });
    }

    renderMistakeReasons(dataset) {
        const ctx = document.getElementById('chart_mistake_reasons');
        if (!ctx) return;

        this.destroyIfExists('mistakeReasons');

        const backgroundColors = [
            '#ef4444', '#f59e0b', '#10b981', '#3b82f6',
            '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'
        ];

        this.chartInstances.mistakeReasons = new Chart(ctx.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: dataset.labels,
                datasets: [{
                    data: dataset.values,
                    backgroundColor: backgroundColors,
                    borderColor: '#ffffff',
                    borderWidth: 2,
                    hoverOffset: 8
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            padding: 15,
                            font: { size: 11 }
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        bodyFont: { size: 11 }
                    }
                },
                cutout: '60%'
            },
        });
    }

    updateDisplay() {
        const elements = {
            'total-sessions-completed': this.dashboardData.totalSessionsCompleted,
            'avg-time-per-session': this.dashboardData.avgTimePerSession,
            'total-products-counted': this.dashboardData.totalProductsCounted,
            'global-accuracy': `${this.dashboardData.globalAccuracy}%`,
            'total-discrepancy-qty': this.dashboardData.totalDiscrepancyQty,
            'total-inventory-loss': this.formatNumber(this.dashboardData.totalInventoryLoss),
            'approvals-pending': this.dashboardData.approvalsPending
        };

        Object.entries(elements).forEach(([className, value]) => {
            const element = document.querySelector(`.${className}`);
            if (element) {
                element.textContent = value;
            }
        });
    }

    formatDateForInput(dateString) {
        if (!dateString) {
            const today = new Date();
            return new Date(today.getFullYear(), today.getMonth(), 1).toISOString().split('T')[0];
        }
        if (typeof dateString === 'string' && dateString.match(/^\d{4}-\d{2}-\d{2}$/)) {
            return dateString;
        }
        const today = new Date();
        return new Date(today.getFullYear(), today.getMonth(), 1).toISOString().split('T')[0];
    }

    onStartDateChange(ev) {
        const newDate = ev.target.value;
        this.dateState.startDate = newDate;
        const startDateInput = document.getElementById('startDate');
        if (startDateInput) {
            startDateInput.value = newDate;
        }
        this.onFilterChange();
    }

    onEndDateChange(ev) {
        const newDate = ev.target.value;
        this.dateState.endDate = newDate;
        const endDateInput = document.getElementById('endDate');
        if (endDateInput) {
            endDateInput.value = newDate;
        }
        this.onFilterChange();
    }

    forceEnableScrolling() {
        const contentArea = document.querySelector('.o_content');
        const actionManager = document.querySelector('.o_action_manager');
        const webClient = document.querySelector('.o_web_client');

        if (contentArea) {
            contentArea.style.overflowY = 'auto';
            contentArea.style.height = '100vh';
        }

        if (actionManager) {
            actionManager.style.overflowY = 'auto';
            actionManager.style.height = '100vh';
        }

        if (webClient) {
            webClient.style.overflowY = 'auto';
            webClient.style.height = '100vh';
        }

        document.body.style.overflow = 'auto';
        document.body.style.height = 'auto';
        document.documentElement.style.overflow = 'auto';
        document.documentElement.style.height = 'auto';
    }
}

SetuInventoryDashboard.template = 'SetuInventoryDashboard';
SetuInventoryDashboard.props = ["*"];
registry.category('actions').add('setu_inventory_dashboard', SetuInventoryDashboard);

