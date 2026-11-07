-- Chamados por mês de abertura, zona e corredor: contagens que se somam, para o painel filtrar.

select
    cast(date_trunc('month', c.data_abertura) as date)              as mes,
    coalesce(l.zona, 'Sem zona')                                    as zona,
    case when c.flag_corredor then 'sim' else 'não' end             as corredor,
    count(*)                                                        as chamados,
    any_value(t.flag_periodo_chuvoso)                               as flag_periodo_chuvoso
from {{ ref('fato_chamado') }} as c
left join {{ ref('dim_local') }} as l on l.distrito = c.distrito_final
join {{ ref('dim_tempo') }} as t on t.data = cast(date_trunc('month', c.data_abertura) as date)
group by all
