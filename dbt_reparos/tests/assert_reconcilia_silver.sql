-- A fato_chamado tem exatamente as linhas válidas que o manifesto da silver declara.
-- Falha (devolve uma linha) se as contagens diferirem.

with manifesto as (
    select linhas_validas from read_json_auto('../data/silver/_manifest.json')
),

fato as (
    select count(*) as linhas from {{ ref('fato_chamado') }}
)

select manifesto.linhas_validas, fato.linhas
from manifesto, fato
where manifesto.linhas_validas <> fato.linhas
