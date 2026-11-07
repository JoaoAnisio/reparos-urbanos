-- A série mensal soma exatamente os chamados da fato (nenhum fica de fora do join com dim_tempo).
select s.total, f.total
from (select sum(chamados) as total from {{ ref('mart_serie_mensal') }}) as s,
     (select count(*) as total from {{ ref('fato_chamado') }}) as f
where s.total <> f.total
