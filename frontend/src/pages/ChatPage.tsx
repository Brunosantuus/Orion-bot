import { useEffect, useRef, useState } from "react"
import { Send, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { sendChat, getHistorico, type MensagemHistorico } from "@/lib/api"

type Mensagem = MensagemHistorico

function Avatar() {
  return (
    <span className="flex size-7 shrink-0 items-center justify-center self-end rounded-full bg-gradient-to-br from-[var(--orion-glow-violet)] to-[var(--orion-glow-blue)]">
      <Sparkles className="size-3.5 text-white" />
    </span>
  )
}

export function ChatPage() {
  const [mensagens, setMensagens] = useState<Mensagem[]>([])
  const [carregando, setCarregando] = useState(true)
  const [texto, setTexto] = useState("")
  const [enviando, setEnviando] = useState(false)
  const fimRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getHistorico()
      .then((h) => {
        setMensagens(h)
        setTimeout(() => fimRef.current?.scrollIntoView(), 50)
      })
      .finally(() => setCarregando(false))
  }, [])

  const enviar = async () => {
    const mensagem = texto.trim()
    if (!mensagem || enviando) return
    setTexto("")
    setMensagens((m) => [...m, { role: "user", content: mensagem }])
    setEnviando(true)
    try {
      const resposta = await sendChat(mensagem)
      setMensagens((m) => [...m, { role: "assistant", content: resposta }])
    } catch (e) {
      setMensagens((m) => [...m, { role: "assistant", content: `⚠️ ${e}` }])
    } finally {
      setEnviando(false)
      setTimeout(() => fimRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <ScrollArea className="flex-1 px-4 py-3">
        <div className="flex flex-col gap-2.5">
          {!carregando && mensagens.length === 0 && (
            <div className="mt-10 flex flex-col items-center gap-3 text-center">
              <span className="flex size-14 items-center justify-center rounded-full bg-gradient-to-br from-[var(--orion-glow-violet)] to-[var(--orion-glow-blue)] shadow-[0_0_28px_-4px_var(--orion-glow-violet)]">
                <Sparkles className="size-6 text-white" />
              </span>
              <p className="text-sm text-muted-foreground">Manda uma mensagem pro Orion 👋</p>
            </div>
          )}
          {mensagens.map((m, i) => (
            <div
              key={i}
              className={cn(
                "flex items-end gap-2",
                m.role === "user" ? "flex-row-reverse" : "flex-row"
              )}
            >
              {m.role === "assistant" && <Avatar />}
              <div
                className={cn(
                  "max-w-[75%] rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap",
                  m.role === "user"
                    ? "rounded-br-sm bg-gradient-to-br from-[var(--orion-glow-violet)] to-[color-mix(in_oklab,var(--orion-glow-violet),var(--orion-glow-blue)_35%)] text-white"
                    : "rounded-bl-sm border border-border/60 bg-card text-foreground"
                )}
              >
                {m.content}
              </div>
            </div>
          ))}
          {enviando && (
            <div className="flex items-end gap-2">
              <Avatar />
              <div className="rounded-2xl rounded-bl-sm border border-border/60 bg-card px-3.5 py-2 text-sm text-muted-foreground">
                digitando…
              </div>
            </div>
          )}
          <div ref={fimRef} />
        </div>
      </ScrollArea>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          enviar()
        }}
        className="flex items-center gap-2 border-t border-border/60 p-4"
      >
        <Input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Fala com o Orion…"
          disabled={enviando}
          className="h-12 rounded-full text-base"
        />
        <Button
          type="submit"
          disabled={enviando || !texto.trim()}
          className="size-12 shrink-0 rounded-full bg-gradient-to-br from-[var(--orion-glow-violet)] to-[var(--orion-glow-blue)] text-white hover:opacity-90"
        >
          <Send className="size-5" />
        </Button>
      </form>
    </div>
  )
}
