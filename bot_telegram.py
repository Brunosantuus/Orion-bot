import json
import os
import schedule
import threading
import time
import sys
import telebot
import requests
from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")

_base = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(_base, "config.json") if os.path.exists(os.path.join(_base, "config.json")) else os.path.join(_base, "config.railway.json")
TAREFAS_FILE = os.path.join(_base, "tarefas.json")
LEMBRETES_USUARIO_FILE = os.path.join(_base, "lembretes_usuario.json")

config = {}
bot = None
historico_chat = {}
estados = {}  # chat_id -> estado da conversa ao criar lembrete


# ── Config ──────────────────────────────────────────────────────────────────

def carregar_config():
    global config
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    # Variáveis de ambiente têm prioridade (usado no Railway)
    # Token dividido em 2 partes para contornar limitação do Railway com ":"
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


# ── Tarefas ──────────────────────────────────────────────────────────────────

def carregar_tarefas():
    if os.path.exists(TAREFAS_FILE):
        with open(TAREFAS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def salvar_tarefas(tarefas):
    with open(TAREFAS_FILE, "w", encoding="utf-8") as f:
        json.dump(tarefas, f, ensure_ascii=False, indent=2)


def formatar_tarefas():
    tarefas = carregar_tarefas()
    if not tarefas:
        return "Nenhuma tarefa cadastrada."
    linhas = []
    for i, t in enumerate(tarefas, 1):
        icone = "✅" if t.get("concluida") else "⬜"
        linhas.append(f"{i}. {icone} {t['texto']}")
    return "\n".join(linhas)


# ── IA via Groq ───────────────────────────────────────────────────────────────

def perguntar_ia(chat_id, mensagem_usuario):
    api_key = config.get("groq", {}).get("api_key", "")
    if not api_key or "SUA_KEY" in api_key:
        return "⚠️ Configure a chave do Groq no config.json"

    if chat_id not in historico_chat:
        historico_chat[chat_id] = []

    agora = datetime.now(FUSO).strftime("%Y-%m-%d %H:%M")
    system_prompt = (
        "Você é o Orion, assistente pessoal parceiro do Bruno. "
        "Fale SEMPRE em português brasileiro informal e descontraído — como um amigo próximo, "
        "use gírias leves, seja bem-humorado e direto. Nada de formalidades. "
        "Você ajuda com tarefas, saúde (água, academia) e trabalho, mas de forma leve e animada. "
        "Respostas curtas e na vibe — máximo 2 parágrafos, sem enrolação.\n\n"
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

    modelo = config.get("groq", {}).get("modelo", "llama3-8b-8192")

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": modelo,
                "messages": [{"role": "system", "content": system_prompt}] + mensagens,
                "max_tokens": 512,
            },
            timeout=30,
        )
        resp.raise_for_status()
        resposta = resp.json()["choices"][0]["message"]["content"]
        historico_chat[chat_id].append({"role": "assistant", "content": resposta})
        return resposta
    except requests.exceptions.Timeout:
        return "⏳ A IA demorou demais. Tente novamente."
    except Exception as e:
        return f"⚠️ Erro ao consultar IA: {str(e)}"


# ── Lembretes do usuário (personalizados) ────────────────────────────────────

def carregar_lembretes_usuario():
    if os.path.exists(LEMBRETES_USUARIO_FILE):
        with open(LEMBRETES_USUARIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def salvar_lembretes_usuario(lembretes):
    with open(LEMBRETES_USUARIO_FILE, "w", encoding="utf-8") as f:
        json.dump(lembretes, f, ensure_ascii=False, indent=2)


def verificar_lembretes_especificos():
    agora = datetime.now(FUSO)
    lembretes = carregar_lembretes_usuario()
    restantes = []
    for l in lembretes:
        if l["tipo"] == "especifico":
            dt = datetime.strptime(l["datetime"], "%Y-%m-%d %H:%M")
            if (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (agora.year, agora.month, agora.day, agora.hour, agora.minute):
                enviar_lembrete(f"⏰ Lembrete: {l['texto']}")
            else:
                restantes.append(l)
        else:
            restantes.append(l)
    if len(restantes) != len(lembretes):
        salvar_lembretes_usuario(restantes)


# ── Lembretes agendados ───────────────────────────────────────────────────────

def enviar_lembrete(mensagem):
    chat_id = config["telegram"].get("chat_id", "")
    if not chat_id:
        print(f"[{datetime.now(FUSO).strftime('%H:%M')}] chat_id não configurado. Envie /start ao bot.")
        return
    try:
        bot.send_message(chat_id, mensagem)
        print(f"[{datetime.now(FUSO).strftime('%H:%M')}] Lembrete enviado")
    except Exception as e:
        print(f"[{datetime.now(FUSO).strftime('%H:%M')}] Erro ao enviar lembrete: {e}")


def configurar_agenda():
    schedule.clear()
    for lembrete in config.get("lembretes", []):
        schedule.every().day.at(lembrete["horario"]).do(enviar_lembrete, mensagem=lembrete["mensagem"])
    # Lembretes diários do usuário
    for l in carregar_lembretes_usuario():
        if l["tipo"] == "diario":
            schedule.every().day.at(l["hora"]).do(enviar_lembrete, mensagem=f"⏰ {l['texto']}")
    # Verifica lembretes específicos a cada minuto
    schedule.every().minute.do(verificar_lembretes_especificos)
    total = len(config.get("lembretes", []))
    print(f"  {total} lembretes agendados.")


def thread_agenda():
    while True:
        schedule.run_pending()
        time.sleep(30)


# ── Handlers do bot ───────────────────────────────────────────────────────────

def registrar_handlers():

    @bot.message_handler(commands=["start", "ajuda"])
    def cmd_start(msg):
        # Salva chat_id automaticamente na primeira vez
        chat_id_str = str(msg.chat.id)
        if not config["telegram"].get("chat_id"):
            config["telegram"]["chat_id"] = chat_id_str
            salvar_config()
            extra = "✅ *Seu chat foi vinculado! Você receberá os lembretes aqui.*\n\n"
        else:
            extra = ""

        bot.reply_to(msg, (
            f"{extra}"
            "🔔 *Assistente de Lembretes com IA*\n\n"
            "📋 *Comandos:*\n"
            "/lembrar [texto] — criar lembrete (data ou diário)\n"
            "/meus\\_lembretes — ver lembretes criados\n"
            "/cancelar\\_lembrete [n] — remover lembrete\n"
            "/tarefas — ver lista de tarefas\n"
            "/adicionar [tarefa] — adicionar tarefa\n"
            "/concluir [n] — marcar tarefa como feita\n"
            "/remover [n] — remover tarefa\n"
            "/lembretes — ver lembretes fixos\n\n"
            "💬 *Ou simplesmente mande uma mensagem — a IA responde!*\n"
            "_Ex: 'O que tenho para fazer hoje?' ou 'Me dê dicas de produtividade'_"
        ), parse_mode="Markdown")

    @bot.message_handler(commands=["tarefas"])
    def cmd_tarefas(msg):
        bot.reply_to(msg, f"📋 *Suas tarefas:*\n\n{formatar_tarefas()}", parse_mode="Markdown")

    @bot.message_handler(commands=["adicionar"])
    def cmd_adicionar(msg):
        texto = msg.text.replace("/adicionar", "").strip()
        if not texto:
            bot.reply_to(msg, "⚠️ Uso: `/adicionar Descrição da tarefa`", parse_mode="Markdown")
            return
        tarefas = carregar_tarefas()
        tarefas.append({"texto": texto, "concluida": False, "criada": date.today().isoformat()})
        salvar_tarefas(tarefas)
        bot.reply_to(msg, f"✅ Tarefa adicionada:\n*{texto}*", parse_mode="Markdown")

    @bot.message_handler(commands=["concluir"])
    def cmd_concluir(msg):
        try:
            n = int(msg.text.replace("/concluir", "").strip())
            tarefas = carregar_tarefas()
            tarefas[n - 1]["concluida"] = True
            salvar_tarefas(tarefas)
            bot.reply_to(msg, f"✅ Tarefa {n} concluída: *{tarefas[n-1]['texto']}*", parse_mode="Markdown")
        except (ValueError, IndexError):
            bot.reply_to(msg, "⚠️ Uso: `/concluir 1` (número da tarefa)", parse_mode="Markdown")

    @bot.message_handler(commands=["remover"])
    def cmd_remover(msg):
        try:
            n = int(msg.text.replace("/remover", "").strip())
            tarefas = carregar_tarefas()
            removida = tarefas.pop(n - 1)
            salvar_tarefas(tarefas)
            bot.reply_to(msg, f"🗑️ Tarefa removida: *{removida['texto']}*", parse_mode="Markdown")
        except (ValueError, IndexError):
            bot.reply_to(msg, "⚠️ Uso: `/remover 1` (número da tarefa)", parse_mode="Markdown")

    @bot.message_handler(commands=["limpar"])
    def cmd_limpar(msg):
        tarefas = carregar_tarefas()
        antes = len(tarefas)
        tarefas = [t for t in tarefas if not t.get("concluida")]
        salvar_tarefas(tarefas)
        bot.reply_to(msg, f"🧹 {antes - len(tarefas)} tarefa(s) concluída(s) removida(s).")

    @bot.message_handler(commands=["lembrar"])
    def cmd_lembrar(msg):
        texto = msg.text.replace("/lembrar", "").strip()
        if not texto:
            bot.reply_to(msg, "⚠️ Uso: `/lembrar Descrição do lembrete`\nExemplo: `/lembrar Tomar remédio`", parse_mode="Markdown")
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
                f'📝 *"{estados[chat_id]["texto"]}"*\n\n📅 Qual data e hora?\nFormato: `DD/MM HH:MM`\nExemplo: `25/06 14:30` ou `hoje 15:00`',
                chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown"
            )
        else:
            estados[chat_id]["tipo"] = "diario"
            estados[chat_id]["step"] = "hora"
            bot.edit_message_text(
                f'📝 *"{estados[chat_id]["texto"]}"*\n\n⏰ Que horas todo dia?\nFormato: `HH:MM`\nExemplo: `08:30`',
                chat_id=chat_id, message_id=call.message.message_id, parse_mode="Markdown"
            )
        bot.answer_callback_query(call.id)

    @bot.message_handler(commands=["meus_lembretes"])
    def cmd_meus_lembretes(msg):
        lembretes = carregar_lembretes_usuario()
        if not lembretes:
            bot.reply_to(msg, "Nenhum lembrete personalizado criado.\nUse /lembrar para adicionar!")
            return
        linhas = []
        for i, l in enumerate(lembretes, 1):
            if l["tipo"] == "especifico":
                dt = datetime.strptime(l["datetime"], "%Y-%m-%d %H:%M")
                linhas.append(f"{i}. 📅 {dt.strftime('%d/%m às %H:%M')} — {l['texto']}")
            else:
                linhas.append(f"{i}. 🔁 Todo dia às {l['hora']} — {l['texto']}")
        bot.reply_to(msg, "📋 *Seus lembretes personalizados:*\n\n" + "\n".join(linhas) +
                     "\n\nUse `/cancelar_lembrete [número]` para remover.", parse_mode="Markdown")

    @bot.message_handler(commands=["cancelar_lembrete"])
    def cmd_cancelar_lembrete(msg):
        try:
            n = int(msg.text.replace("/cancelar_lembrete", "").strip())
            lembretes = carregar_lembretes_usuario()
            removido = lembretes.pop(n - 1)
            salvar_lembretes_usuario(lembretes)
            configurar_agenda()
            bot.reply_to(msg, f"🗑️ Lembrete removido: *{removido['texto']}*", parse_mode="Markdown")
        except (ValueError, IndexError):
            bot.reply_to(msg, "⚠️ Uso: `/cancelar_lembrete 1` (número do lembrete)", parse_mode="Markdown")

    @bot.message_handler(commands=["lembretes"])
    def cmd_lembretes(msg):
        lembretes = config.get("lembretes", [])
        if not lembretes:
            bot.reply_to(msg, "Nenhum lembrete agendado.")
            return
        linhas = [f"⏰ `{l['horario']}` — {l['mensagem'].splitlines()[0]}" for l in lembretes]
        bot.reply_to(msg, "📅 *Lembretes agendados:*\n\n" + "\n".join(linhas), parse_mode="Markdown")

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
                    data = date.today()
                else:
                    dia, mes = dia_mes.split("/")
                    data = date(date.today().year, int(mes), int(dia))
                hora, minuto = hora_str.split(":")
                dt = datetime(data.year, data.month, data.day, int(hora), int(minuto))
                lembretes = carregar_lembretes_usuario()
                lembretes.append({"tipo": "especifico", "texto": estado["texto"], "datetime": dt.strftime("%Y-%m-%d %H:%M")})
                salvar_lembretes_usuario(lembretes)
                del estados[chat_id]
                bot.reply_to(msg, f"✅ Lembrete agendado!\n📅 *{dt.strftime('%d/%m/%Y às %H:%M')}*\n📝 {estado['texto']}", parse_mode="Markdown")
            except Exception:
                bot.reply_to(msg, "⚠️ Formato inválido. Use: `DD/MM HH:MM` ou `hoje HH:MM`\nExemplo: `hoje 15:30` ou `25/06 09:00`", parse_mode="Markdown")

        elif estado.get("step") == "hora":
            try:
                hora_str = msg.text.strip()
                h, m = hora_str.split(":")
                int(h); int(m)
                lembretes = carregar_lembretes_usuario()
                lembretes.append({"tipo": "diario", "texto": estado["texto"], "hora": hora_str})
                salvar_lembretes_usuario(lembretes)
                configurar_agenda()
                del estados[chat_id]
                bot.reply_to(msg, f"✅ Lembrete diário criado!\n🔁 *Todo dia às {hora_str}*\n📝 {estado['texto']}", parse_mode="Markdown")
            except Exception:
                bot.reply_to(msg, "⚠️ Formato inválido. Use: `HH:MM`\nExemplo: `08:30`", parse_mode="Markdown")

        else:
            bot.send_chat_action(chat_id, "typing")
            resposta = perguntar_ia(chat_id, msg.text)

            # Detecta se a IA criou um lembrete — aceita espaços extras no formato
            import re
            match = re.search(r'\[LEMBRETE\s*:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*:\s*(.+?)\]', resposta)
            if match:
                try:
                    dt = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M")
                    texto_lembrete = match.group(3).strip()
                    lembretes = carregar_lembretes_usuario()
                    lembretes.append({"tipo": "especifico", "texto": texto_lembrete, "datetime": dt.strftime("%Y-%m-%d %H:%M")})
                    salvar_lembretes_usuario(lembretes)
                    resposta = re.sub(r'\[LEMBRETE[^\]]+\]', '', resposta).strip()
                except Exception:
                    pass

            bot.reply_to(msg, resposta)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global bot

    print("=" * 54)
    print("   🤖 ASSISTENTE DE LEMBRETES COM IA (Telegram)")
    print("=" * 54)

    carregar_config()

    token = config["telegram"].get("token", "")
    if "SEU_TOKEN" in token or not token:
        print("\n❌ TELEGRAM_TOKEN não configurado! Defina a variável de ambiente.")
        sys.exit(1)

    api_key = config.get("groq", {}).get("api_key", "")
    if not api_key or "SUA_KEY" in api_key:
        print("\n⚠️  GROQ_API_KEY não configurada — chat com IA não funcionará.")

    bot = telebot.TeleBot(token)
    registrar_handlers()
    configurar_agenda()

    agendador = threading.Thread(target=thread_agenda, daemon=True)
    agendador.start()

    chat_id = config["telegram"].get("chat_id", "")
    if not chat_id:
        print("\n⚠️  Envie /start ao bot no Telegram para vincular seu chat.")
    else:
        print(f"\n✅ Chat vinculado: {chat_id}")

    print("\n✅ Bot rodando! Pressione Ctrl+C para encerrar.\n")

    bot.infinity_polling(timeout=30, long_polling_timeout=20)


def print_instrucoes_telegram():
    print("""
╔══════════════════════════════════════════════════════╗
║          COMO CRIAR SEU BOT NO TELEGRAM              ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  1. Abra o Telegram e procure por: @BotFather        ║
║  2. Mande: /newbot                                   ║
║  3. Escolha um nome (ex: Meus Lembretes)             ║
║  4. Escolha um username (ex: meuslembretes_bot)      ║
║  5. Copie o TOKEN que o BotFather te mandar          ║
║  6. Cole no config.json em "token": "TOKEN_AQUI"     ║
║  7. Execute o bot e mande /start para ele            ║
║     (o chat_id será salvo automaticamente)           ║
║                                                      ║
║  OLLAMA (IA local):                                  ║
║  1. Baixe em: https://ollama.com                     ║
║  2. Instale e execute: ollama pull llama3.2          ║
║  3. O Ollama inicia automaticamente ao ligar o PC    ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
