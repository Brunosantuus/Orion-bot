"""
orion_servidor.py — Integração do bot com o servidor do celular (Termux).

Modelo "sentido invertido": o celular (Android, atrás do NAT) NÃO aceita
conexões de entrada, então é ELE quem fala com a VM. Este módulo:

  1. Sobe um pequeno servidor HTTP (thread) que o celular acessa via Tailscale
     (http://<ip-tailscale-da-VM>:8765), autenticado por token:
        POST /report    -> celular publica status/links (guardado em ESTADO)
        GET  /commands  -> celular busca comandos pendentes (start/stop) e limpa a fila
        POST /ack       -> celular confirma execução (opcional, só loga)
  2. Registra os comandos do Telegram: /servidor /tunnels /ligar /desligar

Integração no bot_telegram.py (3 linhas):
    import orion_servidor                                   # topo
    ...
    def main():
        ...
        bot = telebot.TeleBot(token)
        orion_servidor.iniciar_control_server()             # <-- 1
        orion_servidor.registrar_comandos(bot)              # <-- 2 (dentro de main, após criar bot)
        registrar_handlers()
        ...

Config por variáveis de ambiente (na VM):
    ORION_CTRL_TOKEN  -> token compartilhado com o celular (obrigatório)
    ORION_CTRL_PORT   -> porta do servidor de controle (padrão 8765)
"""

import os
import json
import time
import threading
import http.server

try:
    import requests  # já é dependência do bot
except Exception:
    requests = None

CTRL_TOKEN = os.environ.get('ORION_CTRL_TOKEN', '')
CTRL_PORT = int(os.environ.get('ORION_CTRL_PORT', '8765'))

# Credenciais do file server do celular (para /upload via túnel autenticado).
SRV_USER = os.environ.get('ORION_SRV_USER', 'orion')
SRV_PASS = os.environ.get('ORION_SRV_PASS', '')

# ── Alertas proativos (bateria / temperatura / serviço caído / offline) ──
ALERT_CHAT_ID = os.environ.get('ORION_ALERT_CHAT_ID') or os.environ.get('TELEGRAM_CHAT_ID', '')
BAT_LOW = int(os.environ.get('ORION_BAT_LOW', '20'))
BAT_HIGH = int(os.environ.get('ORION_BAT_HIGH', '90'))
TEMP_MAX = float(os.environ.get('ORION_TEMP_MAX', '50'))
OFFLINE_SEC = int(os.environ.get('ORION_OFFLINE_SEC', '150'))

_BOT = None
_ALERTA = {'bat_low': False, 'bat_high': False, 'temp': False, 'offline': False, 'servicos': None}

# Estado compartilhado entre o servidor HTTP e os comandos do Telegram
ESTADO = {'ultimo_report': None, 'ts': 0.0}
FILA_COMANDOS = []          # comandos pendentes p/ o celular executar
_LOCK = threading.Lock()


# ───────────────────────── servidor HTTP (celular -> VM) ─────────────────────────

class _CtrlHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _autorizado(self):
        if not CTRL_TOKEN:
            return False  # sem token configurado => nega tudo (fail-safe)
        return self.headers.get('X-Orion-Token', '') == CTRL_TOKEN

    def _json(self, obj, status=200):
        corpo = json.dumps(obj).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(corpo)))
        self.end_headers()
        try:
            self.wfile.write(corpo)
        except Exception:
            pass

    def do_GET(self):
        if not self._autorizado():
            return self._json({'erro': 'nao autorizado'}, 401)
        if self.path == '/commands':
            with _LOCK:
                pendentes = list(FILA_COMANDOS)
                FILA_COMANDOS.clear()
            return self._json({'comandos': pendentes})
        return self._json({'erro': 'nao encontrado'}, 404)

    def do_POST(self):
        if not self._autorizado():
            return self._json({'erro': 'nao autorizado'}, 401)
        tam = int(self.headers.get('Content-Length', 0) or 0)
        corpo = self.rfile.read(tam) if tam else b''
        try:
            dados = json.loads(corpo) if corpo else {}
        except Exception:
            dados = {}
        if self.path == '/report':
            with _LOCK:
                ESTADO['ultimo_report'] = dados
                ESTADO['ts'] = time.time()
            return self._json({'ok': True})
        if self.path == '/ack':
            print(f"[orion_servidor] ack do celular: {dados}")
            return self._json({'ok': True})
        return self._json({'erro': 'nao encontrado'}, 404)


def iniciar_control_server():
    """Sobe o servidor de controle em thread daemon."""
    if not CTRL_TOKEN:
        print("[orion_servidor] ORION_CTRL_TOKEN não definido — servidor de controle DESLIGADO.")
        return

    def _run():
        try:
            http.server.HTTPServer.allow_reuse_address = True
            srv = http.server.HTTPServer(('0.0.0.0', CTRL_PORT), _CtrlHandler)
            print(f"[orion_servidor] controle ouvindo em 0.0.0.0:{CTRL_PORT} (via Tailscale)")
            srv.serve_forever()
        except Exception as e:
            print(f"[orion_servidor] falha no servidor de controle: {e}")

    threading.Thread(target=_run, daemon=True).start()


# ───────────────────────── comandos do Telegram ─────────────────────────

def _fmt_idade(ts):
    if not ts:
        return "nunca"
    seg = int(time.time() - ts)
    if seg < 60:
        return f"há {seg}s"
    if seg < 3600:
        return f"há {seg // 60}min"
    return f"há {seg // 3600}h"


def _status_texto():
    with _LOCK:
        rep = ESTADO['ultimo_report']
        ts = ESTADO['ts']
    if not rep:
        return ("📴 *Servidor do celular*\nSem contato ainda.\n"
                "_O celular reporta a cada ~15s quando o agente está rodando._")
    online = (time.time() - ts) < 90
    bolinha = "🟢 online" if online else "🔴 sem contato recente"
    svc = rep.get('servicos', {})
    linhas = [f"📱 *Servidor do celular* — {bolinha} ({_fmt_idade(ts)})", ""]
    nomes = {
        'fileserver': '📁 Arquivos', 'mediaserver': '🎬 Media',
        'todoserver': '✅ Tarefas', 'dnsblocker': '🛡️ DNS',
        'cloudflared': '☁️ Túneis',
    }
    for chave, rotulo in nomes.items():
        if chave in svc:
            linhas.append(f"{rotulo}: {'✅' if svc[chave] else '❌'}")
    bat = rep.get('bateria')
    if bat is not None:
        car = ' ⚡' if rep.get('carregando') else ''
        linhas.append(f"🔋 Bateria: {bat}%{car}")
    if rep.get('temperatura'):
        linhas.append(f"🌡️ Temp: {rep['temperatura']}°C")
    if rep.get('ip_local'):
        linhas.append(f"🌐 IP local: `{rep['ip_local']}`")
    return "\n".join(linhas)


def _tunnels_texto():
    with _LOCK:
        rep = ESTADO['ultimo_report']
    tuns = (rep or {}).get('tunnels') or {}
    if not tuns:
        return "🔗 Nenhum túnel ativo no último report do celular."
    nomes = {'arquivos': '📁 Arquivos', 'media': '🎬 Media'}
    linhas = ["🔗 *Links externos (Cloudflare):*", ""]
    for k, v in tuns.items():
        linhas.append(f"{nomes.get(k, k)}: {v}")
    linhas.append("\n🔑 Requer login (usuário/senha).")
    return "\n".join(linhas)


def _url_arquivos():
    """URL atual do túnel do file server (do último report do celular)."""
    with _LOCK:
        rep = ESTADO['ultimo_report']
    return ((rep or {}).get('tunnels') or {}).get('arquivos')


def _tratar_upload(bot, msg):
    """Baixa o arquivo do Telegram e sobe no file server do celular via túnel."""
    file_id = nome = None
    ct = msg.content_type
    if ct == 'document':
        file_id, nome = msg.document.file_id, msg.document.file_name
    elif ct == 'photo':
        file_id, nome = msg.photo[-1].file_id, f"foto_{msg.photo[-1].file_unique_id}.jpg"
    elif ct == 'video':
        file_id = msg.video.file_id
        nome = getattr(msg.video, 'file_name', None) or f"video_{msg.video.file_unique_id}.mp4"
    elif ct == 'audio':
        file_id = msg.audio.file_id
        nome = getattr(msg.audio, 'file_name', None) or f"audio_{msg.audio.file_unique_id}.mp3"
    elif ct == 'voice':
        file_id, nome = msg.voice.file_id, f"voz_{msg.voice.file_unique_id}.ogg"
    if not file_id:
        return

    if requests is None:
        bot.reply_to(msg, "⚠️ Módulo 'requests' indisponível no bot.")
        return
    if not SRV_PASS:
        bot.reply_to(msg, "⚠️ Falta definir ORION_SRV_PASS no bot para autenticar no file server.")
        return
    url = _url_arquivos()
    if not url:
        bot.reply_to(msg, "📴 Servidor do celular offline (sem túnel). Use /ligar e tente de novo.")
        return

    try:
        info = bot.get_file(file_id)
        conteudo = bot.download_file(info.file_path)
    except Exception as e:
        bot.reply_to(msg, f"❌ Não baixei o arquivo do Telegram: {e}\n(bots têm limite ~20MB.)")
        return

    try:
        r = requests.post(f"{url}/upload", auth=(SRV_USER, SRV_PASS),
                          files={'files': (nome, conteudo)}, timeout=120)
    except Exception as e:
        bot.reply_to(msg, f"❌ Falha ao enviar ao servidor: {e}")
        return

    if r.status_code == 200:
        try:
            salvos = r.json().get('salvos', [nome])
        except Exception:
            salvos = [nome]
        bot.reply_to(msg, f"✅ Enviado ao servidor: *{', '.join(salvos)}*\n🔗 {url}",
                     parse_mode="Markdown", disable_web_page_preview=True)
    elif r.status_code == 401:
        bot.reply_to(msg, "❌ Servidor recusou (401) — ORION_SRV_PASS não bate com a senha do file server.")
    else:
        bot.reply_to(msg, f"❌ Servidor recusou (HTTP {r.status_code}).")


def _enviar_alerta(texto):
    if not (_BOT and ALERT_CHAT_ID):
        return
    try:
        _BOT.send_message(ALERT_CHAT_ID, texto, parse_mode="Markdown")
    except Exception as e:
        print(f"[orion_servidor] falha ao enviar alerta: {e}")


def _monitor_alertas():
    """Loop que avalia o último report e dispara alertas (com debounce)."""
    while True:
        time.sleep(30)
        try:
            with _LOCK:
                rep = ESTADO['ultimo_report']
                ts = ESTADO['ts']
            if not rep:
                continue
            idade = time.time() - ts

            # offline / online (não avalia o resto com dados velhos)
            if idade > OFFLINE_SEC:
                if not _ALERTA['offline']:
                    _ALERTA['offline'] = True
                    _enviar_alerta(f"📴 *Servidor do celular offline* — sem contato há "
                                   f"{int(idade)}s. (Tailscale caiu ou o Android encerrou o agente.)")
                continue
            if _ALERTA['offline']:
                _ALERTA['offline'] = False
                _enviar_alerta("✅ *Servidor do celular voltou* — contato restabelecido.")

            # bateria
            bat = rep.get('bateria')
            if isinstance(bat, int):
                if bat < BAT_LOW and not _ALERTA['bat_low']:
                    _ALERTA['bat_low'] = True
                    _enviar_alerta(f"🪫 *Bateria baixa: {bat}%* — o celular pode desligar. "
                                   f"Verifique o carregador.")
                elif bat >= BAT_LOW + 10:
                    _ALERTA['bat_low'] = False
                if rep.get('carregando') and bat >= BAT_HIGH and not _ALERTA['bat_high']:
                    _ALERTA['bat_high'] = True
                    _enviar_alerta(f"🔋 *Bateria em {bat}%* e carregando. Num celular 24/7 no "
                                   f"carregador, ficar sempre em ~100% desgasta a bateria — "
                                   f"considere um limitador de carga (~80%).")
                elif bat < BAT_HIGH - 10:
                    _ALERTA['bat_high'] = False

            # temperatura
            temp = rep.get('temperatura')
            if isinstance(temp, (int, float)) and temp > 0:
                if temp > TEMP_MAX and not _ALERTA['temp']:
                    _ALERTA['temp'] = True
                    _enviar_alerta(f"🌡️ *Celular quente: {temp}°C* (acima de {int(TEMP_MAX)}°C). "
                                   f"Verifique ventilação/carga.")
                elif temp < TEMP_MAX - 5:
                    _ALERTA['temp'] = False

            # serviços (transição no ar -> caiu)
            svc = rep.get('servicos', {}) or {}
            prev = _ALERTA['servicos']
            if prev is not None:
                nomes = {'fileserver': 'Arquivos', 'mediaserver': 'Media',
                         'todoserver': 'Tarefas', 'dnsblocker': 'DNS', 'cloudflared': 'Túneis'}
                caidos = [nomes.get(k, k) for k in svc if prev.get(k) and not svc.get(k)]
                if caidos:
                    _enviar_alerta("❌ *Serviço(s) fora do ar:* " + ", ".join(caidos) +
                                   "\nUse /ligar para restabelecer.")
            _ALERTA['servicos'] = dict(svc)
        except Exception as e:
            print(f"[orion_servidor] erro no monitor de alertas: {e}")


def _iniciar_alertas():
    if not ALERT_CHAT_ID:
        print("[orion_servidor] alertas DESLIGADOS (defina ORION_ALERT_CHAT_ID ou TELEGRAM_CHAT_ID).")
        return
    threading.Thread(target=_monitor_alertas, daemon=True).start()
    print(f"[orion_servidor] alertas ativos (bat<{BAT_LOW}%, temp>{int(TEMP_MAX)}°C, "
          f"offline>{OFFLINE_SEC}s) -> chat {ALERT_CHAT_ID}")


def registrar_comandos(bot):
    """Registra /servidor /tunnels /ligar /desligar, upload e alertas."""
    global _BOT
    _BOT = bot
    _iniciar_alertas()

    @bot.message_handler(commands=["alertas"])
    def _cmd_alertas(msg):
        estado = "🟢 ligados" if ALERT_CHAT_ID else "🔴 desligados (falta ORION_ALERT_CHAT_ID)"
        bot.reply_to(msg, f"🔔 *Alertas do servidor* — {estado}\n\n"
                          f"🪫 Bateria baixa: < {BAT_LOW}%\n"
                          f"🔋 Bateria alta: ≥ {BAT_HIGH}% (carregando)\n"
                          f"🌡️ Temperatura: > {int(TEMP_MAX)}°C\n"
                          f"📴 Offline: sem contato > {OFFLINE_SEC}s",
                     parse_mode="Markdown")

    @bot.message_handler(content_types=['document', 'photo', 'video', 'audio', 'voice'])
    def _cmd_upload(msg):
        _tratar_upload(bot, msg)

    @bot.message_handler(commands=["servidor"])
    def _cmd_servidor(msg):
        bot.reply_to(msg, _status_texto(), parse_mode="Markdown")

    @bot.message_handler(commands=["tunnels", "links"])
    def _cmd_tunnels(msg):
        bot.reply_to(msg, _tunnels_texto(), parse_mode="Markdown",
                     disable_web_page_preview=True)

    @bot.message_handler(commands=["ligar"])
    def _cmd_ligar(msg):
        with _LOCK:
            FILA_COMANDOS.append('start')
        bot.reply_to(msg, "▶️ Comando *ligar* enfileirado. O celular executa no próximo "
                          "contato (~15s) e você recebe os links quando subir.",
                     parse_mode="Markdown")

    @bot.message_handler(commands=["desligar"])
    def _cmd_desligar(msg):
        with _LOCK:
            FILA_COMANDOS.append('stop')
        bot.reply_to(msg, "⏹️ Comando *desligar* enfileirado. O celular para os serviços "
                          "no próximo contato (~15s).", parse_mode="Markdown")
