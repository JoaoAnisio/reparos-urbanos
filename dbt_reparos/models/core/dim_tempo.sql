-- Um dia por linha, da primeira abertura até 120 dias depois da última extração
-- (folga para datas de finalização e projeções dos marts).

with limites as (
    select min(data_abertura) as primeiro_dia, max(data_extracao) + interval 120 day as ultimo_dia
    from {{ ref('stg_chamados') }}
),

dias as (
    select cast(unnest(generate_series(primeiro_dia, ultimo_dia, interval 1 day)) as date) as data
    from limites
)

select
    data,
    year(data)                                              as ano,
    month(data)                                             as mes,
    quarter(data)                                           as trimestre,
    year(data) || 'T' || quarter(data)                      as ano_trimestre,
    isodow(data)                                            as dia_semana,      -- 1 = segunda
    ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo'][isodow(data)] as nome_dia_semana,
    isodow(data) >= 6                                       as flag_fim_de_semana,
    month(data) in (12, 1, 2, 3)                            as flag_periodo_chuvoso
from dias
