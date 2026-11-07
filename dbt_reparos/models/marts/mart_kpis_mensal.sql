-- KPIs por mês (de abertura) e zona. Ocorrências entram no mês do primeiro chamado.
-- Atenção ao ler os meses recentes: a taxa de resolução e o % de reincidência ainda vão subir,
-- porque parte das ocorrências abertas há pouco tempo ainda não teve chance de ser resolvida.

with chamados as (
    select date_trunc('month', c.data_abertura) as mes, coalesce(l.zona, 'Sem zona') as zona
    from {{ ref('fato_chamado') }} as c
    left join {{ ref('dim_local') }} as l on l.distrito = c.distrito_final
),

ocorrencias as (
    select date_trunc('month', o.inicio) as mes, coalesce(l.zona, 'Sem zona') as zona,
           o.situacao, o.numero_reincidencia,
           case when o.situacao = 'resolvida' then date_diff('day', o.inicio, o.fim) end as tempo_reparo_dias
    from {{ ref('fato_ocorrencia') }} as o
    left join {{ ref('dim_local') }} as l on l.distrito = o.distrito_final
),

por_chamado as (
    select mes, zona, count(*) as chamados
    from chamados
    group by all
),

por_ocorrencia as (
    select
        mes,
        zona,
        count(*)                                                        as ocorrencias,
        count(*) filter (where situacao = 'resolvida') / count(*)       as taxa_resolucao,
        median(tempo_reparo_dias)                                       as tempo_reparo_mediano_dias,
        count(*) filter (where numero_reincidencia > 0) / count(*)      as pct_reincidencia
    from ocorrencias
    group by all
)

select
    cast(mes as date)                                   as mes,
    zona,
    coalesce(c.chamados, 0)                             as chamados,
    coalesce(o.ocorrencias, 0)                          as ocorrencias,
    o.taxa_resolucao,
    o.tempo_reparo_mediano_dias,
    o.pct_reincidencia,
    t.flag_periodo_chuvoso
from por_chamado as c
full join por_ocorrencia as o using (mes, zona)
join {{ ref('dim_tempo') }} as t on t.data = cast(mes as date)
order by mes, zona
