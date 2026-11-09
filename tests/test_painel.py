"""Testes do painel (dashboard/app.py).

As regras de acesso (só marts, somente leitura) são checadas no código e rodam sempre. A execução
do app precisa da gold e é pulada sem ela (ex.: CI).
"""
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
GOLD = APP.parent.parent / "data" / "gold" / "reparos.duckdb"


def test_painel_so_le_marts_em_modo_somente_leitura():
    codigo = APP.read_text(encoding="utf-8")
    assert not re.search(r"\b(core|staging|main)\.\w", codigo), "o painel só pode ler o schema marts"
    assert "read_only=True" in codigo
    assert codigo.count("duckdb.connect(") == 1, "uma única forma de abrir o banco: a função ler()"


@pytest.mark.skipif(not GOLD.exists(), reason="gold ausente (ex.: CI); rode make pipeline")
@pytest.mark.parametrize("zona, corredor", [("Todas", "todos"), ("Leste", "sim"), ("Centro", "não")])
def test_painel_roda_sem_erro_com_filtros(zona, corredor):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(APP), default_timeout=60)
    app.run()
    app.sidebar.selectbox[0].set_value(zona)
    app.sidebar.radio[0].set_value(corredor)
    app.run()
    assert not app.exception, app.exception
    assert len(app.metric) == 4
    assert len(app.dataframe) >= 4      # fila, componentes, verificação em campo e equidade
    assert any("errou menos no backtest" in c.value for c in app.caption) or corredor != "todos"
