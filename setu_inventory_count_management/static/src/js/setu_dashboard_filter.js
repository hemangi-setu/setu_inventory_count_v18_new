/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { session } from "@web/session";

const STORAGE_KEY = "setuInventoryOperationDashboardFilters";

/** Session context: prefer session.user_context when present; else user.context (standard after web bootstrap). */
function getSessionContext() {
    return session.user_context || user.context;
}

function toLocalYMD(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function startOfMondayWeek(ref) {
    const d = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate());
    const day = d.getDay();
    const diff = day === 0 ? -6 : 1 - day;
    d.setDate(d.getDate() + diff);
    return d;
}

function computePresetRange(preset, customStart, customEnd) {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    let start;
    let end = new Date(today);

    switch (preset) {
        case "all_time":
            start = new Date(2000, 0, 1);
            break;
        case "today":
            start = new Date(today);
            break;
        case "this_week":
            start = startOfMondayWeek(today);
            break;
        case "this_month":
            start = new Date(today.getFullYear(), today.getMonth(), 1);
            end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
            break;
        case "last_month":
            start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
            end = new Date(today.getFullYear(), today.getMonth(), 0);
            break;
        case "this_year":
            start = new Date(today.getFullYear(), 0, 1);
            end = new Date(today.getFullYear(), 11, 31);
            break;
        case "this_quarter": {
            const q = Math.floor(today.getMonth() / 3);
            start = new Date(today.getFullYear(), q * 3, 1);
            end = new Date(today.getFullYear(), q * 3 + 3, 0);
            break;
        }
        case "custom":
            if (customStart && customEnd) {
                return { startDate: customStart, endDate: customEnd };
            }
            return { startDate: toLocalYMD(today), endDate: toLocalYMD(today) };
        default:
            start = new Date(today);
    }
    return { startDate: toLocalYMD(start), endDate: toLocalYMD(end) };
}

export class SetuDashboardFilter extends Component {
    static template = "SetuDashboardFilter";
    static props = {
        onFiltersChange: { optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        const todayYmd = toLocalYMD(new Date());

        this.state = useState({
            datePreset: "today",
            customStartDate: todayYmd,
            customEndDate: todayYmd,
            startDate: todayYmd,
            endDate: todayYmd,
            warehouseId: "",
            userId: "",
            sessionId: "",
            warehouses: [],
            users: [],
            sessions: [],
        });

        onWillStart(async () => {
            await this.loadFilterOptions();
            this.restoreSavedFilters();
            await this.loadUsers();
            await this.loadWarehouses();
            await this.loadSessions();
            this.applyPreset(false);
            this.emitChange();
        });
    }

    get allowedCompanyIds() {
        const ctx = getSessionContext();
        const allowedFromContext = Array.isArray(ctx?.allowed_company_ids)
            ? ctx.allowed_company_ids
            : [];
        if (allowedFromContext.length) {
            return allowedFromContext;
        }
        // Same fallback order as get company ID from session context (standard Odoo approach)
        const currentCompanyId =
            ctx?.company_id ||
            (ctx?.allowed_company_ids && ctx.allowed_company_ids[0]) ||
            session.company_id ||
            session.user_companies?.current_company ||
            null;
        return currentCompanyId ? [currentCompanyId] : [];
    }

    restoreSavedFilters() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) {
                return;
            }
            const saved = JSON.parse(raw);
            if (saved.datePreset && this.state.datePreset !== saved.datePreset) {
                this.state.datePreset = saved.datePreset;
            }
            if (saved.customStartDate) {
                this.state.customStartDate = saved.customStartDate;
            }
            if (saved.customEndDate) {
                this.state.customEndDate = saved.customEndDate;
            }
            if (saved.warehouseId !== undefined) {
                this.state.warehouseId = saved.warehouseId;
            }
            if (saved.userId !== undefined) {
                this.state.userId = saved.userId;
            }
            if (saved.sessionId !== undefined && saved.sessionId !== "") {
                const single = parseInt(saved.sessionId, 10);
                if (!isNaN(single)) {
                    this.state.sessionId = String(single);
                }
            } else if (saved.sessionIds !== undefined && Array.isArray(saved.sessionIds) && saved.sessionIds.length) {
                const first = parseInt(saved.sessionIds[0], 10);
                if (!isNaN(first)) {
                    this.state.sessionId = String(first);
                }
            }
        } catch {
            /* ignore */
        }
    }

    persistFilters() {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({
                datePreset: this.state.datePreset,
                customStartDate: this.state.customStartDate,
                customEndDate: this.state.customEndDate,
                warehouseId: this.state.warehouseId,
                userId: this.state.userId,
                sessionId: this.state.sessionId,
            })
        );
    }

    buildPayload() {
        const { startDate, endDate } =
            this.state.datePreset === "custom"
                ? computePresetRange(
                      "custom",
                      this.state.customStartDate,
                      this.state.customEndDate
                  )
                : { startDate: this.state.startDate, endDate: this.state.endDate };

        return {
            datePreset: this.state.datePreset,
            startDate,
            endDate,
            warehouseIds: this.state.warehouseId
                ? [parseInt(this.state.warehouseId, 10)]
                : null,
            userIds: this.state.userId ? [parseInt(this.state.userId, 10)] : null,
            sessionIds: this.state.sessionId ? [parseInt(this.state.sessionId, 10)] : null,
        };
    }

    emitChange() {
        if (!this.isCustomDateRangeValid()) {
            return;
        }
        this.persistFilters();
        if (this.props.onFiltersChange) {
            this.props.onFiltersChange(this.buildPayload());
        }
    }

    isCustomDateRangeValid() {
        if (this.state.datePreset !== "custom") {
            return true;
        }
        const fromDate = this.state.customStartDate;
        const toDate = this.state.customEndDate;
        if (!fromDate || !toDate) {
            return true;
        }
        if (fromDate > toDate) {
            this.notification.add("From date cannot be greater than To date.", {
                type: "danger",
            });
            return false;
        }
        return true;
    }

    applyPreset(shouldEmit = true) {
        if (this.state.datePreset === "custom") {
            const { startDate, endDate } = computePresetRange(
                "custom",
                this.state.customStartDate,
                this.state.customEndDate
            );
            this.state.startDate = startDate;
            this.state.endDate = endDate;
        } else {
            const range = computePresetRange(this.state.datePreset, null, null);
            this.state.startDate = range.startDate;
            this.state.endDate = range.endDate;
        }
        if (shouldEmit) {
            this.emitChange();
        }
    }

    onDatePresetChange(ev) {
        this.state.datePreset = ev.target.value;
        this.applyPreset();
    }

    onCustomStartChange(ev) {
        this.state.customStartDate = ev.target.value;
        if (this.state.datePreset === "custom") {
            this.applyPreset();
        }
    }

    onCustomEndChange(ev) {
        this.state.customEndDate = ev.target.value;
        if (this.state.datePreset === "custom") {
            this.applyPreset();
        }
    }

    onWarehouseChange(ev) {
        this.state.warehouseId = ev.target.value;
        this.emitChange();
    }

    async onUserChange(ev) {
        this.state.userId = ev.target.value;
        this.state.sessionId = "";
        await this.loadSessions();
        this.emitChange();
    }

    onSessionChange(ev) {
        this.state.sessionId = ev.target.value;
        this.emitChange();
    }

    async loadFilterOptions() {
        const allowed = this.allowedCompanyIds;
        // Match self.env.companies: only companies in session allowed_company_ids.
        const [warehouses, users] = await Promise.all([
            this.loadWarehousesForDomain(allowed),
            this.loadUsers(),
        ]);

        this.state.warehouses = warehouses;
        this.state.users = users;
    }

    async loadUsers() {
        const allowed = this.allowedCompanyIds;
        const userDomain = [["active", "=", true]];
        if (allowed.length) {
            userDomain.push(["company_ids", "in", allowed]);
        }
        const users = await this.orm.searchRead("res.users", userDomain, ["id", "name"], {
            order: "name",
        });
        const mappedUsers = users.map((u) => ({ id: u.id, name: u.name }));
        this.state.users = mappedUsers;

        const validUserIds = new Set(mappedUsers.map((u) => String(u.id)));
        if (this.state.userId && !validUserIds.has(this.state.userId)) {
            this.state.userId = "";
        }
        return mappedUsers;
    }

    async loadWarehousesForDomain(allowedCompanyIds) {
        if (!allowedCompanyIds || !allowedCompanyIds.length) {
            return [];
        }
        const records = await this.orm.searchRead(
            "stock.warehouse",
            [["company_id", "in", allowedCompanyIds]],
            ["id", "name"],
            { order: "name" }
        );
        return records.map((w) => ({ id: w.id, name: w.name }));
    }

    async loadWarehouses() {
        const allowed = this.allowedCompanyIds;
        this.state.warehouses = await this.loadWarehousesForDomain(allowed);
        const validWarehouseIds = new Set(this.state.warehouses.map((w) => String(w.id)));
        if (this.state.warehouseId && !validWarehouseIds.has(this.state.warehouseId)) {
            this.state.warehouseId = "";
        }
    }

    async loadSessions() {
        const allowed = this.allowedCompanyIds;
        const sessionDomain = [];
        if (allowed.length) {
            sessionDomain.push(["company_id", "in", allowed]);
        }
        if (this.state.userId) {
            sessionDomain.push(["user_ids", "in", [parseInt(this.state.userId, 10)]]);
        }
        const sessions = await this.orm.searchRead(
            "setu.inventory.count.session",
            sessionDomain,
            ["id", "name"],
            { order: "name" }
        );
        this.state.sessions = sessions.map((s) => ({ id: s.id, name: s.name }));
        const validIds = new Set(this.state.sessions.map((s) => String(s.id)));
        if (this.state.sessionId && !validIds.has(this.state.sessionId)) {
            this.state.sessionId = "";
        }
    }
}
