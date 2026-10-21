# Indicadores de qualidade do sono

## Conclusão

1. **Para comparar noites, use dois indicadores do aparelho: limitação de fluxo (`device_flow_lim_min_h`) e despertares respiratórios (`rin`).** São os únicos que se repetem de forma estável e caem quando a pressão sobe. O ronco (`snore_min_h`) confirma a leitura, mas mede quase a mesma coisa que a limitação.
2. **O AHI não serve para ranquear noites.** Ele fica em torno de 0,6/h, varia ao acaso de uma noite para outra (ICC 0,07) e não reage às trocas de pressão. Serve para mostrar que o tratamento controla apneias, não para dizer qual noite foi melhor.
3. **O aparelho conta menos eventos que o fluxo bruto, mas isso vem sobretudo da definição de evento, não de eventos escondidos.** Com a mesma regra da ResMed (queda de 50%), o fluxo dá 1,7/h contra 0,6/h do aparelho, e os dois quase não marcam os mesmos eventos. A literatura indica subcontagem de cerca de 1/h contra polissonografia; sem polissonografia aqui, isso fica possível, não provado.
4. **Entre 5,8 e 9,0 cmH2O, mais pressão deu noites melhores** em limitação, `rin` e ronco, com ganho que quase estabiliza a partir de 8,0. EPR e umidade não mudaram o núcleo de forma confiável.
5. **O Garmin confirma o sentido, não o tamanho.** O índice novo concorda com HRV, FC de repouso e estresse do relógio (correlação média 0,17, fraca). O índice antigo do notebook 03 apontava o sentido contrário (−0,18).

| Pergunta | Resposta | Confiança |
|---|---|---|
| Qual indicador usar para comparar noites? | Limitação de fluxo + `rin` (índice v2) | Média: passam no corte de repetibilidade, mas o Garmin só confirma de leve |
| O aparelho subestima eventos? | Conta menos que o fluxo; a maior parte é diferença de algoritmo | Baixa a média: falta polissonografia |
| Qual pressão foi melhor? | 8,0: melhor relação entre ganho e horas de uso antes da cirurgia | Média: efeito claro, mas a cirurgia de 28/09/2026 mudou a via aérea |
| EPR e umidade importam? | Não de forma confiável no núcleo | Baixa: EPR só ficou ligado em 41 noites e nunca foi alternado de propósito |

## Ranking dos indicadores

A nota vai de 0 a 1 e combina seis critérios (explicados em [Como a nota é calculada](#como-a-nota-é-calculada)). O papel final, na última coluna, não segue só a nota: o indicador precisa passar no corte de repetibilidade (ICC ≥ 0,40 **ou** metades ≥ 0,70) para entrar no índice.

**Origem:** STR = resumo diário do aparelho; PLD = sinais do aparelho a cada 2 s; BRP = fluxo bruto a 25 Hz, processado por este repositório; Garmin = relógio.

**Resposta à pressão:** quanto o indicador muda por cmH2O a mais, medido só nas noites coladas a uma troca de pressão, e em quantas trocas ele andou no sentido esperado.

| # | Indicador | O que mede | Origem | Nota | ICC / metades | Resposta à pressão | Papel |
|---|---|---|---|---|---|---|---|
| 1 | `device_flow_lim_min_h` | Minutos por hora em que o aparelho marca limitação de fluxo (via aérea parcialmente estreitada, sem chegar a evento) | PLD (canal FlowLim) | 0,62 | 0,52 / 0,74 | −2,27 min/h, 9 de 10 trocas | **Núcleo** |
| 2 | `garmin_resting_heart_rate` | FC de repouso do dia | Garmin | 0,57 | 0,33 / — | não se aplica | Desfecho externo |
| 3 | `garmin_spo2_avg` | Saturação média do sono, oxímetro de pulso | Garmin | 0,57 | 0,33 / — | não se aplica | Fora: só tendência |
| 4 | `rin` | Despertares respiratórios por hora (RERA da ResMed): esforço que acorda sem virar apneia | STR | 0,54 | 0,26 / 0,82 | −0,17/h, 8 de 13 | **Núcleo** |
| 5 | `garmin_sleep_stress` | Estresse médio no sono, derivado da HRV | Garmin | 0,52 | 0,17 / — | não se aplica | Desfecho externo |
| 6 | `hypopnea50_per_usage_h` | Quedas de ≥50% da ventilação por ≥10 s, por hora: o equivalente do AHI calculado no fluxo | BRP | 0,51 | 0,22 / 0,55 | −0,53/h, 7 de 10 | Reportar |
| 7 | `snore_min_h` | Minutos por hora com ronco detectado pelo aparelho | PLD (canal Snore) | 0,50 | 0,21 / 0,85 | −0,35 min/h, 6 de 10 | **Apoio**: passa o corte, mas repete a limitação |
| 8 | `surge_index` | Saltos de ventilação (≥1,5× por 2 respirações) por hora, sinal de microdespertar | BRP | 0,50 | 0,24 / 0,43 | −1,64/h, 7 de 10 | Fora: ruidoso |
| 9 | `garmin_body_battery_change` | Quanto a Body Battery subiu durante a noite | Garmin | 0,49 | 0,07 / — | não se aplica | Fora |
| 10 | `garmin_sleep_hours` | Horas de sono estimadas pelo relógio | Garmin | 0,48 | ~0 / — | não se aplica | Contexto (dose) |
| 11 | `hypopnea30_per_usage_h` | Quedas de ≥30% por ≥10 s, por hora (sem exigir dessaturação) | BRP | 0,47 | 0,10 / 0,67 | −0,65/h, 7 de 10 | Fora: conta demais |
| 12 | `garmin_deep_hours` | Horas de sono profundo | Garmin | 0,47 | 0,04 / — | não se aplica | Fora: fase pouco confiável |
| 13 | `garmin_awake_count` | Número de despertares | Garmin | 0,46 | ~0 / — | não se aplica | Desfecho externo (fraco) |
| 14 | `garmin_sleep_score` | Nota de sono proprietária | Garmin | 0,46 | ~0 / — | não se aplica | Fora |
| 15 | `garmin_rem_hours` | Horas de REM | Garmin | 0,46 | ~0 / — | não se aplica | Fora: fase pouco confiável |
| 16 | `usage_hours` | Horas com a máscara | STR | 0,46 | ~0 / — | não se aplica | **Dose**: filtro ≥ 4 h |
| 17 | `flow_limited_pct` | % das respirações com curva inspiratória achatada | BRP | 0,45 | 0,39 / — | −0,19, 7 de 10 | Fora: sobe com vazamento |
| 18 | `rera_like_index` | Achatamento seguido de salto de ventilação, por hora: RERA estimado no fluxo | BRP | 0,45 | −0,06 / 0,34 | −0,44/h, 9 de 10 | Fora: instável |
| 19 | `hi` | Hipopneias por hora | STR | 0,44 | 0,04 / 0,13 | −0,20/h, 8 de 13 | Reportar |
| 20 | `ahi` | Apneias + hipopneias por hora | STR | 0,42 | 0,07 / 0,20 | 0, 6 de 13 | Reportar |
| 21 | `garmin_hrv` | HRV noturna média | Garmin | 0,42 | 0,20 / — | não se aplica | Desfecho externo (só 40% das noites) |
| 22 | `wake_like_bouts` | Blocos de respiração irregular, usados como proxy de vigília | BRP | 0,41 | 0,29 / — | não se aplica | Fora |
| 23 | `periodicity_index` | Fração da ventilação que oscila em ciclos de 30 a 100 s (padrão periódico) | BRP | 0,41 | 0,37 / — | não se aplica | Fora: vigiar se subir |
| 24 | `apnea90_per_usage_h` | Quedas de ≥90% por ≥10 s, por hora: apneia pela regra da AASM | BRP | 0,40 | 0,06 / 0,49 | +0,13/h, 3 de 10 | Fora |
| 25 | `stable_pct` | % de janelas de 5 min com respiração regular e sem evento | BRP | 0,39 | 0,24 / — | −0,31, 5 de 10 | Leitura por terço da noite |
| 26 | `oai` | Apneias obstrutivas por hora | STR | 0,39 | 0,06 / −0,02 | 0, 5 de 13 | Reportar |
| 27 | `mask_events_per_h` | Vezes por hora que a máscara saiu e voltou | STR | 0,39 | 0,02 / — | não se aplica | Contexto (dose) |
| 28 | `cai` | Apneias centrais por hora | STR | 0,36 | 0,09 / 0,23 | 0, 2 de 13 | Reportar; vigiar se a pressão subir |
| 29 | `apnea_cluster_per_h` | Episódios de 3+ apneias em 5 min, por hora | EVE | 0,33 | 0,30 / — | 0, 0 de 10 | Fora: quase sempre zero |

**Como ler os papéis:**

- **Núcleo:** compõe o índice da noite.
- **Apoio:** confirma o núcleo; não entra no índice para não contar a mesma coisa duas vezes.
- **Desfecho externo:** usado para checar se o índice aponta para uma noite melhor, nunca como medida da via aérea.
- **Reportar:** número clínico para acompanhar e mostrar ao médico; não ranqueia noites.
- **Dose:** diz quanto tratamento houve; serve de filtro e covariável.
- **Fora:** não passa no corte ou depende de artefato.

**Por que o Garmin aparece alto no ranking e não entra no núcleo.** Indicadores do relógio não têm resposta à pressão nem convergência (não faz sentido validar o Garmin contra o próprio Garmin), então a nota deles é calculada só com os critérios restantes, em que se saem bem: cobertura alta e pouca interferência de vazamento. Nenhum passa no corte de repetibilidade, e a validação publicada é fraca para fases e moderada para HRV.

## Grupo calculado (relatório)

O `sleep-latest` mostra dois grupos lado a lado: os indicadores do aparelho (núcleo acima) e um indicador calculado no fluxo de 25 Hz por dimensão fisiológica. Os calculados não entram no índice, mas aparecem sempre, com a mesma referência e as mesmas marcas.

**Por que mostrar os dois.** A repetibilidade baixa dos calculados não prova que eles medem mal:

- Hábitos, estresse e comida mudam a noite de verdade e derrubam o ICC entre noites. As metades da mesma noite não sofrem esse efeito. Mesmo assim, os calculados também concordam menos entre as metades (0,43 a 0,67) que os do aparelho (0,74 a 0,85). Parte do ruído é de contagem: com 1 a 2 eventos por hora, cada metade tem poucos eventos.
- O canal de limitação do aparelho não é uma fórmula sintética lisa. Os trechos com limitação duram em mediana 10 s (P90 24 s), poucas respirações.
- Não há validação publicada contra polissonografia para os canais de limitação, RERA (`rin`) e ronco da ResMed; só o AHI do aparelho foi validado (Iftikhar 2023; Desai 2009). Os calculados seguem definições da literatura. Os do aparelho são estáveis e reagem à pressão, mas o algoritmo é fechado.

**Escolhidos.** Repetibilidade e resposta à pressão nas noites antes da cirurgia com uso ≥ 4 h; evidência pela literatura.

| Dimensão | Indicador | ICC / metades | Pressão | Evidência | Por que entra |
|---|---|---|---|---|---|
| Limitação inspiratória | `flow_limited_pct` (achatadas %) | 0,39 / — | 7 de 10 | Moderada | O sinal de fluxo com melhor ligação a sintomas: dobrou a chance de sonolência com IAH < 15 (Mann 2024), associou-se a lapsos de vigilância independentemente do IAH (Staykov 2024) e subiu de 2,9% para 14,7% do sono com CPAP subótimo, com o IAH quase parado (Parekh 2021). Sobe com vazamento |
| Eventos | `hypopnea50_per_usage_h` (IAH fluxo) | 0,22 / 0,55 | 7 de 10 | Moderada para eficácia, fraca para sintomas | O número clínico, com a regra de 50% e por hora de uso, comparável ao AHI do aparelho. A definição muda muito o resultado (Ruehland 2009); sem SpO2 nem EEG não dá para aplicar a regra da AASM (Berry 2012) |
| Fragmentação | `surge_index` (surge) | 0,24 / 0,43 | 7 de 10 | Fraca a moderada | O salto de ventilação depois do evento cresce com o despertar e a intensidade dele (Amatoury 2016; Zhang 2026). Também conta suspiros do sono tranquilo |
| Estabilidade | `stable_pct` (estável %), menor é pior | 0,24 / — | 5 de 10 | Moderada para sono e vigília | Respiração regular marca o NREM estável (Thomas 2005; Wood 2020); irregularidade no fluxo do CPAP previu vigília no EEG (Ayappa 2009) |
| Contexto | `flow_resp_rate` (FR), sem marca | — | — | Fraca | Muda com estado e doença (Douglas 1982). Caiu de 17,4 para 16 depois da cirurgia |

**Fora do relatório:**

- `ned_median`: é a entrada do `flow_limited_pct`; liga-se ao local do colapso (Genta 2017), não a sintomas.
- `flatness_median`: ICC 0,73, o mais estável de todos, mas muda só 0,011 por cmH2O.
- `hypopnea30_with_surge_index` (ICC −0,04) e `rera_like_index` (−0,06): instáveis.
- `periodicity_index`: vigiar se a pressão subir, pela apneia central que surge com o tratamento (Liu 2017); o CAI do aparelho já cobre.
- Carga ventilatória (Parekh 2023: ICC 0,89 e mortalidade cardiovascular): testada em 21/10/2026 como % de respirações abaixo de 50% da base local, de 5 min e da noite. Deu ICC de 0,21 a 0,27, sem resposta à pressão e ρ 0,74 a 0,79 com o IAH do fluxo. Não reproduziu; o artigo usa a ventilação suavizada, não respiração a respiração.

Referências do grupo calculado:

- Ruehland 2009 ([10.1093/sleep/32.2.150](https://doi.org/10.1093/sleep/32.2.150))
- Berry 2012 ([10.5664/jcsm.2172](https://doi.org/10.5664/jcsm.2172))
- Iftikhar 2023 ([10.1007/s11325-023-02780-w](https://doi.org/10.1007/s11325-023-02780-w))
- Desai 2009 ([10.1007/s11325-009-0258-2](https://doi.org/10.1007/s11325-009-0258-2))
- Mann 2024 ([10.1513/AnnalsATS.202308-710OC](https://doi.org/10.1513/AnnalsATS.202308-710OC))
- Staykov 2024 ([10.1016/j.chest.2023.11.031](https://doi.org/10.1016/j.chest.2023.11.031))
- Parekh 2021 ([10.1093/sleep/zsab010](https://doi.org/10.1093/sleep/zsab010))
- Parekh 2023 ([10.1164/rccm.202301-0109OC](https://doi.org/10.1164/rccm.202301-0109OC))
- Amatoury 2016 ([10.5665/sleep.6304](https://doi.org/10.5665/sleep.6304))
- Zhang 2026 ([10.1111/jsr.70412](https://doi.org/10.1111/jsr.70412))
- Thomas 2005 ([10.1093/sleep/28.9.1151](https://doi.org/10.1093/sleep/28.9.1151))
- Wood 2020 ([10.3389/fphys.2020.592978](https://doi.org/10.3389/fphys.2020.592978))
- Ayappa 2009 ([PMC2625330](https://pmc.ncbi.nlm.nih.gov/articles/PMC2625330/))
- Douglas 1982 ([10.1136/thx.37.11.840](https://doi.org/10.1136/thx.37.11.840))
- Genta 2017 ([10.1016/j.chest.2017.06.017](https://doi.org/10.1016/j.chest.2017.06.017))
- Liu 2017 ([10.1016/j.chest.2017.06.010](https://doi.org/10.1016/j.chest.2017.06.010))

## O índice da noite (v2)

O índice compara a noite com a linha de base da mesma pressão, em desvios-padrão. Usa limitação de fluxo e `rin`, pesados pela estabilidade de cada um. **Maior = pior; 0 = noite típica.** Foi calibrado nas noites até abril/2026 e testado nas noites de maio em diante (125 noites), contra o Garmin:

| Desfecho do Garmin | Índice v2 | Índice v1 (notebook 03) |
|---|---|---|
| HRV (maior é melhor) | 0,28 ✔ | −0,19 ✘ |
| FC de repouso | 0,18 ✔ | −0,33 ✘ |
| Estresse no sono | 0,16 ✔ | −0,18 ✘ |
| Despertares | 0,08 ✔ | −0,04 ✘ |
| **Média** | **0,17** | **−0,18** |

Valores positivos significam que índice pior acompanha relógio pior, o sentido esperado. O v2 acerta o sentido nos quatro desfechos; o v1 erra nos quatro. A força é fraca: o índice ordena bem períodos, não noites isoladas.

## Linha de base a 7,0 cmH2O

Baseada em 73 noites com uso ≥ 4 h e sinal, de 12/12/2025 a 27/09/2026, antes da cirurgia. Acima do Q3 é atenção; acima do P90 é regressão. Para horas de uso, o pior é para baixo.

| Indicador | Mediana | Atenção | Regressão | Mudança mínima detectável numa noite |
|---|---|---|---|---|
| Limitação de fluxo | 8,8 min/h | > 9,9 | > 11,1 | 4,6 min/h |
| `rin` | 0,1/h | > 0,2 | > 0,3 | 0,83/h |
| Ronco | 0,24 min/h | > 0,40 | > 0,59 | 1,1 min/h |
| Horas de uso | 7,9 h | < 7,2 h | < 6,6 h | 3,0 h |
| AHI do aparelho | 0,6/h | > 0,8 | > 1,0 | 0,98/h |

**A mudança mínima detectável é maior que a faixa de alerta.** Uma noite isolada com 11 min/h de limitação está na faixa de regressão, mas a diferença para a mediana (2,2) é menor que o ruído (4,6). Por isso:

- compare a **mediana de 7 noites**, ou exija **3 noites seguidas** no mesmo sentido;
- o ronco usual (0,2 a 0,6 min/h) cabe inteiro dentro do ruído e só se lê na semana.

## Efeito da pressão, do EPR e da umidade

Regressão com erro robusto à autocorrelação (Newey-West), bootstrap em blocos de 7 dias e correção para múltiplos testes (q = p ajustado por Benjamini-Hochberg). Um efeito só conta como confiável com q < 0,05 **e** intervalo do bootstrap fora do zero. Noites antes da cirurgia de 28/09/2026, de 5,8 a 9,0 cmH2O.

| Fator | Limitação de fluxo | `rin` | Ronco | AHI |
|---|---|---|---|---|
| +1 cmH2O de pressão | **−1,23 min/h** (q 0,002) | **−0,10/h** (q < 0,001) | **−0,22 min/h** (q 0,002) | −0,04/h (q 0,14) |
| +1 nível de EPR ligado | −0,89 min/h (q 0,001; bootstrap cruza zero) | 0 | 0 | −0,08/h (q 0,03), abaixo do ruído |
| +1 nível de umidade | −0,40 min/h (q 0,09) | 0 | 0 | 0 |

Mediana por faixa de pressão, mesmo período:

| Pressão (cmH2O) | Noites | Limitação de fluxo | `rin` | Ronco | AHI | Uso |
|---|---|---|---|---|---|---|
| 6,2–6,7 | 23 | 10,6 min/h | 0,2/h | 0,47 min/h | 0,7/h | 8,3 h |
| 6,8–7,1 | 75 | 8,8 | 0,1 | 0,24 | 0,6 | 7,9 h |
| 7,2–7,7 | 29 | 7,9 | 0,1 | 0,21 | 0,6 | 8,2 h |
| 7,8–8,1 | 48 | 6,9 | 0,0 | 0,16 | 0,5 | 8,1 h |
| 8,2–8,7 | 34 | 6,7 | 0,0 | 0,11 | 0,6 | 7,6 h |
| 8,8–9,0 | 14 | 6,0 | 0,0 | 0,16 | 0,4 | 7,3 h |

- **Pressão:** efeito claro e consistente nos três indicadores do núcleo, na regressão e nas trocas isoladas. O ganho grande vai até 8,0; acima disso a limitação melhora pouco e o uso cai cerca de meia hora.
- **EPR:** o cartão guarda o nível mesmo com o EPR desligado (`epr_enabled` = 0). A análise usa `epr_effective` (nível se ligado, 0 se desligado). O EPR só ficou ligado em 41 noites, em janeiro e março de 2026; o sinal na limitação não resiste ao bootstrap. Fica como hipótese para um teste ABAB.
- **Umidade:** nada no núcleo. A fração de janelas estáveis (`stable_pct`) sobe 1,5 ponto por nível (q < 0,001), mas é um indicador fora do corte de repetibilidade.
- **Depois da cirurgia:** palato e nariz mudaram em 28/09/2026. A curva acima orienta o primeiro ajuste, não substitui as noites novas.

## O aparelho subestima eventos?

**Em parte sim, mas a maior diferença vem da regra usada para contar.** Quanto mais folgado o limiar, mais eventos o fluxo encontra:

| Contagem no fluxo bruto | Mediana por hora de uso |
|---|---|
| Queda de 30% (só fluxo; a AASM exige também dessaturação ou despertar) | 6,78 |
| Queda de 40% | 3,12 |
| **Queda de 50% (regra de hipopneia da ResMed; já inclui as apneias)** | **1,66** |
| Queda de 75% (regra de apneia da ResMed) | 0,79 |
| Queda de 90% (regra de apneia da AASM) | 0,74 |
| AHI do aparelho | 0,60 |

**Os dois marcam eventos diferentes, mesmo com a mesma regra.** Casando evento por evento, com 15 s de folga:

| Comparação | Eventos do aparelho achados pelo fluxo | Eventos do fluxo confirmados pelo aparelho |
|---|---|---|
| Aparelho × queda de 30% | 75% | 3% |
| Aparelho × queda de 50% | 44% | 7% |
| Apneias × queda de 90% | 29% | 9% |

Por noite, a concordância de Lin entre AHI e fluxo a 50% é 0,09 (quase nenhuma), e o fluxo conta em média 1,18/h a mais. Essa diferença cresce nas noites piores (Spearman 0,68).

**Por que divergem.** O detector deste repositório compara a ventilação média com a mediana local; o aparelho usa o próprio algoritmo de queda de fluxo. Dos eventos do fluxo sem par no aparelho:

- 36% vêm logo depois de um salto de ventilação (o fim de um despertar, que derruba a ventilação por alguns segundos);
- 31% duram 10 a 12 s, no limite da definição;
- 43% não têm explicação por vazamento, início de sessão, rampa, vigília ou os dois motivos acima.

Vazamento e rampa não explicam nada: a rampa nunca esteve ligada e o vazamento p95 está em zero desde junho/2026.

**O que a literatura diz.** A meta-análise de Iftikhar (Sleep and Breathing, 2023) encontrou viés médio de −1,01/h dos CPAP ResMed contra polissonografia, com limites de −3,55 a +1,54. No S9, Baek (2016) viu subcontagem de 1,30/h, concentrada nas hipopneias. Ou seja, o aparelho pode subestimar cerca de 1/h, o que levaria o AHI de 0,6 para algo perto de 1,6/h: ainda bem abaixo de 5/h, o limite de controle adequado. A frequência respiratória do aparelho e a do fluxo concordam (Spearman 0,96), então o sinal é o mesmo; o que difere é a regra.

**Não somar** `hypopnea50` com `apnea75` ou `apnea90`: o de 50% já contém as quedas mais fundas.

## Como a nota é calculada

| Critério | Peso | O que responde | Como foi medido |
|---|---|---|---|
| Repetibilidade | 0,25 | A medida é estável? | Média do ICC de noites vizinhas na mesma pressão com a confiabilidade das metades (horas pares contra ímpares da mesma noite) |
| Resposta à pressão | 0,20 | Ela muda quando a pressão muda? | Fração das trocas de pressão em que andou no sentido esperado |
| Convergência | 0,20 | Ela acompanha o relógio? | Spearman parcial com HRV, FC de repouso, despertares e estresse, descontando pressão, horas de uso e mês |
| Independência de artefato | 0,15 | Ela é contaminada por vazamento ou início de sessão? | 1 − correlação com vazamento |
| Cobertura | 0,10 | Existe na maioria das noites? | Fração das noites com valor |
| Evidência | 0,10 | A literatura sustenta? | A = medida direta; B = definição publicada com viés conhecido; C = proxy ou índice proprietário |

Critério sem dado é ignorado e o peso dele é redistribuído. Alterar qualquer peso em 0,1 mantém o ranking com Spearman 0,87 contra o original.

## Glossário

- **ICC (coeficiente de correlação intraclasse):** quanto duas noites vizinhas, na mesma pressão, dão valores parecidos. 0 = acaso; 1 = idênticas. ICC baixo pode significar medida ruim **ou** noites que de fato variam.
- **Metades:** correlação entre as horas pares e ímpares da mesma noite, corrigida por Spearman-Brown. Separa o caso acima: se as metades concordam, a medida é estável e a variação entre noites é real (é o caso do `rin`).
- **Mudança mínima detectável:** menor diferença entre duas noites que não pode ser explicada pelo ruído da medida, com 95% de confiança.
- **Concordância de Lin:** como a correlação, mas também penaliza quando um índice fica sistematicamente acima do outro.
- **Bland-Altman:** diferença entre dois métodos contra a média deles; mostra o viés e se ele cresce com o nível.
- **q (Benjamini-Hochberg):** p ajustado para muitos testes ao mesmo tempo.

## Como comparar daqui para a frente

- **Uma mudança por vez.** Mudou a pressão, registre; limitação, `rin` e ronco reagem a ela e mascaram o efeito de um hábito.
- **Uso ≥ 4 h** para índice por hora. Noite curta entra como ponto isolado.
- **Sem DATALOG**, limitação e ronco ficam ausentes, não zero.
- **Hábito novo:** uma linha em `data/reference/daily_log.csv`, com a variável cadastrada em `config/habits_catalog.json`. Teste em blocos ABAB de 7 a 14 noites (`plan_n_of_1`), não numa noite só. Desfechos: limitação de fluxo, `rin` e ronco; horas de uso como dose; Garmin como confirmação.
- **Candidatos para o próximo bloco:** pressão entre 7,0 e 8,0 depois da cirurgia, e EPR (sinal fraco, nunca alternado de propósito) só quando a pressão estabilizar.

## Fontes

Notebooks `notebooks/07_indicator_reliability.ipynb` e `notebooks/08_factor_effects.ipynb`, executados em `data/reports/`, com 282 noites de uso ≥ 4 h (220 com fluxo bruto). Ranking completo em `data/reports/07_scorecard.csv`; pesos e a referência bibliográfica de cada indicador em `config/indicator_weights.json`.

## Consulta

```sql
with sig as (
  select night,
         60 * avg(case when flow_limitation > 0 then 1 else 0 end) as flow_lim_min_h,
         60 * avg(case when snore > 0 then 1 else 0 end) as snore_min_h
  from signals_2s group by night
)
select n.night, n.pressure, n.epr_level, n.humidity_level, n.usage_hours,
       n.ahi, n.oai, n.cai, n.rin,
       sig.flow_lim_min_h, sig.snore_min_h,
       m.hypopnea50_index, m.apnea75_index, m.apnea90_index
from nights n
left join sig using (night)
left join night_metrics m using (night)
where n.usage_hours > 0
order by n.night;
```
