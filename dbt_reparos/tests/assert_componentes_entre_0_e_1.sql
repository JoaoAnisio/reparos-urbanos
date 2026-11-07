-- Cada componente precisa estar em [0, 1]; senão um peso deixa de significar o que diz.
select posicao_fila, componente_espera, componente_via, componente_demanda,
       componente_reincidencia, componente_equidade
from {{ ref('mart_fila_prioridade') }}
where not (componente_espera between 0 and 1 and componente_via between 0 and 1
           and componente_demanda between 0 and 1 and componente_reincidencia between 0 and 1
           and componente_equidade between 0 and 1)
