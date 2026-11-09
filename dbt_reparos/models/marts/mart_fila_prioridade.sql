-- Fila de despacho: ocorrências abertas há até dias_verificar_em_campo (180) dias, ordenadas pelo
-- score de prioridade (0 a 10). As mais antigas vão para mart_verificacao_campo: não competem
-- com os buracos atuais, porque antes é preciso confirmar se ainda existem.
-- Cada componente vai de 0 a 1; os pesos e tetos ficam em vars (dbt_project.yml).
-- A referência de tempo é o data_extracao de cada ocorrência (dias_em_aberto da fato).

with abertas as (
    select o.*, l.subprefeitura, l.zona
    from {{ ref('fato_ocorrencia') }} as o
    left join {{ ref('dim_local') }} as l on l.distrito = o.distrito_final
    where o.situacao = 'aberta'
      and o.dias_em_aberto <= {{ var('dias_verificar_em_campo') }}
),

-- Equidade: posição (percent_rank) da subprefeitura no tempo mediano de reparo, de 0 (a mais
-- rápida) a 1 (a mais lenta). Empates recebem a mesma posição.
equidade as (
    select
        subprefeitura,
        percent_rank() over (order by tempo_reparo_mediano_dias)    as componente_equidade
    from {{ ref('mart_equidade') }}
),

componentes as (
    select
        a.*,
        least(a.dias_em_aberto / {{ var('teto_espera_dias') }}, 1)                    as componente_espera,
        case
            when a.flag_corredor then 1.0
            when a.tipo_via in ('avenida', 'estrada', 'viaduto', 'ponte') then 0.7
            else 0.4                                    -- rua, travessa, outros e sem logradouro
        end                                                                            as componente_via,
        least(ln(1 + a.qtd_chamados) / ln(1 + {{ var('teto_demanda_chamados') }}), 1) as componente_demanda,
        least(a.numero_reincidencia / {{ var('teto_reincidencia') }}, 1)              as componente_reincidencia,
        coalesce(e.componente_equidade, 0.5)            -- sem subprefeitura: neutro
                                                                                       as componente_equidade
    from abertas as a
    left join equidade as e using (subprefeitura)
),

score as (
    select
        *,
        10 * (  {{ var('peso_espera') }}       * componente_espera
              + {{ var('peso_via') }}          * componente_via
              + {{ var('peso_demanda') }}      * componente_demanda
              + {{ var('peso_reincidencia') }} * componente_reincidencia
              + {{ var('peso_equidade') }}     * componente_equidade)                  as score
    from componentes
)

select
    -- id_ocorrencia desempata o que inicio não desempata: a posição não muda entre execuções
    row_number() over (order by score desc, inicio, id_ocorrencia)                     as posicao_fila,
    id_ocorrencia,
    round(score, 2)                                                                    as score,
    componente_espera,
    componente_via,
    componente_demanda,
    componente_reincidencia,
    componente_equidade,
    inicio,
    data_extracao,
    dias_em_aberto,
    qtd_chamados,
    numero_reincidencia,
    flag_corredor,
    tipo_via,
    logradouro,
    distrito_final,
    subprefeitura,
    zona,
    celula_r8,
    lat_aprox,
    lon_aprox
from score
