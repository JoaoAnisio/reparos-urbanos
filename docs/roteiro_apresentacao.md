# Roteiro da apresentação (5 minutos)

Antes de começar: `make painel` já aberto no navegador, zona "Todas" e corredor "todos".
Não rode a pipeline com o painel aberto (o DuckDB não aceita gravação com o banco aberto).

## 1. O problema e a fonte (30 s)

- São Paulo recebe de 21 a 33 mil pedidos de tapa-buraco por trimestre pelo SP156.
- A fonte são os dados abertos da prefeitura: um CSV por trimestre, licença CC0. Usei 9
  trimestres, de 07/2024 a 09/2026: 4,9 milhões de chamados de todos os serviços, 244 mil de
  tapa-buraco.
- A pergunta: **onde estão os problemas reais, quanto demoram e quanto voltam?** Um pedido não é
  um buraco.

## 2. O que os dados escondiam (60 s)

- **O formato muda sem aviso.** Oito trimestres em `dd/mm`, Latin-1 e ponto e vírgula; o último
  em `mm/dd`, UTF-8 e vírgula. Lido do jeito errado, 62% das datas ficam inválidas e o resto troca
  dia e mês, sem erro nenhum. Por isso a ingestão testa os dois formatos e recusa se houver dúvida.
- **O Excel passou por aqui.** O 2025T1 tem exatamente 1.048.575 linhas, o limite de uma planilha,
  e 305 mil delas vazias.
- **Trimestres fechados são republicados.** O arquivo de 2024T3 traz finalizações de agosto de
  2026: o portal regenerou os arquivos antigos. Por isso a bronze guarda versões em vez de
  sobrescrever.

## 3. De chamados para problemas reais (60 s)

- **Metade é repetição:** 49,6% dos chamados têm outro na mesma rua, a até 80 m, na mesma semana.
- O limite de 80 m foi **medido**, não chutado: comparei com chamados abertos meses depois no mesmo
  lugar (o grupo de controle) e vi onde o excesso acaba.
- Os chamados ligados formam um grafo; cada componente conexo é um problema físico.
  **244 mil chamados viram 129 mil problemas.**
- **A rajada da Rua Anoriaçu:** um só problema com 361 chamados, 96% pelo aplicativo, 189 ainda
  abertos. 361 pedidos viraram uma única ocorrência registrada (se é um trecho estragado ou dois
  buracos vizinhos, os dados não dizem).

## 4. O buraco que volta? (45 s)

- **45% dos problemas surgem a até 80 m de um problema já encerrado no último ano.** Mas isso não
  quer dizer que o mesmo buraco voltou.
- Mesmo método dos 80 m: comparar com a faixa seguinte da rua, de 80 a 160 m. Lá, 35% também têm um
  problema encerrado antes. **Só uns 10 pontos são atribuíveis ao mesmo ponto**; o resto é rua com
  muito chamado.
- O corredor de ônibus parecia pior (59% contra 45%), mas o controle também é maior: ele tem mais
  chamados, não mais reincidência. O que o corredor tem de fato é reparo mais lento: 14 dias de
  mediana contra 6.
- Ressalva honesta: "finalizado" no SP156 é o encerramento do chamado, não a garantia de conserto.

## 5. A fila e o mapa, ao vivo (60 s)

- **Indicadores no topo:** 16,7 mil problemas abertos (9 mil na fila, 7,7 mil a verificar em
  campo), 6 dias de mediana para reparar. A taxa de resolução usa ocorrências de 15 a 3 meses atrás,
  para não contar como "não resolvido" o que abriu ontem.
- **Mapa:** os hexágonos H3 mostram onde se concentram os chamados do último ano.
- **Fila:** abra o top 10 e o "Por que essa ordem?". O score combina espera, tipo de via, demanda,
  reincidência e equidade, com os pesos à vista.
- Mostre a lista **"Verificar em campo"**: problemas abertos há mais de 180 dias saem da fila,
  porque a pergunta para eles é outra, "isso ainda existe?".
- Filtre **Leste** e **corredor = sim**: tudo se recalcula.
- Mostre a série mensal: as faixas do período chuvoso e a previsão. Conte que o modelo sazonal
  **perdeu** para "repetir o último mês" no backtest (erro de 144 contra 109), e por isso o painel
  usa o mais simples.

## 6. LGPD e equidade: o que o sistema não mostra (30 s)

- O painel não mostra chamado individual, número do imóvel nem CEP. As coordenadas ficam com 3
  casas decimais (~110 m), e o mapa só mostra células com pelo menos 3 chamados (k-anonimato).
- Um teste de dados falha se surgir uma coluna com nome de dado pessoal.
- Equidade: a tabela por subprefeitura mostra o uso de canais digitais e o tempo de reparo. Regiões
  que usam menos o aplicativo podem estar sub-representadas, e o score dá peso a quem já espera mais.

## 7. Próximos passos (15 s)

- Um dado de severidade (tamanho ou risco do buraco) para a fila não depender só de aproximações.
- O contorno real do município no lugar do retângulo.
- Mais histórico para a previsão sazonal ter chance contra a ingênua.
