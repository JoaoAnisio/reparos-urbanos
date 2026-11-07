-- Nenhuma coluna de core ou marts pode ter nome de dado pessoal ou que localize uma residência.
-- Devolve as colunas suspeitas.
--
-- Exceção explícita: numero_reincidencia contém "numero", mas é uma contagem de reincidências,
-- não o número do imóvel. Uma coluna nova só entra aqui depois de alguém confirmar o que ela é.
--
-- Sem ref(), o dbt build poderia rodar este teste antes de criar as tabelas, e ele passaria sobre
-- schemas vazios. As linhas abaixo o obrigam a rodar depois de todos os modelos de core e marts
-- (acrescente aqui cada modelo novo).
-- depends_on: {{ ref('dim_tempo') }}
-- depends_on: {{ ref('dim_local') }}
-- depends_on: {{ ref('dim_status') }}
-- depends_on: {{ ref('dim_canal') }}
-- depends_on: {{ ref('fato_chamado') }}
-- depends_on: {{ ref('fato_ocorrencia') }}
-- depends_on: {{ ref('mart_fila_prioridade') }}
-- depends_on: {{ ref('mart_kpis_mensal') }}
-- depends_on: {{ ref('mart_mapa_calor') }}
-- depends_on: {{ ref('mart_equidade') }}
-- depends_on: {{ ref('mart_indicadores') }}
-- depends_on: {{ ref('mart_serie_mensal') }}

select table_schema, table_name, column_name
from information_schema.columns
where table_schema in ('core', 'marts')
  and regexp_matches(lower(column_name), 'numero|cep|protocolo|cpf|email|telefone')
  and column_name not in ('numero_reincidencia')
