select distinct
    canal
from {{ ref('stg_chamados') }}
