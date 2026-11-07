-- Tipagem final da silver. Daqui em diante, nenhuma camada vê a coordenada exata nem a célula r10:
-- só lat/lon com 3 casas (~110 m) e a célula r8 (~530 m de aresta).

with fonte as (
    select * from {{ source('silver', 'chamados') }}
)

select
    -- A ordem pedida (trimestre ... orgao) deixa 26.781 linhas empatadas, e em 572 grupos elas
    -- diferem em outras colunas: as colunas seguintes desempatam para o id não mudar entre
    -- execuções. O que ainda empata são linhas idênticas, e aí a ordem não importa.
    row_number() over (
        order by trimestre, data_abertura, lat, lon, canal, status_original, orgao,
                 data_finalizacao, servico, logradouro, distrito_final, id_ocorrencia
    )                                                   as id_chamado,

    cast(data_abertura as date)                         as data_abertura,
    cast(data_finalizacao as date)                      as data_finalizacao,
    cast(data_extracao as date)                         as data_extracao,
    cast(trimestre as varchar)                          as trimestre,
    cast(versao_bronze as varchar)                      as versao_bronze,

    cast(servico as varchar)                            as servico,
    cast(status as varchar)                             as status,
    cast(status_original as varchar)                    as status_original,
    cast(canal as varchar)                              as canal,
    cast(orgao as varchar)                              as orgao,

    cast(logradouro as varchar)                         as logradouro,
    {{ tipo_via('logradouro') }}                        as tipo_via,

    round(lat, 3)                                       as lat_aprox,
    round(lon, 3)                                       as lon_aprox,
    cast(celula_r8 as varchar)                          as celula_r8,

    cast(distrito_final as varchar)                     as distrito_final,
    cast(origem_distrito as varchar)                    as origem_distrito,
    cast(confianca_distrito as double)                  as confianca_distrito,

    cast(id_ocorrencia as varchar)                      as id_ocorrencia,
    cast(numero_reincidencia as integer)                as numero_reincidencia,
    cast(extensao_ocorrencia_m as double)               as extensao_ocorrencia_m,
    cast(qtd_chamados_ocorrencia as integer)            as qtd_chamados_ocorrencia,

    cast(flag_corredor as boolean)                      as flag_corredor,
    cast(flag_repeticao as boolean)                     as flag_repeticao,
    cast(flag_finalizado_sem_data as boolean)           as flag_finalizado_sem_data,
    cast(flag_sem_subprefeitura as boolean)             as flag_sem_subprefeitura,
    cast(flag_distrito_divisa as boolean)               as flag_distrito_divisa,
    cast(flag_sem_votos as boolean)                     as flag_sem_votos

from fonte
