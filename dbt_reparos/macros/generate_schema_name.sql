{#
  Por padrão o dbt concatena o schema do profile com o +schema do modelo ("main_core").
  Aqui o +schema é usado sozinho, para os schemas se chamarem exatamente staging, core e marts.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
