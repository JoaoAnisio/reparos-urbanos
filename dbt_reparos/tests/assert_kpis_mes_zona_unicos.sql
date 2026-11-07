-- Uma linha por mês e zona.
select mes, zona, count(*) as linhas
from {{ ref('mart_kpis_mensal') }}
group by all
having count(*) > 1
