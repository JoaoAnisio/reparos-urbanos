-- Grão: 1 chamado.

select
    id_chamado,

    -- chaves das dimensões
    data_abertura,                  -- dim_tempo
    data_finalizacao,               -- dim_tempo (nula se não finalizado ou finalizado sem data)
    distrito_final,                 -- dim_local (nula nos 33 sem votos)
    status_original,                -- dim_status
    canal,                          -- dim_canal
    id_ocorrencia,                  -- fato_ocorrencia

    -- medidas
    case when status = 'finalizado'
         then date_diff('day', data_abertura, data_finalizacao) end    as tempo_resolucao_dias,

    -- atributos
    trimestre,
    tipo_via,
    origem_distrito,
    confianca_distrito,
    numero_reincidencia,
    celula_r8,
    lat_aprox,
    lon_aprox,

    -- flags
    flag_corredor,
    flag_repeticao,
    flag_finalizado_sem_data,
    flag_sem_subprefeitura,
    flag_distrito_divisa,
    flag_sem_votos

from {{ ref('stg_chamados') }}
