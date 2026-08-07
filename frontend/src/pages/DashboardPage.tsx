import { useEffect, useState, type ReactNode } from "react"
import {
  Scale,
  Dumbbell,
  Flame,
  Droplet,
  Footprints,
  Moon,
  HeartPulse,
  ListTodo,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { getResumo, type Resumo } from "@/lib/api"
import { cn } from "@/lib/utils"

function Stat({
  icon: Icon,
  color,
  label,
  value,
}: {
  icon: typeof Scale
  color: "violet" | "blue" | "amber" | "green"
  label: string
  value: ReactNode
}) {
  const cores: Record<string, string> = {
    violet: "bg-[var(--orion-glow-violet)]/15 text-[var(--orion-glow-violet)]",
    blue: "bg-[var(--orion-glow-blue)]/15 text-[var(--orion-glow-blue)]",
    amber: "bg-[#f2b84b]/15 text-[#f2b84b]",
    green: "bg-[#56d69c]/15 text-[#56d69c]",
  }
  return (
    <Card className="border-border/60">
      <CardContent className="flex items-center gap-3">
        <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-full", cores[color])}>
          <Icon className="size-4.5" />
        </span>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-xs text-muted-foreground">{label}</p>
          <p className="truncate text-base font-semibold">{value ?? "—"}</p>
        </div>
      </CardContent>
    </Card>
  )
}

export function DashboardPage() {
  const [resumo, setResumo] = useState<Resumo | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    let ativo = true
    const carregar = () => {
      getResumo()
        .then((d) => ativo && setResumo(d))
        .catch((e) => ativo && setErro(String(e)))
    }
    carregar()
    const id = setInterval(carregar, 30_000)
    return () => {
      ativo = false
      clearInterval(id)
    }
  }, [])

  if (erro) return <p className="p-4 text-sm text-destructive">{erro}</p>
  if (!resumo) return <p className="p-4 text-sm text-muted-foreground">Carregando…</p>

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <Stat
        icon={Scale}
        color="violet"
        label="Peso"
        value={
          resumo.peso.atual != null
            ? `${resumo.peso.atual}kg${resumo.peso.tendencia ? ` ${resumo.peso.tendencia}` : ""}`
            : "—"
        }
      />
      <Stat icon={Dumbbell} color="blue" label="Treino sugerido" value={resumo.treino_sugerido} />
      <div className="grid grid-cols-2 gap-3">
        <Stat icon={Flame} color="amber" label="Sequência academia" value={`${resumo.streaks.academia}d`} />
        <Stat icon={Droplet} color="blue" label="Sequência água" value={`${resumo.streaks.agua}d`} />
        <Stat icon={Footprints} color="green" label="Passos hoje" value={resumo.saude_hoje.passos} />
        <Stat
          icon={Moon}
          color="violet"
          label="Sono"
          value={resumo.saude_hoje.horas_sono != null ? `${resumo.saude_hoje.horas_sono}h` : "—"}
        />
        <Stat
          icon={HeartPulse}
          color="amber"
          label="FC repouso"
          value={resumo.saude_hoje.fc_repouso != null ? `${resumo.saude_hoje.fc_repouso}bpm` : "—"}
        />
        <Stat icon={ListTodo} color="green" label="Tarefas pendentes" value={resumo.tarefas_pendentes} />
      </div>
    </div>
  )
}
