-- O score é 10 x soma ponderada de componentes entre 0 e 1: fora de [0, 10] há erro de fórmula.
select posicao_fila, score
from {{ ref('mart_fila_prioridade') }}
where score < 0 or score > 10 or score is null
