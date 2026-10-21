# Sleep Analysis

Um projeto para análise de padrões de sono e qualidade do sono.

## Descrição

Este projeto visa analisar e monitorar padrões de sono, fornecendo insights sobre a qualidade do sono e sugestões para melhorá-la.

Objetivos em `docs/objectives.md`, arquitetura em `docs/architecture.md` e indicadores para comparar noites em `docs/quality-indicators.md`.

## Configuração do Ambiente

Requer [uv](https://docs.astral.sh/uv/) (instala o Python 3.12 e as dependências):

```bash
uv sync
```

## Como Usar

```bash
uv run sleep-update      # tudo de uma vez: cartão, Garmin, build incremental, resumo e relatório comparativo
uv run sleep-latest      # só o resumo: indicadores do aparelho, calculados no fluxo e Garmin
uv run sleep-report      # página data/reports/comparativo.html: cirurgia, pressão e últimas 90 noites
uv run sleep-ingest D:   # backup incremental do cartão do CPAP para data/raw
uv run sleep-build       # converte os EDF em tabelas Parquet em data/processed
uv run jupyter lab       # abrir notebooks/01_overview.ipynb
```
