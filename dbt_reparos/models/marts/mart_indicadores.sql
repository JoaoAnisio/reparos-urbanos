-- Indicadores do painel, já calculados para cada combinação de zona e corredor (incluindo os totais:
-- zona = 'Todas', corredor = 'todos'). Medianas e taxas não se somam, por isso o cube.
-- Referência de tempo: a extração mais recente.
--
-- Taxa de resolução e % de reincidência usam as ocorrências iniciadas entre 15 e 3 meses antes da
-- extração ("janela madura"): todas tiveram ao menos 3 meses para ser resolvidas, e todas têm um ano
-- inteiro de histórico antes delas para achar uma antecessora (os dados começam em 07/2024).
-- Com uma janela que chega até a extração, as ocorrências de poucos dias puxariam a taxa para baixo.

with referencia as (
    select max(data_extracao) as ultima_extracao from {{ ref('fato_ocorrencia') }}
),

ocorrencias as (
    select
        coalesce(l.zona, 'Sem zona')                                            as zona,
        case when o.flag_corredor then 'sim' else 'não' end                     as corredor,
        o.situacao,
        o.numero_reincidencia,
        o.inicio >  r.ultima_extracao - interval 15 month
        and o.inicio <= r.ultima_extracao - interval 3 month                    as na_janela,
        o.dias_em_aberto,
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
    count(*) filter (where situacao = 'aberta' and dias_em_aberto <= {{ var('dias_verificar_em_campo') }})
                                                                                as abertas_na_fila,
    count(*) filter (where situacao = 'aberta' and dias_em_aberto >  {{ var('dias_verificar_em_campo') }})
                                                                                as abertas_verificar_campo,
    -- reparos concluídos nos 90 dias antes da extração mais recente
    median(reparo_90d_dias)                                                     as tempo_mediano_reparo_90d_dias,
    -- ocorrências iniciadas na janela madura (15 a 3 meses antes da extração)
    count(*) filter (where na_janela and situacao = 'resolvida')
        / nullif(count(*) filter (where na_janela), 0)                          as taxa_resolucao_janela,
    count(*) filter (where na_janela and numero_reincidencia > 0)
        / nullif(count(*) filter (where na_janela), 0)                          as pct_reincidencia_janela,
    (select ultima_extracao from referencia)                                    as data_referencia,
    cast((select ultima_extracao from referencia) - interval 15 month as date)  as janela_inicio,
    cast((select ultima_extracao from referencia) - interval 3 month as date)   as janela_fim
from ocorrencias
group by cube (zona, corredor)
