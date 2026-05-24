import json
import os
import re
import schedule
import threading
import time
import sys
import telebot
import requests
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")

_base = os.path.dirname(__file__)
CONFIG_FILE = (os.path.join(_base, "config.json")
               if os.path.exists(os.path.join(_base, "config.json"))
               else os.path.join(_base, "config.railway.json"))
TAREFAS_FILE = os.path.join(_base, "tarefas.json")
LEMBRETES_USUARIO_FILE = os.path.join(_base, "lembretes_usuario.json")
STREAKS_FILE = os.path.join(_base, "streaks.json")
NOTAS_FILE = os.path.join(_base, "notas.json")

config = {}
bot = None
historico_chat = {}
estados = {}
_snooze_pending = {}

_HABITO_POR_HORARIO = {"10:00": "agua", "15:00": "agua", "18:00": "academia"}


# ── Config ────────────────────────────────────────────────────────────────────

def carregar_config():
    global config
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    token_id = os.environ.get("TOKEN_ID")
    token_key = os.environ.get("TOKEN_KEY")
    if token_id and token_key:
        config["telegram"]["token"] = f"{token_id}:{token_key}"
    if os.environ.get("TELEGRAM_CHAT_ID"):
        config["telegram"]["chat_id"] = os.environ["TELEGRAM_CHAT_ID"]
    if os.environ.get("GROQ_API_KEY"):
        config["groq"]["api_key"] = os.environ["GROQ_API_KEY"]


def salvar_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ── Supabase ──────────────────────────────────────────────────────────────────

_SB_URL = os.environ.get("SUPABASE_URL", "")
_SB_KEY = os.environ.get("SUPABASE_KEY", "")
_USA_SB = bool(_SB_URL and _SB_KEY)


def _sb_req(method, table, filters=None, body=None):
    qs = "&".join(f"{k}={v}" for k, v in (filters or {}).items())
    url = f"{_SB_URL}/rest/v1/{table}{'?' + qs if qs else ''}"
    headers = {
        "apikey": _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    r = requests.request(method, url, headers=headers, json=body, timeout=10)
    try:
        return r.json() if r.content else []
    except Exception:
        return []


# ── Helpers de parsing ────────────────────────────────────────────────────────

def _parse_tarefa(texto):
    """Extrai prioridade (!urgente) e prazo (@DD/MM) do texto."""
    prioridade = "normal"
    prazo = None

    if texto.startswith("!") or re.search(r"\burgente\b", texto, re.IGNORECASE):
        prioridade = "alta"
        texto = re.sub(r"^!+\s*", "", texto)
        texto = re.sub(r"\burgente:?\s*", "", texto, flags=re.IGNORECASE).strip()

    match = re.search(r"@(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", texto)
    if match:
        try:
            dia = int(match.group(1))
            mes = int(match.group(2))
            ano = int(match.group(3)) if match.group(3) else date.today().year
            prazo = date(ano, mes, dia).isoformat()
        except ValueError:
            pass
        texto = re.sub(r"@\d{1,2}/\d{1,2}(?:/\d{4})?", "", texto).strip()

    return texto, prioridade, prazo


def _prazo_label(prazo_iso):
    """Retorna label legível do prazo com urgência."""
    if not prazo_iso:
        return ""
    try:
        prazo_dt = date.fromisoformat(prazo_iso)
        dias = (prazo_dt - date.today()).days
        if dias < 0:
            return " ⚠️ VENCIDA"
        if dias == 0:
            return " 🚨 HOJE"
        if dias == 1:
            return " ⏳ amanhã"
        return f" 📅 {prazo_dt.strftime('%d/%m')}"
    except Exception:
        return ""


# ── Tarefas ───────────────────────────────────────────────────────────────────

def carregar_tarefas():
    if _USA_SB:
        try:
            return _sb_req("GET", "tarefas", {"select": "*", "order": "id"}) or []
        except Exception:
            pass
    if os.path.exists(TAREFAS_FILE):
        with open(TAREFAS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _tarefas_local_save(lst):
    with open(TAREFAS_FILE, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=2)


def adicionar_tarefa(texto, prioridade="normal", prazo=None):
    nova = {
        "texto": texto,
        "concluida": False,
        "criada": date.today().isoformat(),
        "prioridade": prioridade,
        "prazo": prazo,
    }
    if _USA_SB:
        try:
            _sb_req("POST", "tarefas", body=nova)
            return
        except Exception:
            pass
    lst = carregar_tarefas()
    lst.append(nova)
    _tarefas_local_save(lst)


def concluir_tarefa(idx):
    lst = carregar_tarefas()
    t = lst[idx - 1]
    if _USA_SB:
        try:
            _sb_req("PATCH", "tarefas", {"id": f"eq.{t['id']}"}, {"concluida": True})
            return t
        except Exception:
            pass
    lst[idx - 1]["concluida"] = True
    _tarefas_local_save(lst)
    return t


def remover_tarefa(idx):
    lst = carregar_tarefas()
    t = lst[idx - 1]
    if _USA_SB:
        try:
            _sb_req("DELETE", "tarefas", {"id": f"eq.{t['id']}"})
            return t
        except Exception:
            pass
    lst.pop(idx - 1)
    _tarefas_local_save(lst)
    return t


def limpar_concluidas():
    lst = carregar_tarefas()
    concluidas = [t for t in lst if t.get("concluida")]
    if _USA_SB:
        try:
            for t in concluidas:
                _sb_req("DELETE", "tarefas", {"id": f"eq.{t['id']}"})
            return len(concluidas)
        except Exception:
            pass
    _tarefas_local_save([t for t in lst if not t.get("concluida")])
    return len(concluidas)


def formatar_tarefas(apenas_pendentes=False):
    tarefas = carregar_tarefas()
    if apenas_pendentes:
        tarefas = [t for t in tarefas if not t.get("concluida")]

    _ordem = {"alta": 0, "normal": 1, "baixa": 2}
    tarefas = sorted(
        tarefas,
        key=lambda t: (
            t.get("concluida", False),
            _ordem.get(t.get("prioridade", "normal"), 1),
            t.get("prazo") or "z",
        ),
    )

    if not tarefas:
        return "Nenhuma tarefa cadastrada."

    linhas = []
    for i, t in enumerate(tarefas, 1):
        if t.get("concluida"):
            icone = "✅"
        elif t.get("prioridade") == "alta":
            icone = "🔴"
        elif t.get("prioridade") == "baixa":
            icone = "🟢"
        else:
            icone = "⬜"
        prazo = _prazo_label(t.get("prazo")) if not t.get("concluida") else ""
        linhas.append(f"{i}. {icone} {t['texto']}{prazo}")
    return "\n".join(linhas)


# ── Notas rápidas ─────────────────────────────────────────────────────────────

def carregar_notas():
    if _USA_SB:
        try:
            return _sb_req("GET", "notas", {"select": "*", "order": "id"}) or []
        except Exception:
            pass
    if os.path.exists(NOTAS_FILE):
        with open(NOTAS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _notas_local_save(lst):
    with open(NOTAS_FILE, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=2)


def adicionar_nota(texto):
    nova = {"texto": texto, "criada": datetime.now(FUSO).strftime("%Y-%m-%d %H:%M")}
    if _USA_SB:
        try:
            _sb_req("POST", "notas", body=nova)
            return
        except Exception:
            pass
    lst = carregar_notas()
    lst.append(nova)
    _notas_local_save(lst)


def remover_nota(idx):
    lst = carregar_notas()
    n = lst[idx - 1]
    if _USA_SB:
        try:
            _sb_req("DELETE", "notas", {"id": f"eq.{n['id']}"})
            return n
        except Exception:
            pass
    lst.pop(idx - 1)
    _notas_local_save(lst)
    return n


# ── Lembretes do usuário ──────────────────────────────────────────────────────

def carregar_lembretes_usuario():
    if _USA_SB:
        try:
            return _sb_req("GET", "lembretes_usuario", {"select": "*", "order": "id"}) or []
        except Exception:
            pass
    if os.path.exists(LEMBRETES_USUARIO_FILE):
        with open(LEMBRETES_USUARIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _lembretes_local_save(lst):
    with open(LEMBRETES_USUARIO_FILE, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=2)


def adicionar_lembrete_usuario(lembrete):
    if _USA_SB:
        try:
            _sb_req("POST", "lembretes_usuario", body=lembrete)
            return
        except Exception:
            pass
    lst = carregar_lembretes_usuario()
    lst.append(lembrete)
    _lembretes_local_save(lst)


def remover_lembrete_usuario(idx):
    lst = carregar_lembretes_usuario()
    l = lst[idx - 1]
    if _USA_SB:
        try:
            _sb_req("DELETE", "lembretes_usuario", {"id": f"eq.{l['id']}"})
            return l
        except Exception:
            pass
    lst.pop(idx - 1)
    _lembretes_local_save(lst)
    return l


def _deletar_lembrete_especifico(l):
    if _USA_SB and l.get("id"):
        try:
            _sb_req("DELETE", "lembretes_usuario", {"id": f"eq.{l['id']}"})
            return
        except Exception:
            pass
    lst = carregar_lembretes_usuario()
    lst = [x for x in lst if not (
        x["tipo"] == "especifico"
        and x.get("datetime") == l.get("datetime")
        and x.get("texto") == l.get("texto")
    )]
    _lembretes_local_save(lst)


# ── Streaks ───────────────────────────────────────────────────────────────────

def carregar_streaks():
    if _USA_SB:
        try:
            dados = _sb_req("GET", "streaks", {"select": "*"})
            return {s["habito"]: s for s in (dados or [])}
        except Exception:
            pass
    if os.path.exists(STREAKS_FILE):
        with open(STREAKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _streaks_local_save(streaks):
    with open(STREAKS_FILE, "w", encoding="utf-8") as f:
        json.dump(streaks, f, ensure_ascii=False, indent=2)


def confirmar_habito(habito):
    hoje = date.today().isoformat()
    ontem = (date.today() - timedelta(days=1)).isoformat()
    streaks = carregar_streaks()
    s = streaks.get(habito, {"ultima_data": None, "sequencia": 0})

    if s.get("ultima_data") == hoje:
        return s["sequencia"], None

    nova_seq = s["sequencia"] + 1 if s.get("ultima_data") == ontem else 1
    dados = {"habito": habito, "ultima_data": hoje, "sequencia": nova_seq}

    if _USA_SB:
        try:
            existente = _sb_req("GET", "streaks", {"habito": f"eq.{habito}", "select": "id"})
            if existente:
                _sb_req("PATCH", "streaks", {"habito": f"eq.{habito}"}, dados)
            else:
                _sb_req("POST", "streaks", body=dados)
        except Exception:
            pass
    else:
        streaks[habito] = dados
        _streaks_local_save(streaks)

    if nova_seq >= 30:
        msg = f"🏆 {nova_seq} dias seguidos! Você é uma lenda!"
    elif nova_seq >= 7:
        msg = f"🔥🔥 {nova_seq} dias seguidos! Incrível!"
    elif nova_seq > 1:
        msg = f"🔥 {nova_seq} dias seguidos!"
    else:
        msg = "Ótimo começo! 💪 Vamos manter!"

    return nova_seq, msg


# ── IA via Groq ───────────────────────────────────────────────────────────────

def _chamar_groq(mensagens, max_tokens=512):
    api_key = config.get("groq", {}).get("api_key", "")
    modelo = config.get("groq", {}).get("modelo", "llama-3.3-70b-versatile")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": modelo, "messages": mensagens, "max_tokens": max_tokens},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def perguntar_ia(chat_id, mensagem_usuario):
    api_key = config.get("groq", {}).get("api_key", "")
    if not api_key or "SUA_KEY" in api_key:
        return "⚠️ Configure a chave do Groq no config.json"

    if chat_id not in historico_chat:
        historico_chat[chat_id] = []

    agora = datetime.now(FUSO).strftime("%Y-%m-%d %H:%M")
    system_prompt = (
        "Você é o Orion, assistente pessoal criado pelo Bruno para ajudá-lo no dia a dia. "
        "Sua função principal é: lembrar tarefas, organizar a rotina, monitorar saúde (água, academia) e trabalho. "
        "Você foi criado especificamente pelo Bruno e existe para ser útil a ele — isso define quem você é.\n\n"
        "Estilo: descontraído e direto como um amigo próximo, sem formalidades, mas SEMPRE focado em ajudar. "
        "Quando o Bruno pedir algo, execute primeiro e converse depois. "
        "Respostas curtas e objetivas — máximo 2 linhas, sem enrolação.\n\n"
        f"Data/hora atual: {agora}\n"
        f"Tarefas do Bruno:\n{formatar_tarefas()}\n\n"
        "REGRA OBRIGATÓRIA: sempre que o Bruno pedir pra lembrar, notificar ou agendar QUALQUER coisa, "
        "você DEVE colocar exatamente esta linha no início da resposta (sem espaços extras):\n"
        "[LEMBRETE:YYYY-MM-DD HH:MM:descrição]\n"
        "Use a data/hora atual para calcular horários relativos. "
        "Exemplos: 'daqui 1 minuto' → soma 1 min na hora atual. 'amanhã às 9h' → data de amanhã 09:00. "
        "NUNCA omita essa linha quando houver pedido de lembrete. Depois confirme de forma animada."
    )

    historico_chat[chat_id].append({"role": "user", "content": mensagem_usuario})
    mensagens = historico_chat[chat_id][-12:]

    try:
        resposta = _chamar_groq([{"role": "system", "content": system_prompt}] + mensagens)
        historico_chat[chat_id].append({"role": "assistant", "content": resposta})
        return resposta
    except requests.exceptions.Timeout:
        return "⏳ A IA demorou demais. Tente novamente."
    except Exception as e:
        return f"⚠️ Erro ao consultar IA: {str(e)}"


# ── Alertas e automações ──────────────────────────────────────────────────────

def verificar_prazos():
    """Envia alerta de tarefas vencendo em até 2 dias. Chamado às 08:05."""
    chat_id = config["telegram"].get("chat_id", "")
    if not chat_id:
        return

    hoje = date.today()
    alertas = []
    for t in carregar_tarefas():
        if t.get("concluida") or not t.get("prazo"):
            continue
        try:
            prazo_dt = date.fromisoformat(t["prazo"])
            dias = (prazo_dt - hoje).days
            if dias < 0:
                alertas.append(f"⚠️ *VENCIDA:* {t['texto']} (venceu {prazo_dt.strftime('%d/%m')})")
            elif dias == 0:
                alertas.append(f"🚨 *HOJE:* {t['texto']}")
            elif dias == 1:
                alertas.append(f"⏳ *Amanhã:* {t['texto']}")
            elif dias == 2:
                alertas.append(f"📅 *Em 2 dias:* {t['texto']}")
        except Exception:
            continue

    if alertas:
        try:
            bot.send_message(chat_id, "🔔 *Atenção aos prazos:*\n\n" + "\n".join(alertas), parse_mode="Markdown")
        except Exception as e:
            print(f"Erro alerta prazos: {e}")


def enviar_resumo_semanal():
    """Resumo gerado pela IA toda sexta às 17h."""
    if datetime.now(FUSO).weekday() != 4:  # 4 = sexta-feira
        return

    chat_id = config["telegram"].get("chat_id", "")
    if not chat_id:
        return

    tarefas = carregar_tarefas()
    concluidas = [t for t in tarefas if t.get("concluida")]
    pendentes = [t for t in tarefas if not t.get("concluida")]

    try:
        nomes_c = ", ".join(t["texto"] for t in concluidas[:5]) or "nenhuma"
        nomes_p = ", ".join(t["texto"] for t in pendentes[:5]) or "nenhuma"
        prompt = (
            f"Você é o Orion. É sexta-feira, hora do resumo semanal do Bruno. "
            f"Concluídas: {len(concluidas)} ({nomes_c}). "
            f"Pendentes: {len(pendentes)} ({nomes_p}). "
            f"Gere um resumo animado em até 5 linhas: reconheça as conquistas, "
            f"destaque o que ficou pendente e motive para a próxima semana."
        )
        mensagem = _chamar_groq([{"role": "user", "content": prompt}], max_tokens=250)
    except Exception:
        mensagem = (
            f"📊 *Resumo da semana:*\n"
            f"✅ {len(concluidas)} tarefa(s) concluída(s)\n"
            f"⬜ {len(pendentes)} pendente(s)\n\n"
            "Bom fim de semana! 🎉"
        )

    try:
        bot.send_message(chat_id, mensagem, parse_mode="Markdown")
    except Exception as e:
        print(f"Erro resumo semanal: {e}")


# ── Lembretes agendados ───────────────────────────────────────────────────────

def enviar_lembrete(mensagem, habito=None):
    chat_id = config["telegram"].get("chat_id", "")
    if not chat_id:
        return
    try:
        botoes = []
        if habito == "academia":
            botoes.append(telebot.types.InlineKeyboardButton("✅ Fui!", callback_data="habito_academia"))
        elif habito == "agua":
            botoes.append(telebot.types.InlineKeyboardButton("💧 Bebi!", callback_data="habito_agua"))

        if len(_snooze_pending) > 50:
            for k in sorted(_snooze_pending.keys())[:25]:
                del _snooze_pending[k]

        snooze_id = str(int(time.time() * 1000))
        _snooze_pending[snooze_id] = mensagem
        botoes.append(telebot.types.InlineKeyboardButton("⏰ +15 min", callback_data=f"snooze_{snooze_id}"))

        markup = telebot.types.InlineKeyboardMarkup()
        markup.row(*botoes)
        bot.send_message(chat_id, mensagem, reply_markup=markup)
        print(f"[{datetime.now(FUSO).strftime('%H:%M')}] Lembrete enviado")
    except Exception as e:
        print(f"[{datetime.now(FUSO).strftime('%H:%M')}] Erro ao enviar lembrete: {e}")


def enviar_agenda_manha():
    """Bom dia personalizado com agenda do dia gerado pela IA."""
    chat_id = config["telegram"].get("chat_id", "")
    if not chat_id:
        return

    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    tarefas = formatar_tarefas(apenas_pendentes=True)
    lembretes_hoje = [
        l for l in carregar_lembretes_usuario()
        if l["tipo"] == "especifico" and l.get("datetime", "").startswith(hoje)
    ]
    lista_lem = ", ".join(l["texto"] for l in lembretes_hoje) if lembretes_hoje else "nenhum"

    try:
        prompt = (
            f"Você é o Orion, assistente do Bruno. É manhã de {hoje}. "
            f"Mande um bom dia animado e mostre a agenda do dia em até 4 linhas. "
            f"Tarefas pendentes: {tarefas}. Lembretes de hoje: {lista_lem}. "
            f"Destaque tarefas urgentes (🔴) se houver. Não use [LEMBRETE:...]. Seja direto e motivador."
        )
        mensagem = _chamar_groq([{"role": "user", "content": prompt}], max_tokens=200)
    except Exception:
        mensagem = config.get("lembretes", [{}])[0].get(
            "mensagem", "Bom dia! ☀️\n💧 Beba água\n📋 Use /tarefas para ver o dia"
        )

    try:
        bot.send_message(chat_id, mensagem)
        print(f"[{datetime.now(FUSO).strftime('%H:%M')}] Agenda matinal enviada")
    except Exception as e:
        print(f"Erro agenda matinal: {e}")


def verificar_lembretes_especificos():
    agora = datetime.now(FUSO)
    lembretes = carregar_lembretes_usuario()
    para_disparar = [
        l for l in lembretes
        if l["tipo"] == "especifico" and (
            lambda dt: (dt.year, dt.month, dt.day, dt.hour, dt.minute) ==
                       (agora.year, agora.month, agora.day, agora.hour, agora.minute)
        )(datetime.strptime(l["datetime"], "%Y-%m-%d %H:%M"))
    ]
    for l in para_disparar:
        enviar_lembrete(f"⏰ {l['texto']}")
        _deletar_lembrete_especifico(l)


def configurar_agenda():
    schedule.clear()

    schedule.every().day.at("07:00").do(enviar_agenda_manha)
    schedule.every().day.at("08:05").do(verificar_prazos)
    schedule.every().day.at("17:00").do(enviar_resumo_semanal)

    for lembrete in config.get("lembretes", []):
        if lembrete["horario"] in ("07:00",):
            continue
        habito = _HABITO_POR_HORARIO.get(lembrete["horario"])
        schedule.every().day.at(lembrete["horario"]).do(
            enviar_lembrete, mensagem=lembrete["mensagem"], habito=habito
        )

    for l in carregar_lembretes_usuario():
        if l["tipo"] == "diario":
            schedule.every().day.at(l["hora"]).do(enviar_lembrete, mensagem=f"⏰ {l['texto']}")

    schedule.every().minute.do(verificar_lembretes_especificos)
    print(f"  {len(config.get('lembretes', []))} lembretes fixos agendados.")


def thread_agenda():
    while True:
        schedule.run_pending()
        time.sleep(30)


# ── Handlers ──────────────────────────────────────────────────────────────────

def registrar_handlers():

    @bot.message_handler(commands=["start", "ajuda"])
    def cmd_start(msg):
        chat_id_str = str(msg.chat.id)
        if not config["telegram"].get("chat_id"):
            config["telegram"]["chat_id"] = chat_id_str
            salvar_config()
            extra = "✅ *Seu chat foi vinculado! Você receberá os lembretes aqui.*\n\n"
        else:
            extra = ""
        bot.reply_to(msg, (
            f"{extra}"
            "🌟 *Orion — Assistente Pessoal*\n\n"
            "📋 *Tarefas:*\n"
            "/adicionar [texto] [@DD/MM] — adicionar (use ! para urgente)\n"
            "/urgente [texto] — adicionar tarefa urgente\n"
            "/tarefas — ver tarefas (ordenadas por prioridade)\n"
            "/concluir [n] — marcar como feita\n"
            "/remover [n] — remover\n"
            "/historico — ver tarefas concluídas\n\n"
            "📝 *Notas rápidas:*\n"
            "/nota [texto] — salvar nota\n"
            "/notas — ver todas as notas\n"
            "/deletar\\_nota [n] — remover nota\n\n"
            "⏰ *Lembretes:*\n"
            "/lembrar [texto] — criar lembrete\n"
            "/meus\\_lembretes — ver lembretes criados\n"
            "/cancelar\\_lembrete [n] — remover lembrete\n\n"
            "🏆 *Hábitos:*\n"
            "/streaks — ver sequência de hábitos\n\n"
            "💬 *Ou mande uma mensagem — o Orion responde!*\n"
            "_Ex: 'me lembra da reunião amanhã às 14h'_"
        ), parse_mode="Markdown")

    # ── Tarefas ──

    @bot.message_handler(commands=["tarefas"])
    def cmd_tarefas(msg):
        bot.reply_to(msg, f"📋 *Suas tarefas:*\n\n{formatar_tarefas()}", parse_mode="Markdown")

    @bot.message_handler(commands=["adicionar"])
    def cmd_adicionar(msg):
        texto_raw = msg.text.replace("/adicionar", "").strip()
        if not texto_raw:
            bot.reply_to(msg,
                         "⚠️ Uso: `/adicionar texto [@DD/MM]`\n"
                         "Use `!` no início para urgente.\n"
                         "Ex: `/adicionar ! Relatório @30/06`",
                         parse_mode="Markdown")
            return
        texto, prioridade, prazo = _parse_tarefa(texto_raw)
        adicionar_tarefa(texto, prioridade, prazo)
        prazo_str = f"\n📅 Prazo: {date.fromisoformat(prazo).strftime('%d/%m/%Y')}" if prazo else ""
        prioridade_str = " 🔴 *URGENTE*" if prioridade == "alta" else ""
        bot.reply_to(msg, f"✅ Tarefa adicionada:{prioridade_str}\n*{texto}*{prazo_str}", parse_mode="Markdown")

    @bot.message_handler(commands=["urgente"])
    def cmd_urgente(msg):
        texto_raw = msg.text.replace("/urgente", "").strip()
        if not texto_raw:
            bot.reply_to(msg, "⚠️ Uso: `/urgente Descrição da tarefa`", parse_mode="Markdown")
            return
        texto, _, prazo = _parse_tarefa(texto_raw)
        adicionar_tarefa(texto, prioridade="alta", prazo=prazo)
        prazo_str = f"\n📅 Prazo: {date.fromisoformat(prazo).strftime('%d/%m/%Y')}" if prazo else ""
        bot.reply_to(msg, f"🔴 *Tarefa urgente adicionada:*\n{texto}{prazo_str}", parse_mode="Markdown")

    @bot.message_handler(commands=["concluir"])
    def cmd_concluir(msg):
        try:
            n = int(msg.text.replace("/concluir", "").strip())
            t = concluir_tarefa(n)
            bot.reply_to(msg, f"✅ Tarefa {n} concluída: *{t['texto']}*", parse_mode="Markdown")
        except (ValueError, IndexError):
            bot.reply_to(msg, "⚠️ Uso: `/concluir 1` (número da tarefa)", parse_mode="Markdown")

    @bot.message_handler(commands=["remover"])
    def cmd_remover(msg):
        try:
            n = int(msg.text.replace("/remover", "").strip())
            t = remover_tarefa(n)
            bot.reply_to(msg, f"🗑️ Tarefa removida: *{t['texto']}*", parse_mode="Markdown")
        except (ValueError, IndexError):
            bot.reply_to(msg, "⚠️ Uso: `/remover 1` (número da tarefa)", parse_mode="Markdown")

    @bot.message_handler(commands=["limpar"])
    def cmd_limpar(msg):
        n = limpar_concluidas()
        bot.reply_to(msg, f"🧹 {n} tarefa(s) concluída(s) removida(s).")

    @bot.message_handler(commands=["historico"])
    def cmd_historico(msg):
        concluidas = [t for t in carregar_tarefas() if t.get("concluida")]
        if not concluidas:
            bot.reply_to(msg, "Nenhuma tarefa concluída ainda. Bora trabalhar! 💪")
            return
        linhas = [f"{i}. ✅ {t['texto']}" for i, t in enumerate(concluidas, 1)]
        bot.reply_to(msg, "✅ *Tarefas concluídas:*\n\n" + "\n".join(linhas), parse_mode="Markdown")

    # ── Notas ──

    @bot.message_handler(commands=["nota"])
    def cmd_nota(msg):
        texto = msg.text.replace("/nota", "").strip()
        if not texto:
            bot.reply_to(msg, "⚠️ Uso: `/nota Texto da nota`\nEx: `/nota Protocolo 2024/001 - aguardando sec`", parse_mode="Markdown")
            return
        adicionar_nota(texto)
        bot.reply_to(msg, f"📝 Nota salva:\n_{texto}_", parse_mode="Markdown")

    @bot.message_handler(commands=["notas"])
    def cmd_notas(msg):
        notas = carregar_notas()
        if not notas:
            bot.reply_to(msg, "Nenhuma nota salva.\nUse `/nota texto` para adicionar.", parse_mode="Markdown")
            return
        linhas = [f"{i}. 📝 {n['texto']}" for i, n in enumerate(notas, 1)]
        bot.reply_to(msg, "📝 *Suas notas:*\n\n" + "\n".join(linhas) +
                     "\n\nUse `/deletar_nota [número]` para remover.", parse_mode="Markdown")

    @bot.message_handler(commands=["deletar_nota"])
    def cmd_deletar_nota(msg):
        try:
            n = int(msg.text.replace("/deletar_nota", "").strip())
            nota = remover_nota(n)
            bot.reply_to(msg, f"🗑️ Nota removida: _{nota['texto']}_", parse_mode="Markdown")
        except (ValueError, IndexError):
            bot.reply_to(msg, "⚠️ Uso: `/deletar_nota 1` (número da nota)", parse_mode="Markdown")

    # ── Streaks ──

    @bot.message_handler(commands=["streaks"])
    def cmd_streaks(msg):
        streaks = carregar_streaks()
        if not streaks:
            bot.reply_to(msg, (
                "Nenhum hábito registrado ainda.\n"
                "Quando o Orion mandar um lembrete de água ou academia, "
                "clique no botão para confirmar e a sequência começa! 💪"
            ))
            return
        nomes = {"academia": "🏋️ Academia", "agua": "💧 Hidratação"}
        linhas = []
        for habito, s in streaks.items():
            nome = nomes.get(habito, habito)
            seq = s.get("sequencia", 0)
            emoji = "🔥" if seq >= 3 else ("✅" if seq > 0 else "⬜")
            linhas.append(f"{emoji} {nome}: *{seq} dia(s) seguido(s)*")
        bot.reply_to(msg, "🏆 *Seus hábitos:*\n\n" + "\n".join(linhas), parse_mode="Markdown")

    # ── Lembretes ──

    @bot.message_handler(commands=["lembrar"])
    def cmd_lembrar(msg):
        texto = msg.text.replace("/lembrar", "").strip()
        if not texto:
            bot.reply_to(msg, "⚠️ Uso: `/lembrar Descrição do lembrete`", parse_mode="Markdown")
            return
        estados[msg.chat.id] = {"texto": texto, "step": "tipo"}
        markup = telebot.types.InlineKeyboardMarkup()
        markup.row(
            telebot.types.InlineKeyboardButton("📅 Data específica", callback_data="lembrar_especifico"),
            telebot.types.InlineKeyboardButton("🔁 Todo dia", callback_data="lembrar_diario"),
        )
        bot.reply_to(msg, f'📝 *"{texto}"*\n\nEste lembrete é:', reply_markup=markup, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data in ("lembrar_especifico", "lembrar_diario"))
    def callback_tipo_lembrete(call):
        chat_id = call.message.chat.id
        if chat_id not in estados:
            bot.answer_callback_query(call.id, "Sessão expirada. Use /lembrar novamente.")
            return
        if call.data == "lembrar_especifico":
            estados[chat_id]["tipo"] = "especifico"
            estados[chat_id]["step"] = "data"
            bot.edit_message_text(
                f'📝 *"{estados[chat_id]["texto"]}"*\n\n📅 Qual data e hora?\n'
                'Formato: `DD/MM HH:MM`\nExemplo: `25/06 14:30` ou `hoje 15:00`',
                chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown"
            )
        else:
            estados[chat_id]["tipo"] = "diario"
            estados[chat_id]["step"] = "hora"
            bot.edit_message_text(
                f'📝 *"{estados[chat_id]["texto"]}"*\n\n⏰ Que horas todo dia?\n'
                'Formato: `HH:MM`\nExemplo: `08:30`',
                chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown"
            )
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("snooze_"))
    def callback_snooze(call):
        snooze_id = call.data[len("snooze_"):]
        mensagem = _snooze_pending.pop(snooze_id, None)
        if not mensagem:
            bot.answer_callback_query(call.id, "⚠️ Lembrete expirado.")
            return
        dt_snooze = datetime.now(FUSO) + timedelta(minutes=15)
        texto = re.sub(r"^⏰\s*", "", mensagem).strip()
        adicionar_lembrete_usuario({
            "tipo": "especifico",
            "texto": texto,
            "datetime": dt_snooze.strftime("%Y-%m-%d %H:%M"),
        })
        bot.answer_callback_query(call.id, "⏰ Adiado 15 min!")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(call.message.chat.id,
                         f"⏰ Ok! Vou te lembrar às *{dt_snooze.strftime('%H:%M')}*.",
                         parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("habito_"))
    def callback_habito(call):
        habito = call.data[len("habito_"):]
        seq, msg_streak = confirmar_habito(habito)
        if msg_streak is None:
            bot.answer_callback_query(call.id, "Já confirmado hoje! 👍")
            return
        nomes = {"academia": "Academia", "agua": "Hidratação"}
        bot.answer_callback_query(call.id, msg_streak)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(call.message.chat.id,
                         f"✅ *{nomes.get(habito, habito)}* confirmada!\n{msg_streak}",
                         parse_mode="Markdown")

    @bot.message_handler(commands=["meus_lembretes"])
    def cmd_meus_lembretes(msg):
        lembretes = carregar_lembretes_usuario()
        if not lembretes:
            bot.reply_to(msg, "Nenhum lembrete personalizado.\nUse /lembrar para adicionar!")
            return
        linhas = []
        for i, l in enumerate(lembretes, 1):
            if l["tipo"] == "especifico":
                dt = datetime.strptime(l["datetime"], "%Y-%m-%d %H:%M")
                linhas.append(f"{i}. 📅 {dt.strftime('%d/%m às %H:%M')} — {l['texto']}")
            else:
                linhas.append(f"{i}. 🔁 Todo dia às {l['hora']} — {l['texto']}")
        bot.reply_to(msg, "📋 *Seus lembretes:*\n\n" + "\n".join(linhas) +
                     "\n\nUse `/cancelar_lembrete [número]` para remover.", parse_mode="Markdown")

    @bot.message_handler(commands=["cancelar_lembrete"])
    def cmd_cancelar_lembrete(msg):
        try:
            n = int(msg.text.replace("/cancelar_lembrete", "").strip())
            l = remover_lembrete_usuario(n)
            configurar_agenda()
            bot.reply_to(msg, f"🗑️ Lembrete removido: *{l['texto']}*", parse_mode="Markdown")
        except (ValueError, IndexError):
            bot.reply_to(msg, "⚠️ Uso: `/cancelar_lembrete 1`", parse_mode="Markdown")

    @bot.message_handler(commands=["lembretes"])
    def cmd_lembretes(msg):
        lembretes = config.get("lembretes", [])
        if not lembretes:
            bot.reply_to(msg, "Nenhum lembrete fixo configurado.")
            return
        linhas = [f"⏰ `{l['horario']}` — {l['mensagem'].splitlines()[0]}" for l in lembretes]
        bot.reply_to(msg, "📅 *Lembretes fixos:*\n\n" + "\n".join(linhas), parse_mode="Markdown")

    # ── Chat livre ──

    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def handle_texto(msg):
        chat_id = msg.chat.id
        estado = estados.get(chat_id, {})

        if estado.get("step") == "data":
            try:
                partes = msg.text.strip().split(" ")
                hora_str = partes[-1]
                dia_mes = partes[0].lower()
                if dia_mes == "hoje":
                    d = date.today()
                else:
                    dia, mes = dia_mes.split("/")
                    d = date(date.today().year, int(mes), int(dia))
                hora, minuto = hora_str.split(":")
                dt = datetime(d.year, d.month, d.day, int(hora), int(minuto))
                adicionar_lembrete_usuario({
                    "tipo": "especifico",
                    "texto": estado["texto"],
                    "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                })
                del estados[chat_id]
                bot.reply_to(msg,
                             f"✅ Lembrete agendado!\n📅 *{dt.strftime('%d/%m/%Y às %H:%M')}*\n📝 {estado['texto']}",
                             parse_mode="Markdown")
            except Exception:
                bot.reply_to(msg,
                             "⚠️ Formato inválido. Use: `DD/MM HH:MM` ou `hoje HH:MM`",
                             parse_mode="Markdown")

        elif estado.get("step") == "hora":
            try:
                hora_str = msg.text.strip()
                h, m = hora_str.split(":")
                int(h); int(m)
                adicionar_lembrete_usuario({"tipo": "diario", "texto": estado["texto"], "hora": hora_str})
                configurar_agenda()
                del estados[chat_id]
                bot.reply_to(msg,
                             f"✅ Lembrete diário criado!\n🔁 *Todo dia às {hora_str}*\n📝 {estado['texto']}",
                             parse_mode="Markdown")
            except Exception:
                bot.reply_to(msg, "⚠️ Formato inválido. Use: `HH:MM`", parse_mode="Markdown")

        else:
            bot.send_chat_action(chat_id, "typing")
            resposta = perguntar_ia(chat_id, msg.text)

            match = re.search(r'\[LEMBRETE\s*:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*:\s*(.+?)\]', resposta)
            if match:
                try:
                    dt = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M")
                    texto_lembrete = match.group(3).strip()
                    adicionar_lembrete_usuario({
                        "tipo": "especifico",
                        "texto": texto_lembrete,
                        "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                    })
                    resposta = re.sub(r'\[LEMBRETE[^\]]+\]', '', resposta).strip()
                except Exception:
                    pass

            bot.reply_to(msg, resposta)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global bot

    print("=" * 54)
    print("   🌟 ORION — Assistente Pessoal (Telegram)")
    print("=" * 54)

    carregar_config()

    token = config["telegram"].get("token", "")
    if "SEU_TOKEN" in token or not token:
        print("\n❌ TELEGRAM_TOKEN não configurado!")
        sys.exit(1)

    api_key = config.get("groq", {}).get("api_key", "")
    if not api_key or "SUA_KEY" in api_key:
        print("\n⚠️  GROQ_API_KEY não configurada.")

    if _USA_SB:
        print("\n✅ Persistência: Supabase")
    else:
        print("\n⚠️  Persistência: arquivos locais (dados perdidos ao reiniciar)")

    bot = telebot.TeleBot(token)
    registrar_handlers()
    configurar_agenda()

    agendador = threading.Thread(target=thread_agenda, daemon=True)
    agendador.start()

    chat_id = config["telegram"].get("chat_id", "")
    if not chat_id:
        print("\n⚠️  Envie /start ao bot para vincular seu chat.")
    else:
        print(f"\n✅ Chat vinculado: {chat_id}")

    print("\n✅ Orion rodando!\n")

    bot.infinity_polling(timeout=30, long_polling_timeout=20)


if __name__ == "__main__":
    main()
