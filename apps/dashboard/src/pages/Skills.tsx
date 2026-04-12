/**
 * Skills page — skill catalog, agent-skill matrix, and agent configuration.
 * Tabs: Skill Catalog, Agent Configuration. Sync skills button.
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { FlexCard } from '@/components/ui/FlexCard'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { SidePanel } from '@/components/ui/SidePanel'
import { BookOpen, RefreshCw, Search, Clock, Hash, Timer } from 'lucide-react'

interface SkillData {
  id: string
  name: string
  category: string
  description: string
  usage_count?: number
  last_invoked_at?: string | null
  avg_execution_ms?: number | null
  agent_names?: string[]
}

const SKILL_CATEGORIES = ['analysis', 'data', 'execution', 'risk', 'all']

const EMPTY_AGENT_CONFIG = {
  agents_md: '',
  soul_md: '',
  tools_md: '',
}

export default function SkillsPage() {
  const [category, setCategory] = useState('all')
  const [selectedSkill, setSelectedSkill] = useState<SkillData | null>(null)
  const [syncing, setSyncing] = useState(false)
  // SKL3: Skill Search
  const [skillSearch, setSkillSearch] = useState('')

  const { data: skills = [] } = useQuery<SkillData[]>({
    queryKey: ['skills', category],
    queryFn: async () => {
      try {
        const res = await api.get(`/api/v2/skills?category=${category}`)
        return res.data ?? []
      } catch {
        return []
      }
    },
  })

  const { data: agentConfig = EMPTY_AGENT_CONFIG } = useQuery({
    queryKey: ['agent-config'],
    queryFn: async () => {
      try {
        const res = await api.get('/api/v2/skills/agent-config')
        return res.data ?? EMPTY_AGENT_CONFIG
      } catch {
        return EMPTY_AGENT_CONFIG
      }
    },
  })

  // SKL3: Filtered skills
  const filteredSkills = useMemo(() => {
    if (!skillSearch.trim()) return skills
    const q = skillSearch.toLowerCase()
    return skills.filter((s) =>
      s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q)
    )
  }, [skills, skillSearch])

  const syncSkills = async () => {
    setSyncing(true)
    try {
      await api.post('/api/v2/skills/sync')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      <PageHeader icon={BookOpen} title="Skills" description="Skill catalog and agent configuration">
        <Button variant="outline" onClick={syncSkills} disabled={syncing}>
          <RefreshCw className={`h-4 w-4 mr-2 ${syncing ? 'animate-spin' : ''}`} />
          Sync Skills
        </Button>
      </PageHeader>

      <Tabs defaultValue="catalog">
        <TabsList>
          <TabsTrigger value="catalog">Skill Catalog</TabsTrigger>
          <TabsTrigger value="config">Agent Configuration</TabsTrigger>
        </TabsList>

        <TabsContent value="catalog" className="mt-4 space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            {/* SKL3: Skill Search */}
            <div className="relative flex-1 min-w-0 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Search skills by name or description..."
                value={skillSearch}
                onChange={(e) => setSkillSearch(e.target.value)}
              />
            </div>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Category" />
              </SelectTrigger>
              <SelectContent>
                {SKILL_CATEGORIES.map((c) => (
                  <SelectItem key={c} value={c}>{c}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {Array.isArray(filteredSkills) && filteredSkills.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
              {filteredSkills.map((s) => (
                <Card key={s.id} className="cursor-pointer hover:border-primary/50 transition-all">
                  <CardContent className="p-4 space-y-2" onClick={() => setSelectedSkill(s)}>
                    <div className="flex items-start gap-2">
                      <BookOpen className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-semibold text-sm truncate">{s.name}</span>
                          <Badge variant="outline" className="text-[10px]">{s.category}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{s.description}</p>
                      </div>
                    </div>

                    {/* SKL2: Skill Detail Enrichment */}
                    <div className="flex items-center gap-3 text-[10px] text-muted-foreground pt-1 border-t border-border/50">
                      <span className="flex items-center gap-1">
                        <Hash className="h-3 w-3" />
                        {s.usage_count ?? 0} uses
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {s.last_invoked_at ? new Date(s.last_invoked_at).toLocaleDateString() : 'Never'}
                      </span>
                      <span className="flex items-center gap-1">
                        <Timer className="h-3 w-3" />
                        {s.avg_execution_ms != null ? `${s.avg_execution_ms.toFixed(0)}ms` : '--'}
                      </span>
                    </div>

                    {/* SKL1: Skill-Agent Matrix */}
                    {Array.isArray(s.agent_names) && s.agent_names.length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-1">
                        {s.agent_names.slice(0, 4).map((name) => (
                          <Badge key={name} variant="secondary" className="text-[10px]">{name}</Badge>
                        ))}
                        {s.agent_names.length > 4 && (
                          <Badge variant="secondary" className="text-[10px]">+{s.agent_names.length - 4}</Badge>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 border border-dashed border-border rounded-xl">
              <BookOpen className="h-12 w-12 text-muted-foreground/30 mb-3" />
              <p className="text-sm font-medium text-muted-foreground">
                {skillSearch ? 'No skills match your search' : 'No skills found'}
              </p>
              <p className="text-xs text-muted-foreground/60 mt-1">
                {skillSearch ? 'Try a different search term' : 'Click "Sync Skills" to discover available skills from your agents'}
              </p>
            </div>
          )}
        </TabsContent>

        <TabsContent value="config" className="mt-4 space-y-4">
          <div className="grid gap-3 sm:gap-4">
            <FlexCard title="AGENTS.md">
              <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-32 font-mono">{agentConfig.agents_md}</pre>
            </FlexCard>
            <FlexCard title="SOUL.md">
              <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-32 font-mono">{agentConfig.soul_md}</pre>
            </FlexCard>
            <FlexCard title="TOOLS.md">
              <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-32 font-mono">{agentConfig.tools_md}</pre>
            </FlexCard>
          </div>
        </TabsContent>
      </Tabs>

      <SidePanel open={!!selectedSkill} onOpenChange={() => setSelectedSkill(null)} title={selectedSkill?.name ?? ''} description={selectedSkill?.category ?? ''}>
        {selectedSkill && (
          <div className="space-y-3">
            <p className="text-sm">{selectedSkill.description}</p>
            <Badge variant="outline">{selectedSkill.category}</Badge>

            {/* SKL2: Full details in panel */}
            <div className="grid grid-cols-2 gap-2 text-sm pt-2 border-t">
              <span className="text-muted-foreground">Usage Count</span>
              <span className="font-mono">{selectedSkill.usage_count ?? 0}</span>
              <span className="text-muted-foreground">Last Invoked</span>
              <span>{selectedSkill.last_invoked_at ? new Date(selectedSkill.last_invoked_at).toLocaleString() : 'Never'}</span>
              <span className="text-muted-foreground">Avg Execution</span>
              <span className="font-mono">{selectedSkill.avg_execution_ms != null ? `${selectedSkill.avg_execution_ms.toFixed(0)}ms` : '--'}</span>
            </div>

            {/* SKL1: Agent list in panel */}
            {Array.isArray(selectedSkill.agent_names) && selectedSkill.agent_names.length > 0 && (
              <div className="pt-2 border-t space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Used by Agents</p>
                <div className="flex flex-wrap gap-1">
                  {selectedSkill.agent_names.map((name) => (
                    <Badge key={name} variant="secondary">{name}</Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </SidePanel>
    </div>
  )
}
