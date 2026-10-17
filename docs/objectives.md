# Objetivos

Analisar minhas noites de sono com os dados do CPAP (ResMed AirSense 10 Elite, pressão fixa, com umidificador).

## Curto prazo — cirurgia de desvio de septo

Cirurgia realizada em **28/09/2026**. A pressão fixa passou de 7,0 para
6,0 cmH2O após a cirurgia.

A comparação exploratória está em `notebooks/05_pre_post_surgery.ipynb`.
De 28/09 a 27/10, as noites são classificadas como `recovery`
(pós-operatório inicial); o grupo `after` começa em **28/10/2026**.
A linha de base principal usa as últimas 60 noites pré com pelo menos 4 h
a 7,0 cmH2O. O controle usa as noites pré a 6,0 cmH2O, com as de 5,8
apresentadas separadamente como sensibilidade. O controle histórico inclui
usos parciais e não elimina diferenças de época, hábitos ou recuperação.

- Comparar o sono **antes** e **depois** da cirurgia.
- Medir o quanto o sono melhorou.
- Levantar evidências para discutir com o médico se é possível parar de usar o CPAP.

## Médio prazo — entender e comparar noites

- Entender como o sono se comporta em função de variáveis (ex.: hábitos, horário, ambiente, ajustes do aparelho).
- Comparar noites entre si e identificar quais foram melhores, e por quê.

## Limitações conhecidas dos dados

- **Os dados só existem com o CPAP ligado.** Eles mostram o sono *tratado* (apneias residuais, vazamento, ronco, limitação de fluxo), não quantas apneias eu teria sem o aparelho. A decisão de parar o CPAP depende de exame sem o aparelho (polissonografia ou teste domiciliar) e de avaliação médica; este projeto serve para dar contexto, não para essa decisão.
- **O aparelho é de pressão fixa.** Ele não ajusta a pressão sozinho, então a "pressão necessária" não muda nos dados depois da cirurgia. Para comparar noites, os sinais que se sustentam são a limitação de fluxo, o `rin` e o ronco; horas de uso são a dose. O AHI residual fica baixo demais para separar noites. O ranking e as ressalvas estão em `docs/quality-indicators.md`.
- **O cartão de memória tem corrupção.** 46 noites (01–12/06/2026 e 26/06–29/07/2026) estão ilegíveis. Os dados precisam ser copiados do cartão para o projeto com frequência.
- **A SpO2 do Garmin é de pulso.** Serve como tendência, não como oximetria do CPAP nem como exame. O AHI residual não acompanha a SpO2 mínima do relógio.
- **O detalhe por minuto do Garmin só existe por cerca de 6 meses.** Fases, FC, HRV e SpO2 amostra a amostra começam em 05/2026; dias anteriores continuam só com o resumo. `sleep-garmin-sync` precisa rodar pelo menos uma vez por mês, de preferência junto com a cópia do cartão.
