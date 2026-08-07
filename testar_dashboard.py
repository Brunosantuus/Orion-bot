"""Sobe backend + frontend juntos pra teste local, sem precisar de token do Telegram/Groq/Supabase.

Uso:
    python testar_dashboard.py
    python testar_dashboard.py caminho/para/exportar.zip   # importa um export do Apple Saúde antes de subir

Depois acesse (no PC ou no iPhone, mesma rede Wi-Fi/Ethernet):
    http://localhost:5173          (ou o IP local, se for de outro dispositivo)
"""
import atexit
import os
import shutil
import socket
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")  # evita UnicodeEncodeError com emoji no console do Windows
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv()  # lê .env local, se existir — antes dos setdefault, pra ele poder sobrescrever os valores de teste

os.environ.setdefault("ORION_CTRL_TOKEN", "teste-local")
os.environ.setdefault("ORION_WEB_SENHA", "teste-local")

import bot_telegram
import orion_servidor

_base = os.path.dirname(os.path.abspath(__file__))

bot_telegram.carregar_config()  # lê config.json/config.railway.json (só pra ter a estrutura de config; segredos vazios não quebram nada)

if len(sys.argv) > 1:
    caminho_export = sys.argv[1]
    print(f"Importando export de saúde: {caminho_export} ...")
    with open(caminho_export, "rb") as f:
        conteudo = f.read()
    resumo = bot_telegram.processar_export_apple_health(conteudo, os.path.basename(caminho_export))
    print(resumo, "\n")
else:
    # Sem arquivo passado: popula alguns dados de exemplo se ainda não houver nada, só pra ter algo pra ver.
    if not bot_telegram.carregar_saude_diaria():
        bot_telegram.registrar_saude_diaria(fonte="teste_manual", passos=8500, horas_sono=7.2, fc_repouso=58)
    if not bot_telegram.carregar_treino_historico():
        bot_telegram.registrar_treino_realizado("A", fonte="chat")

orion_servidor.iniciar_control_server()
orion_servidor.registrar_resumo_provider(bot_telegram.montar_resumo_dashboard)

# Chat: só responde de verdade se o config tiver uma chave Groq real (senão
# perguntar_ia devolve um aviso, sem quebrar). Usa "0" se não houver chat_id
# ainda vinculado (não precisa de um bot do Telegram rodando pra testar).
_chat_id_teste = bot_telegram.config.get("telegram", {}).get("chat_id") or "0"
orion_servidor.registrar_chat_provider(
    lambda msg: bot_telegram.processar_mensagem_ia(int(_chat_id_teste), msg))
orion_servidor.registrar_health_export_provider(bot_telegram.processar_export_apple_health)
orion_servidor.registrar_historico_provider(
    lambda: bot_telegram._hist_carregar_db(int(_chat_id_teste)))
orion_servidor.registrar_lembretes_provider(
    bot_telegram.carregar_lembretes_usuario, bot_telegram.criar_lembrete_web,
    bot_telegram.remover_lembrete_por_id, lambda: bot_telegram.config.get("lembretes", []))


def _ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ── Frontend (npm run dev) ────────────────────────────────────────────────────

_frontend_proc = None


def _iniciar_frontend():
    global _frontend_proc
    npm = shutil.which("npm")
    frontend_dir = os.path.join(_base, "frontend")
    if not npm:
        print("[frontend] npm nao encontrado no PATH — pulei. Rode `npm run dev` na pasta frontend/ manualmente.")
        return
    if not os.path.isdir(os.path.join(frontend_dir, "node_modules")):
        print("[frontend] node_modules nao existe — rode `npm install` dentro de frontend/ primeiro. Pulei.")
        return
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    _frontend_proc = subprocess.Popen([npm, "run", "dev"], cwd=frontend_dir, creationflags=flags)


def _parar_frontend():
    if _frontend_proc and _frontend_proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(_frontend_proc.pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            _frontend_proc.terminate()


atexit.register(_parar_frontend)
_iniciar_frontend()

print("\nBackend no ar. Frontend subindo (Vite) — em alguns segundos acesse:")
print(f"   http://localhost:5173   (ou http://{_ip_local()}:5173 de outro dispositivo na mesma rede)\n")
print("Senha de login (teste local): teste-local")
print("(Se o frontend nao subir, confirme que rodou `npm install` dentro de frontend/.)")
print("Ctrl+C para parar os dois.")

while True:
    time.sleep(3600)
