import { useState, type FormEvent } from "react"
import { Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { login } from "@/lib/api"

export function LoginPage({ onEntrar }: { onEntrar: () => void }) {
  const [senha, setSenha] = useState("")
  const [erro, setErro] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const entrar = async (e: FormEvent) => {
    e.preventDefault()
    setErro(null)
    setEnviando(true)
    try {
      await login(senha)
      onEntrar()
    } catch (e) {
      setErro(String(e instanceof Error ? e.message : e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-5 p-6 text-center">
      <span className="flex size-16 items-center justify-center rounded-full bg-gradient-to-br from-[var(--orion-glow-violet)] to-[var(--orion-glow-blue)] shadow-[0_0_32px_-4px_var(--orion-glow-violet)]">
        <Sparkles className="size-7 text-white" />
      </span>
      <div>
        <h1 className="text-lg font-semibold">Orion</h1>
        <p className="text-sm text-muted-foreground">digite a senha pra entrar</p>
      </div>
      <form onSubmit={entrar} className="flex w-full max-w-xs flex-col gap-2.5">
        <Input
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          placeholder="Senha"
          autoFocus
        />
        {erro && <p className="text-sm text-destructive">{erro}</p>}
        <Button
          type="submit"
          disabled={enviando || !senha}
          className="bg-gradient-to-br from-[var(--orion-glow-violet)] to-[var(--orion-glow-blue)] text-white hover:opacity-90"
        >
          Entrar
        </Button>
      </form>
    </div>
  )
}
