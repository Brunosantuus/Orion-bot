import { LayoutDashboard, MessageCircle, Settings } from "lucide-react"
import { cn } from "@/lib/utils"

export type Tab = "dashboard" | "chat" | "settings"

const ITEMS: { id: Tab; label: string; icon: typeof LayoutDashboard; disabled?: boolean }[] = [
  { id: "dashboard", label: "Resumo", icon: LayoutDashboard },
  { id: "chat", label: "Chat", icon: MessageCircle },
  { id: "settings", label: "Config", icon: Settings },
]

export function BottomNav({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 mx-auto flex max-w-md border-t border-border/60 bg-background/80 pb-[env(safe-area-inset-bottom)] backdrop-blur-lg">
      {ITEMS.map(({ id, label, icon: Icon, disabled }) => {
        const ativo = tab === id
        return (
          <button
            key={id}
            type="button"
            disabled={disabled}
            onClick={() => onChange(id)}
            className={cn(
              "flex flex-1 flex-col items-center gap-1 py-2.5 text-xs transition-colors",
              disabled && "pointer-events-none opacity-40"
            )}
          >
            <span
              className={cn(
                "flex size-8 items-center justify-center rounded-full transition-colors",
                ativo && "bg-primary/15 text-primary",
                !ativo && "text-muted-foreground"
              )}
            >
              <Icon className="size-4.5" />
            </span>
            <span className={cn(ativo ? "text-primary" : "text-muted-foreground")}>{label}</span>
            {disabled && <span className="text-[10px] leading-none text-muted-foreground/70">em breve</span>}
          </button>
        )
      })}
    </nav>
  )
}
