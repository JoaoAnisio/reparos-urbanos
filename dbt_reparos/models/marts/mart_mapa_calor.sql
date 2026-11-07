-- Mapa de calor por célula H3 r8 (~530 m de aresta), nos últimos 12 meses antes da extração mais
-- recente. Células com menos de 3 chamados ficam de fora (k-anonimato): não se publica um ponto
-- que identifique a reclamação de uma única pessoa.

with referencia as (
    select max(data_extracao) as ultima_extracao from {{ ref('fato_ocorrencia') }}
),

chamados as (
    select c.celula_r8
    from {{ ref('fato_chamado') }} as c, referencia as r
    where c.data_abertura > r.ultima_extracao - interval 12 month
),

abertas as (
    select f.celula_r8, count(*) as ocorrencias_abertas, avg(f.score) as score_medio_abertas
    from {{ ref('mart_fila_prioridade') }} as f, referencia as r
    where f.inicio > r.ultima_extracao - interval 12 month
    group by f.celula_r8
),

por_celula as (
    select celula_r8, count(*) as chamados
    from chamados
    group by celula_r8
    having count(*) >= 3
)

select
    p.celula_r8,
    p.chamados,
    coalesce(a.ocorrencias_abertas, 0)                  as ocorrencias_abertas,
    round(a.score_medio_abertas, 2)                     as score_medio_abertas
from por_celula as p
left join abertas as a using (celula_r8)
