-- Grão: 1 problema físico (ocorrência), com as mesmas regras de src/consolidacao.tabela_ocorrencias.

with chamados as (
    select * from {{ ref('stg_chamados') }}
),

-- Moda com desempate fixo: o valor mais frequente e, no empate, o primeiro em ordem alfabética.
-- O mode() do DuckDB escolhe qualquer um dos empatados, e há empate em 11 ocorrências (logradouro),
-- 296 (distrito_final) e 767 (celula_r8): a fato mudaria entre execuções sem nenhum dado novo.
-- O unpivot descarta nulos, como o mode().
frequencias as (
    select id_ocorrencia, atributo, valor, count(*) as n
    from (
        unpivot (select id_ocorrencia, logradouro, distrito_final, celula_r8 from chamados)
        on logradouro, distrito_final, celula_r8
        into name atributo value valor
    )
    group by all
),

modas as (
    select
        id_ocorrencia,
        first(valor order by n desc, valor) filter (where atributo = 'logradouro')     as logradouro,
        first(valor order by n desc, valor) filter (where atributo = 'distrito_final') as distrito_final,
        first(valor order by n desc, valor) filter (where atributo = 'celula_r8')      as celula_r8
    from frequencias
    group by id_ocorrencia
),

por_ocorrencia as (
    select
        id_ocorrencia,
        min(data_abertura)                          as inicio,
        max(data_finalizacao)                       as ultima_finalizacao,
        bool_or(status = 'aberto')                  as tem_aberto,
        bool_or(status = 'finalizado')              as tem_finalizado,
        count(*)                                    as qtd_chamados,
        max(numero_reincidencia)                    as numero_reincidencia,   -- igual em toda a ocorrência
        max(extensao_ocorrencia_m)                  as extensao_m,            -- idem
        bool_or(flag_corredor)                      as flag_corredor,
        round(avg(lat_aprox), 3)                    as lat_aprox,
        round(avg(lon_aprox), 3)                    as lon_aprox,
        max(data_extracao)                          as data_extracao
    from chamados
    group by id_ocorrencia
)

select
    p.id_ocorrencia,
    inicio,
    case when tem_aberto then null else ultima_finalizacao end            as fim,   -- só sem chamado aberto
    case when tem_aberto then 'aberta'
         when tem_finalizado then 'resolvida'
         else 'cancelada' end                                             as situacao,
    qtd_chamados,
    numero_reincidencia,
    extensao_m,
    flag_corredor,
    m.logradouro,
    m.distrito_final,
    m.celula_r8,
    lat_aprox,
    lon_aprox,
    data_extracao,
    case when tem_aberto then date_diff('day', inicio, data_extracao) end  as dias_em_aberto
from por_ocorrencia as p
left join modas as m using (id_ocorrencia)   -- left: ocorrência só com valores nulos não aparece em modas
