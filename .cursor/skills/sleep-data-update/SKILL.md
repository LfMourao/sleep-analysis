---
name: sleep-data-update
description: Puxa os dados novos do cartão do CPAP (ResMed AirSense 10) e do Garmin, reconstrói as tabelas e resume as últimas noites. Use quando o usuário avisar que há noites novas, que colocou o cartão, ou pedir para atualizar, sincronizar ou ver como foram as últimas noites.
---

# Atualizar dados do CPAP e do Garmin

Um comando faz tudo e devolve um resumo em Markdown pronto para ler. Leia o resumo, não os Parquet nem os EDF.

## Passos

1. **Contexto da noite.** Se o usuário contou algo das noites novas (fita na boca, uso parcial, mudança de máscara, remédio), grave antes do build em `data/reference/night_notes.json`, chave `YYYY-MM-DD` da noite ResMed com `mouthTape`, `partial` e `note`. Hábito com variável no catálogo (`config/habits_catalog.json`) vai em `data/reference/daily_log.csv`.
2. **Atualizar.** Na raiz do projeto:

   ```bash
   uv run sleep-update            # cartão + Garmin + build incremental + últimas 7 noites
   ```

   Concluído quando a saída termina na seção `## Últimas noites`. Cada item de `Pendências:` no fim é tratado em [Pendências](#pendências).
3. **Ler o resumo.** Ele traz a data da última noite em cada fonte, uma tabela do CPAP, uma do Garmin e o núcleo contra a referência anterior à cirurgia.
   - ⚠ = acima do Q3 da referência; ⚠⚠ = acima do P90. A referência é a pressão anterior à cirurgia mais próxima com pelo menos 8 noites de sinal, e o resumo diz qual foi usada.
   - Uma noite isolada só muda a conclusão se a diferença passar da coluna `mudança mínima`. Para tendência, use a mediana de 7 noites ou 3 noites seguidas no mesmo sentido.
   - Os indicadores que decidem são limitação de fluxo, `rin` e ronco. O AHI só se reporta. A justificativa está em `docs/quality-indicators.md`.
4. **Responder.** Comece pelo veredito das noites novas contra a referência e contra as noites anteriores na mesma pressão. Depois diga o que mudou de configuração (pressão, EPR, umidade) e se a meta combinada foi atingida.
5. **Registrar no vault.** Se a pasta `/home/lfmou/projects/obsidian` estiver aberta, atualize a tabela de dados do aparelho em `Pessoal/Saúde/cpap-pos-op.md` seguindo a skill `vault-memory` do vault.

## Pendências

| Mensagem | O que fazer |
|---|---|
| `cartão não encontrado` | O resumo usa o backup antigo; confira as datas de "Última noite". Peça para inserir o cartão ou rode `uv run sleep-update --card E:` com a letra certa. |
| `Garmin sem login` | O token em `~/.garminconnect` expirou. O login pede senha e MFA, então só o usuário consegue: peça para ele rodar `uv run sleep-garmin-sync` no terminal dele e depois `uv run sleep-update --skip-card`. |
| `Limite de requisições` (na seção Garmin) | Siga com os dados já salvos e rode `--skip-card` mais tarde. |
| `Garmin terminou com código N` | Leia a seção Garmin da saída; costuma ser rede. |

## Detalhe sob demanda

Quando o resumo não basta, consulte com DuckDB e traga só as colunas e noites necessárias:

```python
from sleep_analysis.db import connect
from sleep_analysis.features import build_night_features

features = build_night_features(connect())   # uma linha por noite, ~100 colunas, menos de 1 s
```

Tabelas e colunas: `docs/architecture.md`. `uv run sleep-latest --nights 14` reimprime o resumo sem copiar nada.

## Como o build se comporta

- O build é incremental: só relê as noites cujos arquivos no cartão mudaram. Quente, o fluxo inteiro leva cerca de 15 s.
- Mudança em `respiratory_metrics.py` recalcula só as métricas (cerca de 30 s). Mudança em `build.py`, `edf.py` ou `breaths.py` relê o cartão inteiro (cerca de 70 s). Os dois casos são detectados sozinhos.
- `--full` ignora o cache. Use só se suspeitar de cache corrompido.
- Os notebooks 07 e 08 não rodam no `sleep-update`. Reexecute-os quando o usuário pedir para refazer o ranking ou os efeitos, com o comando em `docs/architecture.md`.

## Pegadinhas

- O WSL não monta o cartão. A cópia usa `robocopy` do Windows pela letra da unidade e preserva as datas dos arquivos, e é isso que mantém o cache válido.
- A noite ResMed vai de meio-dia a meio-dia. A noite do Garmin é `calendarDate − 1`, e as duas usam a mesma chave `night`.
- Se o cartão sair do aparelho no meio da noite, a última noite fica parcial; marque `partial` em `night_notes.json`.
- O cartão guarda o nível do EPR mesmo com o EPR desligado. Use `epr_effective`, nunca `epr_level`.
