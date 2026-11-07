# Usa o ambiente virtual do projeto (uv venv --python 3.12 .venv && uv pip install -r requirements.txt)
PY ?= .venv/bin/python
DBT ?= $(abspath .venv/bin/dbt)

.PHONY: pipeline testes painel

pipeline:        ## bronze -> silver -> gold (dbt) -> previsão
	$(PY) -m scripts.rodar_pipeline

testes:          ## testes de código (pytest) e testes de dados da gold (dbt test)
	$(PY) -m pytest -q
	cd dbt_reparos && $(DBT) test --profiles-dir .

painel:          ## painel Streamlit (lê só marts.* da gold, em modo somente leitura)
	$(PY) -m streamlit run dashboard/app.py
