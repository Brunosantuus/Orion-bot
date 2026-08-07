# Integração com smartwatch (dados de saúde)

## Status

✅ Implementado: `treino_historico`/`saude_diaria` (Supabase + fallback local),
`registrar_treino_realizado`, `proximo_treino_sugerido`, override por texto
livre, comandos `/definir_agenda`, `/ver_agenda`, `/saude_fake`, `/saude_hoje`,
enriquecimento de `_contexto_saude()`/`/stats`/`/dicas`/resumo semanal, e o
esqueleto do dashboard web (`GET /dashboard` / `GET /api/resumo` em
`orion_servidor.py`).

⏳ Pendente: a ingestão real (Apple Health via Shortcuts/Health Auto Export →
`POST /saude`) e a Fase 2 (interface nativa no relógio) — ambas dependem do
relógio físico e não fazem parte do trabalho já feito.

Documento de referência para a próxima etapa do bot: usar dados reais de um
smartwatch (Huawei Watch Fit 5 Pro) para substituir a agenda de treino fixa e
enriquecer o que a IA sabe sobre o dia do usuário — em vez de exemplos/valores
fixos, o bot passa a reagir a sono, frequência cardíaca, passos, calorias e
treino detectado de verdade.

O relógio ainda não chegou. Além disso, como o celular é **iPhone**, a API de
nuvem "Huawei Health Kit" não se aplica — ela só funciona com Android/HMS. No
iPhone, o app Huawei Health escreve os dados direto no **Apple Health
(HealthKit)**, sem depender de nuvem Huawei (ver "Transporte futuro" abaixo).
Por isso a camada de dados abaixo é **agnóstica à fonte**: dá pra construir e
testar tudo isso hoje, com dados falsos, e trocar só um pedaço quando o
método de ingestão real (Apple Health via automação) for implementado.

## Novo domínio: `saude_diaria`

Segue o mesmo padrão já usado no bot para outros domínios (peso, água,
streaks): `carregar_X()` com Supabase + fallback em JSON local, e
`registrar_X()` para gravar. A diferença é que dados de saúde chegam aos
poucos ao longo do dia (passos sobem, sono só se sabe de manhã), então esse
domínio faz **upsert por data** — igual o `confirmar_habito` já faz upsert
por hábito.

**Arquivo local de fallback:** `saude_diaria.json`

**Tabela no Supabase** (criar manualmente no painel — não há migração
automática no repo):

| coluna              | tipo          | obs                    |
|---------------------|---------------|------------------------|
| `id`                | int8          | identity/PK            |
| `data`              | date          | **único**, chave natural |
| `passos`            | int4          | opcional               |
| `calorias`          | int4          | opcional               |
| `fc_repouso`        | int4          | opcional               |
| `fc_media`          | int4          | opcional               |
| `horas_sono`        | numeric       | opcional               |
| `treino_detectado`  | bool          | default false          |
| `treino_tipo`       | text          | opcional               |
| `treino_duracao_min`| int4          | opcional               |
| `fonte`             | text          | `"teste_manual"`, depois `"apple_health"` |

**Funções novas** (`bot_telegram.py`, logo após o bloco de peso/água):
- `carregar_saude_diaria()` — lê todos os registros (Supabase ou JSON local).
- `_saude_diaria_local_save(lst)` — grava o fallback local.
- `registrar_saude_diaria(data=None, fonte="manual", **campos)` — faz merge
  dos campos informados no registro do dia (sem apagar o que já tinha).
  **Esse é o único ponto de entrada de dados do relógio** — quando a
  integração real existir, o único código novo é quem chama essa função com
  `fonte="apple_health"`.
- `saude_hoje()` — retorna o registro de hoje ou `None`.

### Transporte futuro (referência, não implementar agora)

Como o celular é iPhone, a fonte real não é Huawei Health Kit nem
Gadgetbridge — é **Apple Health via automação**, sem precisar escrever app
nativo:
- **App "Health Auto Export"** (App Store) — exporta dados do Apple Health
  automaticamente (JSON) pra uma URL, num horário agendado.
- **Atalhos (Shortcuts)** — automação nativa do iPhone que lê saúde e faz
  `POST` numa URL num horário fixo.

O repo já tem um padrão pronto pra receber isso em `orion_servidor.py`: um
mini-servidor HTTP autenticado por token, rodando numa thread dentro do
próprio bot, que hoje recebe reports do celular via Tailscale (`POST
/report`). O caminho mais natural é um endpoint `POST /saude` nesse mesmo
servidor, que só chama `registrar_saude_diaria(fonte="apple_health", ...)`.

## Testar sem hardware

Dois comandos novos:
- `/saude_fake passos=8500 sono=7.2 fc_repouso=58 fc_media=95 treino=1 [data=AAAA-MM-DD]`
  — grava um dia (real ou passado, via `data=` opcional) para testes e para
  já ter uma janela de dias no resumo semanal.
- `/saude_hoje` — mostra o registro de hoje (debug/visibilidade).

## Pontos de integração

1. **`_contexto_saude()`** — passa a incluir sono, FC de repouso e passos de
   hoje (quando existirem), enriquecendo o contexto que alimenta a IA (Groq).
2. **Confirmação automática de treino** — nova função
   `verificar_treino_automatico()`, rodando como job agendado (~21h, depois
   do horário provável de sincronização do relógio): se `treino_detectado`
   estiver marcado no dia, confirma o hábito "academia" sozinho (usando
   `confirmar_habito`, que já é idempotente por dia — sem risco de duplicar).
   O botão manual "✅ Fui!" continua funcionando como alternativa nos dias
   sem dado do relógio.
3. **`enviar_resumo_semanal()`** — passa a incluir médias dos últimos 7 dias
   (passos, sono, FC de repouso) e quantidade de treinos detectados, junto
   com o resumo de tarefas que já existe hoje.
4. **`/stats` e `/dicas`** — passam a mostrar/considerar os dados de hoje
   (`saude_hoje()`), sem precisar de nenhuma abstração nova.
5. **Água** — fica de fora por enquanto. O relógio não mede hidratação
   direto, só atividade/calorias como proxy — não vale ajustar
   `calcular_meta_agua` sem dados reais pra calibrar. Revisitar depois de
   algumas semanas de uso real.

## Decisões assumidas

- Sono de "ontem à noite" é sempre gravado na `data` de hoje.
- `/saude_fake` e `/saude_hoje` não entram no `/ajuda` — são ferramentas de
  teste, não recursos para o usuário final.
- Tabela `saude_diaria` precisa ser criada manualmente no Supabase antes de
  ativar a integração (ou o bot roda só no fallback local em
  `saude_diaria.json`).

## Fase 2 (futuro): interface própria no relógio

Ideia para depois que a camada de dados acima estiver funcionando: em vez de
só *ler* dados do relógio, ter uma interface do próprio bot rodando nele —
mostrar streak, próxima tarefa/lembrete, ou confirmar o treino direto no
pulso, sem precisar abrir o Telegram no celular.

Isso é um projeto à parte, maior que a integração de dados:
- O Watch Fit 5 Pro roda **HarmonyOS 6.1.0**, que já suporta apps de
  terceiros (via AppGallery dentro do app Huawei Health).
- Desenvolvimento é feito no **DevEco Studio**, com UI em **ArkTS/ArkUI**
  (stack própria do HarmonyOS, diferente de Android/iOS).
- Para uso pessoal (sem publicar no AppGallery), dá pra fazer **sideload**
  direto do IDE pro relógio via Bluetooth/USB emparelhado.
- Comunicação bidirecional relógio ↔ celular usa o **Wear Engine SDK** —
  esse app do relógio conversaria com um app/serviço no celular, que por sua
  vez fala com o bot (mesmo papel que a Health Kit API ou o
  `orion_servidor.py` fariam do lado dos dados).

Não vale começar por aqui: faz mais sentido resolver a ingestão de dados
primeiro (fase 1 acima) e só então avaliar se o ganho de ter uma interface
nativa no relógio compensa aprender ArkTS/ArkUI e manter mais um app.

## Fase 0 (antes de tudo): treino deixa de ser fixo por calendário

Antes mesmo do relógio chegar, dá pra resolver um problema que já existe hoje:
`treino_hoje()` assume que o dia da semana dita o treino (`_AGENDA_FIXA`), mas
na prática o Bruno às vezes pula um dia ou treina um grupo diferente do
previsto ("hoje vou treinar perna"). O calendário fixo não reflete a
realidade — e é justamente essa realidade que vai alimentar tanto a IA
quanto a futura detecção automática do relógio.

Mudança de arquitetura:

1. **`treino_historico`** — tabela nova, append-only (mesmo padrão de
   `peso_historico`/`agua_log`): cada linha é `{data, dia_letra, fonte}`,
   onde `fonte` é `"manual"` (botão "✅ Fui!"), `"chat"` (texto livre) ou
   `"relogio"` (detecção automática, fase 1). Essa tabela vira a fonte de
   verdade sobre o que foi treinado — a agenda fixa deixa de ser autoridade.
2. **`proximo_treino_sugerido()`** — substitui a lógica de "olha o dia da
   semana" por "olha o que foi treinado por último no histórico e sugere o
   próximo da rotação A→B→C". Só cai para `_AGENDA_FIXA` como cold-start,
   quando ainda não existe histórico nenhum.
3. **Override por texto livre** — o handler de texto livre (que hoje cai
   direto no chat geral da IA) passa a reconhecer frases do tipo "hoje vou
   treinar perna/costas/peito" (mapeando grupo muscular → `dia_letra`, mesmo
   agrupamento que já existe em `_ICONE_GRUPO`), grava no `treino_historico`
   com `fonte="chat"` e responde com os exercícios daquele dia — sem
   precisar de um comando novo.
4. **Confirmação unificada** — botão manual, `/bebi`-style e a futura
   `verificar_treino_automatico()` (fase 1) passam todas a gravar no mesmo
   `treino_historico` ao confirmar o streak, pra streak e histórico nunca
   ficarem dessincronizados.
5. **Interface de edição via Telegram** — comandos novos (`/definir_agenda`,
   edição de `agenda_treino`/`treinos`) pra ajustar a divisão de treino
   direto pelo chat, sem precisar mexer no painel do Supabase nem no código.
   As tabelas `agenda_treino`/`treinos` já são checadas antes do fallback
   fixo (`carregar_agenda_treino`/`carregar_treino_dia`,
   bot_telegram.py:443-462) — só faltam os comandos de escrita.
6. **`_contexto_saude()`/`/dicas`** passam a citar o treino real recente
   ("treinou perna há 2 dias, ainda não fez peito essa semana") em vez de só
   repetir a agenda.

Essa mudança independe do relógio — pode (e deve) ser construída antes dele
chegar, e é o que dá à fase 1 (dados do relógio) algo de verdade pra
alimentar em vez de só substituir um número fixo por outro.

## Quando implementar

Esta camada de dados e os pontos de integração acima podem ser construídos
e testados **antes** do relógio chegar. O que falta decidir só depois do
relógio em mãos é *como os dados chegam* (Health Kit vs. Gadgetbridge) — e
isso fica isolado dentro de `registrar_saude_diaria`, sem afetar o resto.
