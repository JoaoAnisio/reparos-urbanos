# Reparos urbanos

Pipeline de dados sobre os chamados de tapa-buraco abertos no SP156, o canal de atendimento da
Prefeitura de São Paulo. Os dados vêm do portal de dados abertos da prefeitura (licença CC0) e
passam por duas camadas:

- **Bronze** (`src/ingest.py`): cópia fiel de cada arquivo trimestral, versionada e com manifesto.
- **Silver** (`src/silver.py`, `src/geo.py`): só os chamados de tapa-buraco, com tipos corrigidos,
  validação (rejeitados vão para uma tabela própria, com o motivo), subprefeitura e zona por uma
  tabela de referência, e enriquecimento geográfico com H3 (distrito inferido, repetições).

## Como rodar

Requer Python 3.12 (`.python-version`) e o [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Coloque os CSVs trimestrais em data/raw/ (ver data/README.md)
python -m scripts.ingest_all       # bronze
python -m scripts.gerar_silver     # silver: data/silver/chamados.parquet e rejeitados.parquet
pytest -q                          # sem bronze, os testes de dados reais são pulados
```

## Limitações

**"Mesma rua" depende do nome do logradouro.** A `flag_repeticao` marca outro chamado na mesma
rua, a até 80 m e aberto em ±7 dias. A comparação é pelo nome normalizado (sem acento nem
diferença de maiúsculas), então esquinas e rodovias com dois nomes contam como ruas diferentes,
por exemplo Rua dos Piemonteses × Rua Agostinho de Azevedo e Estrada do M'Boi Mirim × SP-214.

Medido nos 244.426 chamados válidos (`python -m scripts.medir_limitacao_rua`):

| | Pares |
|---|---|
| Pares a menos de 20 m em ±7 dias | 287.578 |
| na mesma rua | 281.381 |
| **em ruas diferentes** | **6.197 (2,2%)** |

Por causa disso, **2.630 chamados (1,1%)** ficam sem `flag_repeticao`, embora tenham um vizinho a
menos de 20 m numa rua de outro nome. Expandir abreviações não resolveria: os logradouros já vêm
por extenso, e isso recuperaria só 4 chamados.

**"Fora do município" usa um retângulo, não o contorno da cidade.** Pontos de cidades vizinhas que
caem dentro do retângulo passam pela validação. Os 33 chamados com `flag_sem_votos` (nenhum
chamado com distrito na mesma célula H3 nem nas vizinhas) são, na maioria, coordenadas em
cidades vizinhas com logradouro de São Paulo, ou seja, erros de geocodificação. Eles continuam
válidos, com a flag.

**A data de extração é estimada.** O arquivo não informa quando foi gerado; `data_extracao` é a
maior data de abertura ou finalização presente nele, um limite inferior da data real.
