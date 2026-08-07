import { useRef, useState } from "react"
import { Upload } from "lucide-react"
import { Button } from "@/components/ui/button"
import { importarSaude } from "@/lib/api"
import { LembretesSection } from "@/components/LembretesSection"

export function SettingsPage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [enviando, setEnviando] = useState(false)
  const [resultado, setResultado] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  const escolherArquivo = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const arquivo = e.target.files?.[0]
    e.target.value = ""
    if (!arquivo) return
    setEnviando(true)
    setErro(null)
    setResultado(null)
    try {
      const resumo = await importarSaude(arquivo)
      setResultado(resumo)
    } catch (err) {
      setErro(String(err instanceof Error ? err.message : err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-4">
      <div className="rounded-2xl border border-border/60 bg-card p-4">
        <h2 className="mb-1 text-sm font-semibold">Importar dados de saúde</h2>
        <p className="mb-3 text-xs text-muted-foreground">
          No iPhone: Saúde → seu perfil → "Exportar Todos os Dados de Saúde".
          Manda o .zip ou .xml aqui.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".zip,.xml"
          className="hidden"
          onChange={escolherArquivo}
        />
        <Button
          type="button"
          disabled={enviando}
          onClick={() => inputRef.current?.click()}
          className="w-full bg-gradient-to-br from-[var(--orion-glow-violet)] to-[var(--orion-glow-blue)] text-white hover:opacity-90"
        >
          <Upload className="size-4" />
          {enviando ? "Processando…" : "Escolher arquivo"}
        </Button>
        {resultado && (
          <p className="mt-3 text-sm whitespace-pre-wrap text-foreground">{resultado}</p>
        )}
        {erro && <p className="mt-3 text-sm text-destructive">{erro}</p>}
      </div>

      <LembretesSection />
    </div>
  )
}
