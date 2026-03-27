-- Normalize French OUI/NON (and variants) to boolean.
-- N/A or any other value → NULL.
-- Usage: {{ normalize_oui_non('my_column') }}
{% macro normalize_oui_non(column_name) %}
    case
        when upper(trim({{ column_name }})) in ('OUI', 'YES', 'TRUE', '1', 'OK') then true
        when upper(trim({{ column_name }})) in ('NON', 'NO',  'FALSE', '0')       then false
        else null
    end
{% endmacro %}
