-- Indicadores do painel, já calculados para cada combinação de zona e corredor (incluindo os totais:
-- zona = 'Todas', corredor = 'todos'). Medianas e taxas não se somam, por isso o cube.
-- Referência de tempo: a extração mais recente.

with referencia as (
    select max(data_extracao) as ultima_extracao from {{ ref('fato_ocorrencia') }}
),

ocorrencias as (
    select
        coalesce(l.zona, 'Sem zona')                                            as zona,
        case when o.flag_corredor then 'sim' else 'não' end                     as corredor,
        o.situacao,
        o.numero_reincidencia,
        o.inicio > r.ultima_extracao - interval 12 month                        as nos_12_meses,
        case when o.situacao = 'resolvida' and o.fim > r.ultima_extracao - interval 90 day
             then date_diff('day', o.inicio, o.fim) end                         as reparo_90d_dias
    from {{ ref('fato_ocorrencia') }} as o
    cross join referencia as r
    left join {{ ref('dim_local') }} as l on l.distrito = o.distrito_final
)

select
    case when grouping(zona) = 1 then 'Todas' else zona end                     as zona,
    case when grouping(corredor) = 1 then 'todos' else corredor end             as corredor,
    count(*) filter (where situacao = 'aberta')                                 as ocorrencias_abertas,
    -- reparos concluídos nos 90 dias antes da extração mais recente
    median(reparo_90d_dias)                                                     as tempo_mediano_reparo_90d_dias,
    -- ocorrências iniciadas nos 12 meses antes da extração mais recente
    count(*) filter (where nos_12_meses and situacao = 'resolvida')
        / nullif(count(*) filter (where nos_12_meses), 0)                       as taxa_resolucao_12m,
    count(*) filter (where nos_12_meses and numero_reincidencia > 0)
        / nullif(count(*) filter (where nos_12_meses), 0)                       as pct_reincidencia_12m,
    (select ultima_extracao from referencia)                                    as data_referencia
from ocorrencias
group by cube (zona, corredor)
