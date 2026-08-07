import { useEffect, useState } from "react"
import { Sparkles } from "lucide-react"
import { BottomNav, type Tab } from "@/components/BottomNav"
import { DashboardPage } from "@/pages/DashboardPage"
import { ChatPage } from "@/pages/ChatPage"
import { SettingsPage } from "@/pages/SettingsPage"
import { LoginPage } from "@/pages/LoginPage"
import { getSessao } from "@/lib/api"

function App() {
  const [tab, setTab] = useState<Tab>("dashboard")
  const [logado, setLogado] = useState<boolean | null>(null)

  useEffect(() => {
    getSessao().then(setLogado)
  }, [])

  if (logado === null) return null
  if (!logado) return <LoginPage onEntrar={() => setLogado(true)} />

  return (
    <div className="mx-auto flex h-dvh max-w-md flex-col text-foreground">
      <header className="flex items-center gap-3 border-b border-border/60 px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[var(--orion-glow-violet)] to-[var(--orion-glow-blue)] shadow-[0_0_18px_-2px_var(--orion-glow-violet)]">
          <Sparkles className="size-4.5 text-white" />
        </div>
        <div className="leading-tight">
          <h1 className="text-sm font-semibold">Orion</h1>
          <p className="text-xs text-muted-foreground">seu assistente pessoal</p>
        </div>
      </header>
      <main className="min-h-0 flex-1 pb-16">
        {tab === "dashboard" && <DashboardPage />}
        {tab === "chat" && <ChatPage />}
        {tab === "settings" && <SettingsPage />}
      </main>
      <BottomNav tab={tab} onChange={setTab} />
    </div>
  )
}

export default App
