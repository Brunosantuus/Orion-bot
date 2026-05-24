import json
import os
import schedule
import threading
import time
import telebot
import requests
from datetime import date, datetime

_base = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(_base, "config.json") if os.path.exists(os.path.join(_base, "config.json")) else os.path.join(_base, "config.railway.json")
TAREFAS_FILE = os.path.join(os.path.dirname(__file__), "tarefas.json")

config = {}
bot = None
historico_chat = {}  # chat_id -> lista de mensagens para contexto da IA


# ── Config ──────────────────────────────────────────────────────────────────

def carregar_config():
    global config
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    # Variáveis de ambiente têm prioridade (usado no Railway)
    if os.environ.get("TELEGRAM_TOKEN"):
        config["telegram"]["token"] = os.environ["TELEGRAM_TOKEN"]
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

    system_prompt = (
        "Você é um assistente pessoal chamado 'Lembrete'. "
        "Responda SEMPRE em português brasileiro de forma amigável, direta e objetiva. "
        "Você ajuda o usuário a gerenciar tarefas, saúde (beber água, exercícios) e trabalho. "
        "Seja breve nas respostas — máximo 3 parágrafos.\n\n"
        f"Tarefas atuais do usuário:\n{formatar_tarefas()}"
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


# ── Lembretes agendados ───────────────────────────────────────────────────────

def enviar_lembrete(mensagem):
    chat_id = config["telegram"].get("chat_id", "")
    if not chat_id:
        print(f"[{datetime.now().strftime('%H:%M')}] chat_id não configurado. Envie /start ao bot.")
        return
    try:
        bot.send_message(chat_id, mensagem)
        print(f"[{datetime.now().strftime('%H:%M')}] Lembrete enviado")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M')}] Erro ao enviar lembrete: {e}")


def configurar_agenda():
    schedule.clear()
    for lembrete in config.get("lembretes", []):
        horario = lembrete["horario"]
        msg = lembrete["mensagem"]
        schedule.every().day.at(horario).do(enviar_lembrete, mensagem=msg)
    print(f"  {len(config.get('lembretes', []))} lembretes agendados.")


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
            "/tarefas — ver lista de tarefas\n"
            "/adicionar [tarefa] — adicionar tarefa\n"
            "/concluir [n] — marcar tarefa como feita\n"
            "/remover [n] — remover tarefa\n"
            "/limpar — apagar tarefas concluídas\n"
            "/lembretes — ver horários agendados\n\n"
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
        bot.send_chat_action(msg.chat.id, "typing")
        resposta = perguntar_ia(msg.chat.id, msg.text)
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
        print("\n❌ Configure o token do Telegram no arquivo config.json!")
        input("\nPressione Enter para sair...")
        return

    api_key = config.get("gemini", {}).get("api_key", "")
    if not api_key or "SUA_KEY" in api_key:
        print("\n⚠️  Chave do Gemini não configurada — chat com IA não funcionará.")
        print("   Adicione sua key em config.json → gemini.api_key")

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
