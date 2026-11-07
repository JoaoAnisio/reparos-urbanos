-- Uma linha por zona e corredor (o cube não pode repetir combinações).
select zona, corredor, count(*) as linhas
from {{ ref('mart_indicadores') }}
group by all
having count(*) > 1
