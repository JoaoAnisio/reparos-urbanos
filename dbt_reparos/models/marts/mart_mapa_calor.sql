-- Mapa de calor por célula H3 r8 (~530 m de aresta), nos últimos 12 meses antes da extração mais
-- recente. Células com menos de 3 chamados ficam de fora (k-anonimato): não se publica um ponto
-- que identifique a reclamação de uma única pessoa.

with referencia as (
    select max(data_extracao) as ultima_extracao from {{ ref('fato_ocorrencia') }}
),

chamados as (
    select c.celula_r8, coalesce(l.zona, 'Sem zona') as zona
    from {{ ref('fato_chamado') }} as c
    cross join referencia as r
    left join {{ ref('dim_local') }} as l on l.distrito = c.distrito_final
    where c.data_abertura > r.ultima_extracao - interval 12 month
),

-- Todas as abertas iniciadas na janela (inclusive as que aguardam verificação em campo)
abertas as (
    select o.celula_r8, count(*) as ocorrencias_abertas
    from {{ ref('fato_ocorrencia') }} as o, referencia as r
    where o.situacao = 'aberta' and o.inicio > r.ultima_extracao - interval 12 month
    group by o.celula_r8
),

-- Score médio só das que estão na fila de despacho (até 180 dias)
fila as (
    select f.celula_r8, avg(f.score) as score_medio_fila
    from {{ ref('mart_fila_prioridade') }} as f, referencia as r
    where f.inicio > r.ultima_extracao - interval 12 month
    group by f.celula_r8
),

por_celula as (
    -- zona mais frequente da célula (desempate alfabético), para o filtro do painel
    select celula_r8, count(*) as chamados, first(zona order by n_zona desc, zona) as zona
    from (select *, count(*) over (partition by celula_r8, zona) as n_zona from chamados)
    group by celula_r8
    having count(*) >= 3
)

select
    p.celula_r8,
    p.chamados,
    p.zona,
    coalesce(a.ocorrencias_abertas, 0)                  as ocorrencias_abertas,
    round(f.score_medio_fila, 2)                        as score_medio_fila
from por_celula as p
left join abertas as a using (celula_r8)
left join fila as f using (celula_r8)
