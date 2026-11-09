-- Abertas há mais de dias_verificar_em_campo (180) dias: lista para a equipe confirmar se o buraco
-- ainda existe antes de qualquer despacho. Ordenada pelos dias em aberto, das mais antigas para as
-- mais novas. Não entram na fila de prioridade (mart_fila_prioridade).

select
    row_number() over (order by o.dias_em_aberto desc, o.inicio, o.id_ocorrencia)   as posicao_verificacao,
    o.id_ocorrencia,
    o.dias_em_aberto,
    o.inicio,
    o.data_extracao,
    o.qtd_chamados,
    o.numero_reincidencia,
    o.flag_corredor,
    o.tipo_via,
    o.logradouro,
    o.distrito_final,
    l.subprefeitura,
    l.zona,
    o.celula_r8,
    o.lat_aprox,
    o.lon_aprox
from {{ ref('fato_ocorrencia') }} as o
left join {{ ref('dim_local') }} as l on l.distrito = o.distrito_final
where o.situacao = 'aberta'
  and o.dias_em_aberto > {{ var('dias_verificar_em_campo') }}
