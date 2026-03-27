-- Override default schema naming: use custom_schema_name as-is (no prefix).
-- Without this macro dbt would produce e.g. "main_silver" instead of "silver".
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
