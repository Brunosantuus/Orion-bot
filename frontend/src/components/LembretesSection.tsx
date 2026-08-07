import { useEffect, useState } from "react"
import { Bell, Lock, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { getLembretes, criarLembrete, removerLembrete, type Lembrete, type LembreteFixo } from "@/lib/api"

export function LembretesSection() {
  const [lembretes, setLembretes] = useState<Lembrete[]>([])
  const [fixos, setFixos] = useState<LembreteFixo[]>([])
  const [tipo, setTipo] = useState<"especifico" | "diario">("diario")
  const [texto, setTexto] = useState("")
  const [data, setData] = useState("")
  const [hora, setHora] = useState("")
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  const carregar = () => {
    getLembretes().then((d) => {
      setLembretes(d.lembretes)
      setFixos(d.fixos)
    })
  }

  useEffect(carregar, [])

  const criar = async () => {
    setErro(null)
    if (!texto.trim()) return
    setEnviando(true)
    try {
      if (tipo === "especifico") {
        if (!data || !hora) throw new Error("preenche data e hora")
        await criarLembrete({ tipo, texto, datetime: `${data} ${hora}` })
      } else {
        if (!hora) throw new Error("preenche a hora")
        await criarLembrete({ tipo, texto, hora })
      }
      setTexto("")
      setData("")
      setHora("")
      carregar()
    } catch (e) {
      setErro(String(e instanceof Error ? e.message : e))
    } finally {
      setEnviando(false)
    }
  }

  const remover = async (id: number) => {
    await removerLembrete(id)
    carregar()
  }

  return (
    <div className="rounded-2xl border border-border/60 bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold">Lembretes</h2>

      <div className="mb-3 flex gap-1.5 rounded-full bg-muted p-1">
        {(["diario", "especifico"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTipo(t)}
            className={cn(
              "flex-1 rounded-full py-1.5 text-xs font-medium transition-colors",
              tipo === t ? "bg-primary text-primary-foreground" : "text-muted-foreground"
            )}
          >
            {t === "diario" ? "Todo dia" : "Data específica"}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <Input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Beber água, pagar conta…"
        />
        {tipo === "especifico" ? (
          <div className="flex gap-2">
            <Input type="date" value={data} onChange={(e) => setData(e.target.value)} />
            <Input type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
          </div>
        ) : (
          <Input type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
        )}
        {erro && <p className="text-sm text-destructive">{erro}</p>}
        <Button
          type="button"
          disabled={enviando || !texto.trim()}
          onClick={criar}
          className="bg-gradient-to-br from-[var(--orion-glow-violet)] to-[var(--orion-glow-blue)] text-white hover:opacity-90"
        >
          Criar lembrete
        </Button>
      </div>

      {lembretes.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2">
          {lembretes.map((l) => (
            <li
              key={l.id}
              className="flex items-center gap-2 rounded-xl border border-border/60 px-3 py-2 text-sm"
            >
              <Bell className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate">{l.texto}</p>
                <p className="text-xs text-muted-foreground">
                  {l.tipo === "diario" ? `todo dia às ${l.hora}` : l.datetime}
                </p>
              </div>
              <button
                type="button"
                onClick={() => remover(l.id)}
                className="shrink-0 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {fixos.length > 0 && (
        <>
          <p className="mt-4 mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Fixos (configurados no bot)
          </p>
          <ul className="flex flex-col gap-2">
            {fixos.map((f, i) => (
              <li
                key={i}
                className="flex items-center gap-2 rounded-xl border border-border/40 px-3 py-2 text-sm text-muted-foreground"
              >
                <Lock className="size-3.5 shrink-0" />
                <span className="shrink-0 font-mono text-xs">{f.horario}</span>
                <span className="truncate">{f.mensagem.split("\n")[0]}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
