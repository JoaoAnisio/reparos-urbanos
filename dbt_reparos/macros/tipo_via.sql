{#
  Tipo de via pela primeira palavra do logradouro, sem acento e em minúsculas.
  Usado na staging (por chamado) e na fato_ocorrencia (pelo logradouro mais frequente).
#}
{% macro tipo_via(logradouro) -%}
    case
        when {{ logradouro }} is null then null
        when lower(strip_accents(split_part(trim({{ logradouro }}), ' ', 1)))
             in ('avenida', 'rua', 'estrada', 'travessa', 'viaduto', 'ponte')
            then lower(strip_accents(split_part(trim({{ logradouro }}), ' ', 1)))
        else 'outros'
    end
{%- endmacro %}
