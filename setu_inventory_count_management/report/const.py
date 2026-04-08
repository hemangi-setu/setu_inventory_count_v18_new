from datetime import datetime

import pytz


def _report_active_company_ids(env):
    """Company ids constrained by active context, user allowed companies, and current company."""
    allowed_ctx = env.context.get('allowed_company_ids')
    if allowed_ctx is None:
        company_ids = list(env.companies.ids)
    elif isinstance(allowed_ctx, (list, tuple)):
        company_ids = list(allowed_ctx)
    else:
        company_ids = [allowed_ctx]

    if not company_ids and env.company:
        company_ids = [env.company.id]

    # Keep only companies the current user is allowed to access.
    user_allowed_ids = set(env.user.company_ids.ids)
    if user_allowed_ids:
        company_ids = [cid for cid in company_ids if cid in user_allowed_ids]

    # Ensure current company is present when accessible.
    current_company_id = env.company.id if env.company else False
    if current_company_id and current_company_id in user_allowed_ids and current_company_id not in company_ids:
        company_ids.append(current_company_id)

    return list(dict.fromkeys(company_ids))


def inventory_count_approver_user_domain(env):
    """Approvers allowed in `env.companies`; approver-only users can select only themselves."""
    company_ids = _report_active_company_ids(env)
    group = env.ref(
        'setu_inventory_count_management.group_setu_inventory_count_approver',
        raise_if_not_found=False,
    )
    is_manager = env.user.has_group('setu_inventory_count_management.group_setu_inventory_count_manager')
    is_approver = env.user.has_group('setu_inventory_count_management.group_setu_inventory_count_approver')
    domain = [('share', '=', False)]
    if company_ids:
        domain.append(('company_ids', 'in', company_ids))
    if is_approver and not is_manager:
        domain.append(('id', '=', env.user.id))
    if not group:
        return domain
    return domain + [('groups_id', 'in', [group.id])]


def is_inventory_count_approver_only(env):
    """True when the current user is approver but not manager."""
    return (
        env.user.has_group('setu_inventory_count_management.group_setu_inventory_count_approver')
        and not env.user.has_group('setu_inventory_count_management.group_setu_inventory_count_manager')
    )


def sql_current_user_approver_filter(env, column='cou.approver_id'):
    """SQL AND clause to force current approver scope for approver-only users."""
    if not is_inventory_count_approver_only(env):
        return ''
    return f" AND {column} = {int(env.user.id)}"


def inventory_count_report_location_domain(env):
    """Internal stock locations for companies allowed in the multi-company switcher."""
    company_ids = _report_active_company_ids(env)
    domain = [('usage', '=', 'internal')]
    if company_ids:
        domain = [
            ('usage', '=', 'internal'),
            '|',
            ('company_id', '=', False),
            ('company_id', 'in', company_ids),
        ]
    return domain


def inventory_count_report_warehouse_domain(env):
    """Warehouses belonging to companies allowed in the multi-company switcher."""
    company_ids = _report_active_company_ids(env)
    if not company_ids:
        return [('id', '=', False)]
    return [('company_id', 'in', company_ids)]


def get_dynamic_query(location, location_ids, user, user_ids, warehouse, warehouse_ids):
    """
    Build a dynamic WHERE clause for location, user and warehouse filters.

    - For location: when location_ids are provided, include both the selected locations
      and their child locations (using stock.location parent_path).
    - For user and warehouse: keep existing exact match behaviour.
    """
    where_query = ''
    if location_ids:
        # Include selected locations AND their child locations
        # location (column name) is expected to be something like "count_line.location_id"
        where_query += f"""
            and 1 = case
                when array_length({location_ids}, 1) >= 1 then
                    case when (
                        -- Exact match with any selected location
                        {location} = ANY({location_ids})
                        OR
                        -- Or the location is a child of any selected location
                        exists (
                            select 1
                            from stock_location sl_child
                            join stock_location sl_parent
                                on coalesce(sl_child.parent_path, '') like coalesce(sl_parent.parent_path, '') || '%'
                            where sl_child.id = {location}
                              and sl_parent.id = ANY({location_ids})
                        )
                    ) then 1 else 0 end
                else 1
            end
    """
    if user_ids:
        where_query += f"""and 1 = case when array_length({user_ids},1) >= 1 then
                            case when {user} = ANY({user_ids}) then 1 else 0 end
                            else 1 end
    """
    if warehouse_ids:
        where_query += f"""and 1 = case when array_length({warehouse_ids},1) >= 1 then
                            case when {warehouse} = ANY({warehouse_ids}) then 1 else 0 end
                            else 1 end
    """
    return where_query


def change_time_zone(local_timezone, datetime_obj):
    local_timezone = pytz.timezone(local_timezone)
    datetime_obj = datetime.strptime(f"{datetime_obj}", "%Y-%m-%d %H:%M:%S")
    local_dt = local_timezone.localize(datetime_obj, is_dst=None)
    utc_dt = local_dt.astimezone(pytz.utc)
    return utc_dt
