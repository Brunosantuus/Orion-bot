export interface Resumo {
  peso: { atual: number | null; tendencia: string | null }
  treino_sugerido: string
  streaks: { academia: number; agua: number }
  saude_hoje: {
    passos: number | null
    horas_sono: number | null
    fc_repouso: number | null
  }
  tarefas_pendentes: number
}

export async function getSessao(): Promise<boolean> {
  const r = await fetch("/api/session", { credentials: "include" })
  if (!r.ok) return false
  return !!(await r.json()).logado
}

export async function login(senha: string): Promise<void> {
  const r = await fetch("/api/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ senha }),
  })
  const dados = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(dados.erro ?? "Senha incorreta")
}

export async function getResumo(): Promise<Resumo> {
  const r = await fetch("/api/resumo", { credentials: "include" })
  if (!r.ok) throw new Error(`Falha ao buscar resumo (${r.status})`)
  return r.json()
}

export async function sendChat(mensagem: string): Promise<string> {
  const r = await fetch("/api/chat", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mensagem }),
  })
  const dados = await r.json()
  if (!r.ok || dados.erro) throw new Error(dados.erro ?? `Erro (${r.status})`)
  return dados.resposta
}

export async function importarSaude(arquivo: File): Promise<string> {
  const form = new FormData()
  form.append("arquivo", arquivo, arquivo.name)
  const r = await fetch("/api/importar-saude", {
    method: "POST",
    credentials: "include",
    body: form, // sem Content-Type manual — o navegador define o boundary certo
  })
  const dados = await r.json()
  if (!r.ok || dados.erro) throw new Error(dados.erro ?? `Erro (${r.status})`)
  return dados.resumo
}

export interface MensagemHistorico {
  role: "user" | "assistant"
  content: string
}

export async function getHistorico(): Promise<MensagemHistorico[]> {
  const r = await fetch("/api/historico", { credentials: "include" })
  if (!r.ok) return []
  return (await r.json()).mensagens ?? []
}

export interface Lembrete {
  id: number
  tipo: "especifico" | "diario"
  texto: string
  datetime?: string
  hora?: string
}

export interface LembreteFixo {
  horario: string
  mensagem: string
}

export interface Lembretes {
  lembretes: Lembrete[]
  fixos: LembreteFixo[]
}

export async function getLembretes(): Promise<Lembretes> {
  const r = await fetch("/api/lembretes", { credentials: "include" })
  if (!r.ok) return { lembretes: [], fixos: [] }
  const d = await r.json()
  return { lembretes: d.lembretes ?? [], fixos: d.fixos ?? [] }
}

export async function criarLembrete(dados: {
  tipo: "especifico" | "diario"
  texto: string
  datetime?: string
  hora?: string
}): Promise<void> {
  const r = await fetch("/api/lembretes", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(dados),
  })
  const d = await r.json()
  if (!r.ok || d.erro) throw new Error(d.erro ?? `Erro (${r.status})`)
}

export async function removerLembrete(id: number): Promise<void> {
  const r = await fetch("/api/lembretes/remover", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  })
  const d = await r.json()
  if (!r.ok || d.erro) throw new Error(d.erro ?? `Erro (${r.status})`)
}
