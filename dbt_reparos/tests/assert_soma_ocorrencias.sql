-- Cada chamado está em exatamente uma ocorrência: a soma de qtd_chamados é o total de chamados.

with ocorrencias as (
    select sum(qtd_chamados) as soma from {{ ref('fato_ocorrencia') }}
),

chamados as (
    select count(*) as total from {{ ref('fato_chamado') }}
)

select ocorrencias.soma, chamados.total
from ocorrencias, chamados
where ocorrencias.soma <> chamados.total
