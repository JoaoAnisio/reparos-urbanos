-- Distrito -> subprefeitura -> zona, do seed (cópia de src/referencias/distrito_subprefeitura.csv).

select
    distrito,
    subprefeitura,
    zona
from {{ ref('distrito_subprefeitura') }}
