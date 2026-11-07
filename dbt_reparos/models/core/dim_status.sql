-- Um status bruto da fonte por linha, com a categoria padronizada pela silver.

select distinct
    status_original,
    status
from {{ ref('stg_chamados') }}
