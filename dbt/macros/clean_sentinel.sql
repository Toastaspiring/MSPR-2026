-- Replace a known sentinel value with NULL.
-- Usage: {{ clean_sentinel('my_column') }}          -- default 999.9
--        {{ clean_sentinel('my_column', 9999) }}    -- custom sentinel
{% macro clean_sentinel(column_name, sentinel_value=999.9) %}
    case
        when {{ column_name }} = {{ sentinel_value }} then null
        else {{ column_name }}
    end
{% endmacro %}
