import json
from pathlib import Path
import pandas as pd
from src.ingest import BRONZE, versao_vigente

linhas = []
for pasta in sorted(BRONZE.glob("trimestre=*")):
    trimestre = pasta.name.split("=")[1]
    m = json.loads((versao_vigente(trimestre) / "_manifest.json").read_text(encoding="utf-8"))
    linhas.append({k: m.get(k) for k in [
        "trimestre", "linhas", "linhas_vazias", "formato_data", "encoding", "separador",
        "datas_abertura_invalidas", "abertura_min", "abertura_max", "finalizacao_max"]})

catalogo = pd.DataFrame(linhas)
print(catalogo.to_string(index=False))
print(f"\nTotal: {catalogo['linhas'].sum():,} chamados em {len(catalogo)} trimestres")