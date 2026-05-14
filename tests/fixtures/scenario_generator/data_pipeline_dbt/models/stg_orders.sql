-- Staging model for orders — normalises raw order rows.
{{ config(materialized='view') }}

select
    order_id,
    customer_id,
    cast(order_total as numeric(12, 2)) as order_total,
    cast(created_at as timestamp) as created_at
from {{ source('raw', 'orders') }}
