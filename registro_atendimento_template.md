# Template — Registro de Atendimento (Núcleo de Tecnologia Municipal)

Guia para a IA gerar o **Registro de Atendimento – Diário Digital** a partir de
anotações soltas do Bruno. Objetivo: Bruno manda os fatos crus (informais) e a IA
devolve o **texto formal pronto** + os campos preenchidos do formulário.

---

## 1. Como usar (fluxo)

1. Bruno descreve o atendimento em linguagem informal (ex.: *"atendi a escola Posse
   online, secretário Jorge e secretária Ana Beatriz, resolvi acesso a notas de uma
   professora, corrigi frequências erradas de uma turma, falta carga horária da ATA
   e ficha individual"*).
2. A IA extrai as variáveis (seção 3), redige o texto formal (seção 4) e devolve o
   documento no layout da seção 2.
3. Se o fluxo gerar arquivo: usar o script da seção 6 para produzir `.docx` + PDF.

---

## 2. Layout do documento (fixo)

```
            ESTADO DO RIO DE JANEIRO
            PREFEITURA MUNICIPAL DE RIO BONITO
            SECRETARIA MUNICIPAL DE EDUCAÇÃO
        NÚCLEO DE TECNOLOGIA MUNICIPAL – DIÁRIO DIGITAL

Unidade Escolar: {{unidade_escolar}}

REGISTRO DE ATENDIMENTO – PRESENCIAL ( {{x_presencial}} )   ON-LINE ( {{x_online}} )

{{descricao_formal}}

Assinaturas:
_______________________________________________________________________________
_______________________________________________________________________________
_______________________________________________________________________________

Rio Bonito {{dia}} / {{mes}} / {{ano}}
```

- O nome da unidade e o texto da descrição ficam **sublinhados** (visual "escrito sobre a linha").
- Marcar **apenas um** entre PRESENCIAL / ON-LINE com `X` (o outro fica vazio).

---

## 3. Variáveis de entrada (o que a IA precisa extrair)

| Campo | Descrição | Exemplo |
|---|---|---|
| `unidade_escolar` | Nome da escola atendida | Escola Municipal Maurício Kopke |
| `modalidade` | `PRESENCIAL` ou `ON-LINE` | ON-LINE |
| `pessoas` | Quem foi atendido (nome + cargo) | secretário escolar Jorge Machado Rangel; secretária escolar Ana Beatriz Nascimento Rodrigues |
| `acoes_resolvidas` | O que foi feito/resolvido no atendimento | acesso aos lançamentos de notas de uma professora (resolvido na hora); correção de frequências incorretas de uma turma |
| `pendencias` | O que ficou pendente | ajuste da carga horária na ATA; liberação do documento de ficha individual |
| `data` | Data do atendimento (padrão: hoje) | 22/06/2026 |

> Se algum campo faltar, a IA pergunta antes de gerar (não inventar nomes nem datas).

---

## 4. Diretrizes de redação (texto formal)

- **Terceira pessoa, voz impessoal**: "Foi realizado…", "Procedeu-se à…", "Realizou-se…".
- **Tom institucional e objetivo** — sem gírias, sem primeira pessoa ("eu fiz").
- **Não repetir o nome da escola** no início da descrição (já consta no campo Unidade).
- Citar **data por extiquo** ("em 22 de junho de 2026") e **nomes com cargo**.
- Separar claramente: (a) o que foi **verificado/resolvido**; (b) o que **permanece pendente**.
- Quando algo foi resolvido na hora, deixar **explícito**: "sendo a questão solucionada no
  decorrer do próprio atendimento".
- Tamanho: 1 parágrafo coeso (4–6 frases).

### Modelo de frase
> Foi realizado atendimento {modalidade}, em {data por extenso}, junto a(o) {pessoas},
> com o objetivo de verificar pendências no Diário Digital. {ações resolvidas, em ordem}.
> Permanece(m) pendente(s), tão somente, {pendências}.

---

## 5. Exemplo completo (referência de qualidade)

**Entrada informal:**
> escola maurício kopke, online, secretário jorge machado rangel e secretária ana beatriz
> nascimento rodrigues, resolvi o acesso a lançamento de notas de uma professora na hora,
> corrigi frequências erradas de uma turma, falta carga horária da ATA e ficha individual

**Saída esperada (descrição formal):**
> Foi realizado atendimento on-line, em 22 de junho de 2026, junto ao secretário escolar
> Jorge Machado Rangel e à secretária escolar Ana Beatriz Nascimento Rodrigues, com o
> objetivo de verificar pendências no Diário Digital. Procedeu-se à verificação do acesso
> aos lançamentos de notas de uma professora que relatava dificuldade no sistema, sendo a
> questão solucionada no decorrer do próprio atendimento. Realizou-se, ainda, a correção
> dos registros de frequência de uma turma, com a remoção dos lançamentos incorretos
> referentes aos alunos. Permanecem pendentes, tão somente, o ajuste da carga horária na
> ATA e a liberação do documento de ficha individual.

**Campos:** unidade = Escola Municipal Maurício Kopke · modalidade = ON-LINE (X) ·
data = 22/06/2026.

---

## 6. (Opcional) Gerar o arquivo .docx + PDF

O `bot_telegram.py` hoje não gera documento — só texto. Para automatizar o arquivo,
acrescentar `python-docx` (e, no Windows com Word, `docx2pdf`) e usar o template em
branco `registro de atendimento.docx`. Esqueleto:

```python
from docx import Document

def gerar_registro(template_path, out_docx, dados):
    d = Document(template_path)
    # [2] Unidade Escolar — nome sublinhado, mantendo as linhas
    p2 = d.paragraphs[2]; r0 = p2.runs[0]
    label = "Unidade Escolar: "; unders = r0.text[len(label):]
    nome = dados["unidade_escolar"]
    r0.text = label
    rn = p2.add_run(nome); rn.underline = True
    p2.add_run(unders[len(nome):] if len(unders) > len(nome) else unders)
    # [4] marca X em ON-LINE (run4) ou PRESENCIAL (run2)
    alvo = 4 if dados["modalidade"].upper() == "ON-LINE" else 2
    d.paragraphs[4].runs[alvo].text = "( X"
    # [6] descrição formal sublinhada, sem linhas em branco extras
    p6 = d.paragraphs[6]
    for r in list(p6.runs): r.text = ""
    p6.runs[0].text = dados["descricao_formal"]; p6.runs[0].underline = True
    # [12] data
    d.paragraphs[12].runs[0].text = f"Rio Bonito {dados['dia']} / {dados['mes']} / {dados['ano']}"
    for r in d.paragraphs[12].runs[1:]: r.text = ""
    d.save(out_docx)

# PDF (Windows + Word instalado):
# from docx2pdf import convert; convert(out_docx, out_docx.replace(".docx", ".pdf"))
```

> Índices dos parágrafos (`[2]`, `[4]`, `[6]`, `[12]`) valem para o template
> `registro de atendimento.docx` atual. Se o template mudar, reconferir com:
> `for i,p in enumerate(Document(path).paragraphs): print(i, repr(p.text[:50]))`

---

## 7. Prompt sugerido para a IA do bot

```
Você é o assistente do Bruno (Núcleo de Tecnologia Municipal de Rio Bonito).
A partir das anotações informais dele sobre um atendimento, gere o REGISTRO DE
ATENDIMENTO seguindo o template (campos + texto formal). Regras:
- Texto em 3ª pessoa, impessoal e institucional (1 parágrafo, 4–6 frases).
- Não repita o nome da escola no início da descrição.
- Deixe explícito o que foi resolvido na hora e o que permanece pendente.
- Use a data de hoje se ele não informar outra; nunca invente nomes/datas — pergunte.
- Responda com: (1) os campos preenchidos e (2) a descrição formal pronta.
```
