-- k-anonimato: nenhuma célula publicada com menos de 3 chamados.
select celula_r8, chamados
from {{ ref('mart_mapa_calor') }}
where chamados < 3
