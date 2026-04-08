/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { SetuDashboardFilter } from "./setu_dashboard_filter";

const CANVAS_USER = "chart_op_user_workloads";
const CANVAS_REJECTION = "chart_op_rejection_location";
const CANVAS_SCANNED_REJECTED = "chart_op_user_scanned_rejected";

function chartCtor() {
    return typeof Chart !== "undefined" ? Chart : window.Chart;
}

function normalizeBars(dataset, emptyLabel) {
    const labels = dataset?.labels || [];
    const values = dataset?.values || [];
    if (!labels.length) {
        return { labels: [emptyLabel], values: [0] };
    }
    return {
        labels,
        values: labels.map((_, i) => {
            const v = Number(values[i]);
            return Number.isFinite(v) ? v : 0;
        }),
    };
}

/**
 * @param {string|false|null} isoStr
 * @returns {string}
 */
function formatRelativeTime(isoStr) {
    if (!isoStr) {
        return "—";
    }
    const normalized = String(isoStr).replace(" ", "T");
    const t = new Date(normalized);
    if (Number.isNaN(t.getTime())) {
        return String(isoStr);
    }
    const diffSec = Math.floor((Date.now() - t.getTime()) / 1000);
    if (diffSec < 0) {
        return "just now";
    }
    if (diffSec < 60) {
        return `${diffSec} sec ago`;
    }
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) {
        return `${diffMin} min ago`;
    }
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) {
        return `${diffH} hr ago`;
    }
    const diffD = Math.floor(diffH / 24);
    return `${diffD} day(s) ago`;
}

export class SetuInventoryOperationDashboard extends Component {
    static template = "SetuInventoryOperationDashboard";
    static components = { SetuDashboardFilter };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.lastPayloadKey = null;
        this.scrollStyleBackup = new Map();
        this.chartInstances = {
            userWorkloads: null,
            rejectionByLocation: null,
            userScannedVsRejected: null,
        };
        this.state = useState({
            isLoading: false,
            currentFilters: {
                startDate: null,
                endDate: null,
                warehouseIds: [],
                userIds: [],
                sessionIds: [],
            },
            kpis: {
                pendingApproval: 0,
                activeSessions: 0,
                pendingReviewLines: 0,
                avgSessionTime: "00:00",
                reSessions: 0,
                rejectedLines: 0,
            },
            charts: {
                userWorkloads: { labels: [], values: [] },
                rejectionByLocation: { labels: [], values: [] },
                userScannedVsRejected: { labels: [], scanned: [], rejected: [] },
            },
            pendingSessionAdjustments: [],
            unscannedSessions: [],
            managerActivity: [],
        });

        onWillStart(async () => {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js");
        });
        onMounted(() => {
            this.applySingleScrollbarMode();
            this.scheduleRenderCharts();
        });
        onWillUnmount(() => {
            this.restoreScrollMode();
            this.destroyCharts();
        });
    }

    saveAndSetInlineStyle(element, propertyName, value) {
        if (!element) {
            return;
        }
        if (!this.scrollStyleBackup.has(element)) {
            this.scrollStyleBackup.set(element, {
                overflowY: element.style.overflowY,
                height: element.style.height,
            });
        }
        element.style[propertyName] = value;
    }

    applySingleScrollbarMode() {
        const contentArea = document.querySelector(".o_content");
        const actionManager = document.querySelector(".o_action_manager");
        const controllerWithScroll = document.querySelector(".o_controller_with_scroll");

        // Keep only the main Odoo content area as vertical scroller.
        this.saveAndSetInlineStyle(contentArea, "overflowY", "auto");
        this.saveAndSetInlineStyle(contentArea, "height", "auto");

        this.saveAndSetInlineStyle(actionManager, "overflowY", "visible");
        this.saveAndSetInlineStyle(actionManager, "height", "auto");

        this.saveAndSetInlineStyle(controllerWithScroll, "overflowY", "visible");
        this.saveAndSetInlineStyle(controllerWithScroll, "height", "auto");
    }

    restoreScrollMode() {
        for (const [element, previousStyles] of this.scrollStyleBackup.entries()) {
            if (!element || !previousStyles) {
                continue;
            }
            element.style.overflowY = previousStyles.overflowY || "";
            element.style.height = previousStyles.height || "";
        }
        this.scrollStyleBackup.clear();
    }

    destroyCharts() {
        for (const key of Object.keys(this.chartInstances)) {
            const inst = this.chartInstances[key];
            if (inst) {
                inst.destroy();
                this.chartInstances[key] = null;
            }
        }
    }

    scheduleRenderCharts() {
        requestAnimationFrame(() => requestAnimationFrame(() => this.renderCharts()));
    }

    renderCharts(attempt = 0) {
        const ChartLib = chartCtor();
        const canvasUser = document.getElementById(CANVAS_USER);
        const canvasRej = document.getElementById(CANVAS_REJECTION);
        const canvasScanRej = document.getElementById(CANVAS_SCANNED_REJECTED);
        if (!ChartLib || !canvasUser || !canvasRej || !canvasScanRej) {
            if (attempt < 40) {
                setTimeout(() => this.renderCharts(attempt + 1), 50);
            }
            return;
        }

        const userDs = normalizeBars(this.state.charts.userWorkloads, "—");
        const userIds = Array.isArray(this.state.charts.userWorkloads?.user_ids)
            ? this.state.charts.userWorkloads.user_ids
            : [];
        const rejDs = normalizeBars(this.state.charts.rejectionByLocation, "—");
        const rejectionLocationIds = Array.isArray(this.state.charts.rejectionByLocation?.location_ids)
            ? this.state.charts.rejectionByLocation.location_ids
            : [];

        if (this.chartInstances.userWorkloads) {
            this.chartInstances.userWorkloads.destroy();
        }
        this.chartInstances.userWorkloads = new ChartLib(canvasUser.getContext("2d"), {
            type: "bar",
            data: {
                labels: userDs.labels,
                datasets: [
                    {
                        label: "Active sessions",
                        data: userDs.values,
                        backgroundColor: "#3b82f6",
                        borderColor: "#2563eb",
                        borderWidth: 1,
                        borderRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: (_event, elements) => {
                    const firstElement = elements?.[0];
                    if (!firstElement || typeof firstElement.index !== "number") {
                        return;
                    }
                    const clickedUserId = Number(userIds[firstElement.index]);
                    const clickedUserLabel = userDs.labels?.[firstElement.index] || "";
                    if (Number.isInteger(clickedUserId) && clickedUserId > 0) {
                        this.openUserWorkloadSessions(clickedUserId, clickedUserLabel);
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "rgba(0, 0, 0, 0.8)",
                        bodyFont: { size: 11 },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: {
                            display: true,
                            text: "User",
                            font: { size: 12, weight: "bold" },
                        },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1 },
                        grid: { color: "rgba(0, 0, 0, 0.05)" },
                        title: {
                            display: true,
                            text: "Session count",
                            font: { size: 12, weight: "bold" },
                        },
                    },
                },
            },
        });

        if (this.chartInstances.rejectionByLocation) {
            this.chartInstances.rejectionByLocation.destroy();
        }
        this.chartInstances.rejectionByLocation = new ChartLib(canvasRej.getContext("2d"), {
            type: "bar",
            data: {
                labels: rejDs.labels,
                datasets: [
                    {
                        label: "Rejection %",
                        data: rejDs.values,
                        backgroundColor: "#f97a1f",
                        borderColor: "#f97a1f",
                        borderWidth: 1,
                        borderRadius: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: (_event, elements) => {
                    const firstElement = elements?.[0];
                    if (!firstElement || typeof firstElement.index !== "number") {
                        return;
                    }
                    const clickedLocationId = Number(rejectionLocationIds[firstElement.index]);
                    const clickedLocationLabel = rejDs.labels?.[firstElement.index] || "";
                    if (Number.isInteger(clickedLocationId) && clickedLocationId > 0) {
                        this.openRejectedLinesByLocation(clickedLocationId, clickedLocationLabel);
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "rgba(0, 0, 0, 0.8)",
                        bodyFont: { size: 11 },
                        callbacks: {
                            label: (ctx) => {
                                const raw =
                                    ctx.parsed && typeof ctx.parsed.y === "number"
                                        ? ctx.parsed.y
                                        : ctx.parsed?.x;
                                return ` ${Number(raw ?? 0).toFixed(2)}%`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: {
                            display: true,
                            text: "Location",
                            font: { size: 12, weight: "bold" },
                        },
                    },
                    y: {
                        beginAtZero: true,
                        max: 100,
                        grid: { color: "rgba(0, 0, 0, 0.05)" },
                        title: {
                            display: true,
                            text: "Rejection % (rejected / scanned × 100)",
                            font: { size: 12, weight: "bold" },
                        },
                        ticks: { callback: (v) => `${v}%` },
                    },
                },
            },
        });

        const vs = this.state.charts.userScannedVsRejected || {};
        const vsLabels = vs.labels?.length ? vs.labels : ["—"];
        const vsUserIds = Array.isArray(vs.user_ids) ? vs.user_ids : [];
        const scannedVals = vsLabels.map((_, i) => {
            const v = Number(vs.scanned?.[i]);
            return Number.isFinite(v) ? v : 0;
        });
        const rejectedVals = vsLabels.map((_, i) => {
            const v = Number(vs.rejected?.[i]);
            return Number.isFinite(v) ? v : 0;
        });

        if (this.chartInstances.userScannedVsRejected) {
            this.chartInstances.userScannedVsRejected.destroy();
        }
        this.chartInstances.userScannedVsRejected = new ChartLib(canvasScanRej.getContext("2d"), {
            type: "bar",
            data: {
                labels: vsLabels,
                datasets: [
                    {
                        label: "Scanned Count",
                        data: scannedVals,
                        backgroundColor: "#1cc88a",
                        borderColor: "#1cc88a",
                        borderWidth: 1,
                        borderRadius: 4,
                        categoryPercentage: 0.7,
                        barPercentage: 0.9,
                    },
                    {
                        label: "Rejected Count",
                        data: rejectedVals,
                        backgroundColor: "#e74a3b",
                        borderColor: "#e74a3b",
                        borderWidth: 1,
                        borderRadius: 4,
                        categoryPercentage: 0.7,
                        barPercentage: 0.9,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: (_event, elements) => {
                    const firstElement = elements?.[0];
                    if (!firstElement || typeof firstElement.index !== "number") {
                        return;
                    }
                    const clickedUserId = Number(vsUserIds[firstElement.index]);
                    const clickedUserLabel = vsLabels?.[firstElement.index] || "";
                    if (!Number.isInteger(clickedUserId) || clickedUserId <= 0) {
                        return;
                    }
                    this.openUserScannedRejectedLines(
                        clickedUserId,
                        firstElement.datasetIndex || 0,
                        clickedUserLabel
                    );
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "rgba(0, 0, 0, 0.8)",
                        bodyFont: { size: 11 },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        title: {
                            display: true,
                            text: "User",
                            font: { size: 12, weight: "bold" },
                        },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1 },
                        grid: { color: "rgba(0, 0, 0, 0.05)" },
                        title: {
                            display: true,
                            text: "Count",
                            font: { size: 12, weight: "bold" },
                        },
                    },
                },
            },
        });
    }

    async onFiltersChange(payload) {
        const payloadKey = JSON.stringify(payload || {});
        if (payloadKey === this.lastPayloadKey) {
            return;
        }
        this.lastPayloadKey = payloadKey;
        this.state.currentFilters = {
            startDate: payload?.startDate || null,
            endDate: payload?.endDate || null,
            warehouseIds: payload?.warehouseIds || [],
            userIds: payload?.userIds || [],
            sessionIds: payload?.sessionIds || [],
        };
        await this.fetchKpis(payload || {});
    }

    async fetchKpis(payload = {}) {
        this.state.isLoading = true;
        try {
            const data = await this.orm.call(
                "setu.inventory.dashboard",
                "get_operation_dashboard_data",
                [
                    payload.startDate || null,
                    payload.endDate || null,
                    payload.warehouseIds || null,
                    payload.userIds || null,
                    payload.sessionIds || null,
                ]
            );

            this.state.kpis = {
                pendingApproval: data.pending_approval || 0,
                activeSessions: data.active_sessions || 0,
                pendingReviewLines: data.pending_review_lines || 0,
                avgSessionTime: data.avg_session_time || "00:00",
                reSessions: data.re_sessions || 0,
                rejectedLines: data.rejected_lines || 0,
            };
            this.state.charts = {
                userWorkloads: data.user_workloads || { labels: [], values: [], user_ids: [] },
                rejectionByLocation: data.rejection_by_location || { labels: [], values: [] },
                userScannedVsRejected: data.user_scanned_vs_rejected || {
                    labels: [],
                    scanned: [],
                    rejected: [],
                    user_ids: [],
                },
            };
            this.state.pendingSessionAdjustments = data.pending_session_adjustments || [];
            this.state.unscannedSessions = data.unscanned_sessions || [];
            this.state.managerActivity = (data.manager_activity || []).map((row) => ({
                ...row,
                last_scan_label: formatRelativeTime(row.write_date),
            }));
        } catch (error) {
            console.error("Error loading operation dashboard KPIs:", error);
            this.state.pendingSessionAdjustments = [];
            this.state.unscannedSessions = [];
            this.state.managerActivity = [];
            this.state.charts.userScannedVsRejected = {
                labels: [],
                scanned: [],
                rejected: [],
                user_ids: [],
            };
        } finally {
            this.state.isLoading = false;
            this.scheduleRenderCharts();
        }
    }

    openManagerSession(row) {
        if (!row || !row.id) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "setu.inventory.count.session",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openUnscannedSession(row) {
        if (!row || !row.id) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "setu.inventory.count.session",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    buildSessionDomain(extraDomain = []) {
        const domain = [];
        const filters = this.state.currentFilters || {};
        if (filters.startDate) {
            domain.push(["create_date", ">=", `${filters.startDate} 00:00:00`]);
        }
        if (filters.endDate) {
            domain.push(["create_date", "<=", `${filters.endDate} 23:59:59`]);
        }
        if (Array.isArray(filters.warehouseIds) && filters.warehouseIds.length) {
            domain.push(["warehouse_id", "in", filters.warehouseIds]);
        }
        if (Array.isArray(filters.userIds) && filters.userIds.length) {
            domain.push(["user_ids", "in", filters.userIds]);
        }
        if (Array.isArray(filters.sessionIds) && filters.sessionIds.length) {
            domain.push(["id", "in", filters.sessionIds]);
        }
        return [...domain, ...extraDomain];
    }

    async openSessionKpiCard(domainSuffix, actionName) {
        const rawDomainSuffix = Array.isArray(domainSuffix) ? [...domainSuffix] : [];
        const hasStateCondition = rawDomainSuffix.some(
            (item) => Array.isArray(item) && item[0] === "state"
        );
        if (!hasStateCondition) {
            rawDomainSuffix.push(["state", "!=", "Cancel"]);
        }
        const domain = this.buildSessionDomain(rawDomainSuffix);
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: actionName || "Sessions",
            res_model: "setu.inventory.count.session",
            view_mode: "kanban,list,form",
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
            domain,
        });
    }

    async openUserWorkloadSessions(userId, userName = "") {
        if (!Number.isInteger(userId) || userId <= 0) {
            return;
        }
        const domainSuffix = [
            ["state", "in", ["Draft", "In Progress"]],
            ["user_ids", "in", [userId]],
        ];
        const actionName = userName ? `Sessions - ${userName}` : `Sessions - User #${userId}`;
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: actionName,
            res_model: "setu.inventory.count.session",
            view_mode: "kanban,list,form",
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
            domain: this.buildSessionDomain(domainSuffix),
        });
    }

    async openPendingReviewLinesKpiCard() {
        const sessionDomain = this.buildSessionDomain([["state", "=", "Submitted"]]);
        const sessionIds = await this.orm.search("setu.inventory.count.session", sessionDomain);
        if (!sessionIds.length) {
            this.notification.add("No pending review lines found for the selected filters.", {
                type: "warning",
            });
            return;
        }
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Pending Review Lines",
            res_model: "setu.inventory.count.session.line",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
            domain: [
                ["session_id", "in", sessionIds],
                ["state", "=", "Pending Review"],
            ],
        });
    }

    async openRejectedLinesKpiCard() {
        const sessionDomain = this.buildSessionDomain([]);
        const sessionIds = await this.orm.search("setu.inventory.count.session", sessionDomain);
        if (!sessionIds.length) {
            this.notification.add("No rejected lines found for the selected filters.", {
                type: "warning",
            });
            return;
        }
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Rejected Lines",
            res_model: "setu.inventory.count.session.line",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
            domain: [
                ["session_id", "in", sessionIds],
                ["state", "=", "Reject"],
            ],
        });
    }

    async openRejectedLinesByLocation(locationId, locationName = "") {
        if (!Number.isInteger(locationId) || locationId <= 0) {
            return;
        }
        const sessionDomain = this.buildSessionDomain([]);
        const sessionIds = await this.orm.search("setu.inventory.count.session", sessionDomain);
        if (!sessionIds.length) {
            this.notification.add("No rejected lines found for the selected filters.", {
                type: "warning",
            });
            return;
        }
        const actionName = locationName
            ? `Rejected Lines - ${locationName}`
            : `Rejected Lines - Location #${locationId}`;
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: actionName,
            res_model: "setu.inventory.count.session.line",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
            domain: [
                ["session_id", "in", sessionIds],
                ["state", "=", "Reject"],
                ["location_id", "=", locationId],
            ],
        });
    }

    async openUserScannedRejectedLines(userId, datasetIndex = 0, userName = "") {
        if (!Number.isInteger(userId) || userId <= 0) {
            return;
        }
        const sessionDomain = this.buildSessionDomain([]);
        const sessionIds = await this.orm.search("setu.inventory.count.session", sessionDomain);
        if (!sessionIds.length) {
            this.notification.add("No session lines found for the selected filters.", {
                type: "warning",
            });
            return;
        }

        const isRejectedDataset = datasetIndex === 1;
        const baseDomain = [
            "&",
            ["session_id", "in", sessionIds],
            "|",
            ["user_ids", "in", [userId]],
            "&",
            ["user_ids", "=", false],
            ["session_id.user_ids", "in", [userId]],
        ];
        const domain = isRejectedDataset
            ? [...baseDomain, ["state", "=", "Reject"]]
            : [...baseDomain, ["state", "=", "Approve"]];
        const actionPrefix = isRejectedDataset ? "Rejected Lines" : "Scanned Lines";
        const actionName = userName ? `${actionPrefix} - ${userName}` : `${actionPrefix} - User #${userId}`;

        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: actionName,
            res_model: "setu.inventory.count.session.line",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
            domain,
        });
    }

    openPendingAdjustment(row) {
        if (!row || !row.id) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Inventory Adjustment",
            res_model: "setu.stock.inventory",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /**
     * Opens the unscanned product action wizard when lines exist; otherwise the session form.
     * @param {object} row
     */
    async openUnscannedWizard(row) {
        if (!row || !row.id) {
            return;
        }
        const methodName = row.unscanned_count > 0
            ? "action_open_unscanned_products"
            : "check_unscanned_session";
        const action = await this.orm.call("setu.inventory.count.session", methodName, [[row.id]]);
        if (action && typeof action === "object" && action.type) {
            if (action.type === "ir.actions.act_window" && !Array.isArray(action.views)) {
                const fallbackViewMode = (action.view_mode || "list,form").split(",")[0] || "list";
                action.views = [[action.view_id || false, fallbackViewMode]];
            }
            await this.actionService.doAction(action);
        }
    }
}

registry.category("actions").add("setu_inventory_operation_dashboard", SetuInventoryOperationDashboard);
