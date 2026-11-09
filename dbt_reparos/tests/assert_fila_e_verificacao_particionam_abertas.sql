-- Toda ocorrência aberta está em exatamente uma das duas listas: a fila (até 180 dias) ou a
-- verificação em campo (mais de 180). Devolve as que faltam ou aparecem nas duas.
with listas as (
    select id_ocorrencia from {{ ref('mart_fila_prioridade') }}
    union all
    select id_ocorrencia from {{ ref('mart_verificacao_campo') }}
),
contagem as (
    select o.id_ocorrencia, count(l.id_ocorrencia) as vezes
    from {{ ref('fato_ocorrencia') }} as o
    left join listas as l using (id_ocorrencia)
    where o.situacao = 'aberta'
    group by o.id_ocorrencia
)
select * from contagem where vezes <> 1
