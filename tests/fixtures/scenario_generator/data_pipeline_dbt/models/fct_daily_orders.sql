-- Daily order totals — aggregates stg_orders over calendar days.
{{ config(materialized='table') }}

select
    date_trunc('day', created_at) as order_day,
    count(*) as order_count,
    sum(order_total) as gross_revenue
from {{ ref('stg_orders') }}
group by 1
order by 1
