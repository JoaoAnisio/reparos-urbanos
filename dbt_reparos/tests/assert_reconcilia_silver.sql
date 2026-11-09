-- A fato_chamado tem exatamente as linhas válidas que o manifesto da silver declara.
-- Falha (devolve uma linha) se as contagens diferirem.
-- O caminho ../data/silver é relativo à pasta de onde o dbt é chamado: rode de dentro de
-- dbt_reparos/ (é o que make pipeline e scripts/rodar_pipeline.py fazem).

with manifesto as (
    select linhas_validas from read_json_auto('../data/silver/_manifest.json')
),

fato as (
    select count(*) as linhas from {{ ref('fato_chamado') }}
)

select manifesto.linhas_validas, fato.linhas
from manifesto, fato
where manifesto.linhas_validas <> fato.linhas
