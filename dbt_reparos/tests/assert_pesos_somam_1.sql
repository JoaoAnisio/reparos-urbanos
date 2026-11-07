-- Os pesos do score (vars em dbt_project.yml) precisam somar 1, para o score ir de 0 a 10.
select soma
from (
    select {{ var('peso_espera') }} + {{ var('peso_via') }} + {{ var('peso_demanda') }}
         + {{ var('peso_reincidencia') }} + {{ var('peso_equidade') }} as soma
)
where abs(soma - 1) > 1e-9
