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
  abertos. Contar chamados aqui erraria por mais de 300 vezes.

## 4. O buraco que volta (45 s)

- **45% dos problemas** aparecem no mesmo ponto de um problema já encerrado; 17 mil voltaram três
  vezes ou mais, e o recorde é 23.
- No corredor de ônibus é pior: 69% de reincidência contra 55%, e o reparo leva 14 dias de mediana
  contra 6.
- Ressalva honesta: "finalizado" no SP156 é o encerramento do chamado, não a garantia de conserto.

## 5. A fila e o mapa, ao vivo (60 s)

- **Indicadores no topo:** 16,7 mil problemas abertos, 6 dias de mediana para reparar.
- **Mapa:** os hexágonos H3 mostram onde se concentram os chamados do último ano.
- **Fila:** abra o top 10 e o "Por que essa ordem?". O score combina espera, tipo de via, demanda,
  reincidência e equidade, com os pesos à vista.
- Aponte a coluna "verificar em campo": problemas abertos há mais de 180 dias podem ter status
  desatualizado, e a equipe confirma antes de despachar.
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
