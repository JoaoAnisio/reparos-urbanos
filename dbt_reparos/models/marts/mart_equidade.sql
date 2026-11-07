-- Por subprefeitura: acesso digital, tempo de reparo e passivo de abertas.
-- Tempo de reparo é por ocorrência (do primeiro chamado ao fim da ocorrência resolvida), não por
-- chamado: um buraco com 30 reclamações conta uma vez.

with chamados as (
    select l.subprefeitura, l.zona, c.canal
    from {{ ref('fato_chamado') }} as c
    join {{ ref('dim_local') }} as l on l.distrito = c.distrito_final
),

ocorrencias as (
    select l.subprefeitura, o.situacao, o.dias_em_aberto,
           case when o.situacao = 'resolvida' then date_diff('day', o.inicio, o.fim) end as tempo_reparo_dias
    from {{ ref('fato_ocorrencia') }} as o
    join {{ ref('dim_local') }} as l on l.distrito = o.distrito_final
),

por_chamado as (
    select
        subprefeitura,
        any_value(zona)                                                     as zona,
        count(*)                                                            as chamados,
        count(*) filter (where canal in ('mobile', 'portal', 'chatbot')) / count(*)
                                                                            as pct_canais_digitais
    from chamados
    group by subprefeitura
),

por_ocorrencia as (
    select
        subprefeitura,
        count(*)                                                            as ocorrencias,
        median(tempo_reparo_dias)                                           as tempo_reparo_mediano_dias,
        quantile_cont(tempo_reparo_dias, 0.9)                               as tempo_reparo_p90_dias,
        count(*) filter (where situacao = 'aberta')                         as ocorrencias_abertas,
        count(*) filter (where situacao = 'aberta' and dias_em_aberto > 90)
            / nullif(count(*) filter (where situacao = 'aberta'), 0)        as pct_abertas_mais_90_dias
    from ocorrencias
    group by subprefeitura
)

select *
from por_chamado
join por_ocorrencia using (subprefeitura)
