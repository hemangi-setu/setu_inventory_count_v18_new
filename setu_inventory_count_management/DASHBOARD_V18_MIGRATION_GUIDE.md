# Inventory Dashboard - Complete Logic & V18 Migration Guide

## Overview
This document contains the complete inventory dashboard logic from the v19 module and instructions for adapting it to v18.

## Module Structure

### 1. Python Model (`models/setu_inventory_dashboard.py`)

**Model Name:** `setu.inventory.dashboard` (AbstractModel)

#### Key Methods:

1. **`get_dashboard_data(start_date, end_date, warehouse_ids, user_ids, session_ids)`**
   - Returns KPI data:
     - `total_sessions_completed`: Count of completed sessions
     - `avg_time_per_session`: Average time per session (HH:MM:SS)
     - `total_products_counted`: Unique products counted
     - `global_accuracy`: Accuracy percentage
     - `total_discrepancy_qty`: Total discrepancies found
     - `total_inventory_loss`: Total inventory loss value
     - `approvals_pending`: Sessions pending approval

2. **`get_chart_data(start_date, end_date, warehouse_ids, user_ids, session_ids)`**
   - Returns chart datasets:
     - `users`: User accuracy vs mistakes (bar chart)
     - `discrepancy_by_location`: Discrepancies by location (bar chart)
     - `discrepancy_trend`: Discrepancy trend over time (line chart)
     - `top_products_loss`: Top 10 products by loss (bar chart)
     - `mistake_reasons`: User vs system mistakes (doughnut chart)

3. **`get_table_data(start_date, end_date, warehouse_ids, user_ids, session_ids)`**
   - Returns table data:
     - `open_sessions`: Active sessions
     - `recent_adjustments`: Recent inventory adjustments
     - `high_risk_products`: Products with frequent discrepancies

4. **`get_warehouse_list()`**: Returns list of warehouses
5. **`get_user_list()`**: Returns list of active users
6. **`get_session_list(user_ids)`**: Returns sessions filtered by users

#### Helper Methods:
- `_get_valid_counts()`: Filters counts by valid states
- `_get_date_range()`: Parses and normalizes date ranges
- `_build_base_domains()`: Builds search domains
- `_get_filtered_sessions()`: Gets filtered sessions
- `_get_filtered_counts()`: Gets filtered counts
- `_format_duration()`: Formats seconds to HH:MM:SS
- `_get_total_sessions_completed()`: Counts completed sessions
- `_get_avg_time_per_session()`: Calculates average session time
- `_get_total_products_counted()`: Counts unique products
- `_get_global_accuracy()`: Calculates accuracy percentage
- `_get_total_discrepancy_qty()`: Counts discrepancies
- `_get_total_inventory_loss()`: Calculates total loss value
- `_get_approvals_pending()`: Counts pending approvals
- `_get_user_mistakes_data()`: Prepares user accuracy data
- `_get_discrepancy_by_location_data()`: Groups discrepancies by location
- `_get_discrepancy_trend_data()`: Prepares trend data over time
- `_get_top_products_loss_data()`: Gets top products by loss
- `_get_mistake_reasons_data()`: Prepares mistake distribution
- `_get_open_sessions()`: Gets active sessions data
- `_get_recent_adjustments()`: Gets recent adjustments data
- `_get_high_risk_products()`: Gets high-risk products data

### 2. JavaScript Component (`static/src/js/inventory_dashboard.js`)

**Component Class:** `SetuInventoryDashboard`

#### Key Features:
- Uses OWL 2.0 framework (v19)
- Chart.js for visualizations
- Reactive state management with `useState`
- Filter management (date, warehouse, user, session)
- KPI cards with click actions
- Multiple chart types (bar, line, doughnut)
- Data tables for drill-down information

#### Main Methods:
- `setup()`: Component initialization
- `loadDashboardData()`: Loads KPI data
- `loadAllCharts()`: Loads chart data
- `loadTableData()`: Loads table data
- `loadFilterOptions()`: Populates filter dropdowns
- `initializeDashboard()`: Initializes dashboard
- `onFilterChange()`: Handles filter changes
- `onKpiCardClick()`: Handles KPI card clicks
- `renderAllCharts()`: Renders all charts
- `renderUsersAccuracyChart()`: Renders user accuracy chart
- `renderDiscrepancyByLocation()`: Renders location chart
- `renderDiscrepancyTrend()`: Renders trend chart
- `renderTopProductsLoss()`: Renders top products chart
- `renderMistakeReasons()`: Renders mistake reasons chart
- `updateDisplay()`: Updates KPI display values
- `openSessions()`: Opens sessions view
- `openProducts()`: Opens products view
- `openAccuracyReport()`: Opens accuracy report
- `openDiscrepancyReport()`: Opens discrepancy report
- `openInventoryLossReport()`: Opens loss report
- `openApprovals()`: Opens approvals view

### 3. XML Template (`static/src/xml/inventory_dashboard_template.xml`)

**Template Name:** `SetuInventoryDashboard`

Contains:
- Filter bar (date, warehouse, user, session filters)
- 7 KPI cards
- 5 charts (User Accuracy, Discrepancy by Location, Discrepancy Trend, Top Products Loss, Mistake Reasons)
- 3 data tables (High-Risk Products, Recent Adjustments, Open Sessions)
- Comprehensive CSS styling

### 4. View Registration (`views/setu_inventory_dashboard_views.xml`)

- Client action: `action_inventory_dashboard`
- Menu item: `menu_inventory_dashboard`
- Tag: `setu_inventory_dashboard`

## V19 to V18 Migration Guide

### Key Differences:

#### 1. OWL Framework
**V19:**
```javascript
import { Component, onMounted, useState, onWillStart } from "@odoo/owl";
```

**V18:**
```javascript
import { Component, useState, onMounted, onWillStart } from "@odoo/owl";
// OR (depending on v18 version)
import { Component } from "@odoo/owl";
const { useState, onMounted, onWillStart } = owl;
```

#### 2. Service Access
**V19:**
```javascript
this.actionService = useService("action");
this.notification = useService("notification");
this.orm = useService('orm');
```

**V18:**
```javascript
// Option 1: Same as v19 (if available)
this.actionService = useService("action");
this.notification = useService("notification");
this.orm = useService('orm');

// Option 2: Use env.services (v18 fallback)
this.actionService = this.env.services.action;
this.notification = this.env.services.notification;
this.orm = this.env.services.orm;
```

#### 3. View Types
**V19:**
```javascript
view_mode: 'kanban,list,form',
views: [[false, 'kanban'], [false, 'list'], [false, 'form']]
```

**V18:**
```javascript
view_mode: 'kanban,tree,form',
views: [[false, 'kanban'], [false, 'tree'], [false, 'form']]
```

#### 4. Template Syntax
**V19:**
```xml
<t t-name="SetuInventoryDashboard" owl="1">
```

**V18:**
```xml
<t t-name="SetuInventoryDashboard" owl="1">
<!-- Should work the same, but verify -->
```

#### 5. Assets Declaration
**V19:**
```python
'assets': {
    'web.assets_backend': [
        "setu_inventory_count_management/static/src/js/inventory_dashboard.js",
        "setu_inventory_count_management/static/src/xml/inventory_dashboard_template.xml"
    ],
}
```

**V18:**
```python
'assets': {
    'web.assets_backend': [
        "setu_inventory_count_management/static/src/js/inventory_dashboard.js",
        "setu_inventory_count_management/static/src/xml/inventory_dashboard_template.xml"
    ],
}
# Should be the same, but verify the exact structure
```

### Step-by-Step Migration:

1. **Copy Python Model** (`setu_inventory_dashboard.py`)
   - No changes needed - Python code is version-agnostic
   - Ensure model dependencies exist in your v18 module

2. **Adapt JavaScript Component**
   - Change view types from `list` to `tree`
   - Verify OWL imports work in v18
   - Test service access methods
   - Update Chart.js loading if needed

3. **Update XML Template**
   - Verify template syntax works in v18
   - Test OWL template rendering

4. **Update View Registration**
   - Ensure client action works in v18
   - Verify menu structure

5. **Update Manifest**
   - Add dashboard model to `__init__.py`
   - Add assets declaration
   - Add view file to data list

### Required Dependencies:

The dashboard depends on these models:
- `setu.inventory.count.session`
- `setu.stock.inventory.count`
- `setu.stock.inventory.count.line`
- `setu.inventory.count.session.line`
- `setu.inventory.session.details`
- `stock.warehouse`
- `res.users`
- `product.product`
- `stock.location`

### Testing Checklist:

- [ ] Dashboard loads without errors
- [ ] KPI cards display correct data
- [ ] Charts render properly
- [ ] Filters work correctly
- [ ] Date range filtering works
- [ ] Warehouse filter works
- [ ] User filter works
- [ ] Session filter works
- [ ] KPI card clicks open correct views
- [ ] Tables display data correctly
- [ ] Chart.js loads and renders
- [ ] Responsive design works
- [ ] No console errors

### Notes:

1. The Python model code should work in both v18 and v19 without changes
2. The main adaptation needed is in the JavaScript component
3. Chart.js CDN loading should work in both versions
4. CSS styling should be compatible
5. Template syntax is mostly compatible

### Files to Copy/Adapt:

1. `models/setu_inventory_dashboard.py` - Copy as-is
2. `static/src/js/inventory_dashboard.js` - Adapt for v18
3. `static/src/xml/inventory_dashboard_template.xml` - Copy as-is (verify)
4. `views/setu_inventory_dashboard_views.xml` - Copy as-is
5. Update `models/__init__.py` to import dashboard
6. Update `__manifest__.py` to include assets and views

