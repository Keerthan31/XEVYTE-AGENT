import React, { useState, useEffect, useCallback } from 'react'
import {
  Activity,
  ShieldCheck,
  Cpu,
  Wrench,
  Zap,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Server,
  ChevronRight,
  Search,
  Database,
  Lock,
  ShieldAlert,
  ListChecks,
  RefreshCw,
  Radar,
} from 'lucide-react'
import { fetchAuditTrail, fetchSecurityEvents } from '../api'

// The agent has exactly 3 real tools — everything below reflects that
// honestly. The "fast-path" entries are NOT separate tools; they're catalog
// endpoint_ids the agent is told to call directly (skipping search_api_catalog)
// for common actions, per the lookup table in system_prompt.md.
const LIVE_TOOLS = [
  { name: 'read_openapi_spec', desc: 'Dynamically fetches live Swagger/OpenAPI spec from Java backend', tier: 'safe' },
  { name: 'call_xevyte_api', desc: 'Generic executor for any cataloged endpoint', tier: 'confirm' },
  { name: 'search_hr_knowledge_base', desc: 'RAG over HR policy documents', tier: 'safe' },
]

const FAST_PATH_ENDPOINTS = [
  {
    category: 'Leave Management',
    endpoints: [
      { id: 'LeaveAssignmentController.getDetailedLeaveBalance', desc: 'Leave balance', tier: 'safe' },
      { id: 'LeaveController.getEmployeeLeaves', desc: 'Leave history', tier: 'safe' },
      { id: 'LeaveController.applyLeave', desc: 'Apply for leave', tier: 'confirm' },
      { id: 'LeaveController.cancelLeave', desc: 'Cancel leave', tier: 'confirm' },
      { id: 'LeaveController.takeAction', desc: 'Approve / reject leave', tier: 'confirm' },
      { id: 'LeaveController.getManagerLeaves', desc: 'Pending approvals', tier: 'safe' },
    ],
  },
  {
    category: 'Attendance',
    endpoints: [
      { id: 'AttendanceAnalyticsController.getMyAnalytics', desc: 'Attendance summary', tier: 'safe' },
      { id: 'DailyEntryController.getEmployeeEntries', desc: "Today's attendance", tier: 'safe' },
      { id: 'DailyEntryController.submitEntry', desc: 'Mark attendance', tier: 'confirm' },
    ],
  },
  {
    category: 'Helpdesk & Grievance',
    endpoints: [
      { id: 'TicketController.submitTicket', desc: 'Submit ticket', tier: 'confirm' },
      { id: 'TicketController.getMyTickets', desc: 'My tickets', tier: 'safe' },
      { id: 'GrievanceController.submitGrievance', desc: 'Raise grievance', tier: 'confirm' },
      { id: 'NotificationController.getNotifications', desc: 'Notifications', tier: 'safe' },
    ],
  },
  {
    category: 'Profile & Allocations',
    endpoints: [
      { id: 'EmployeeController.getEmployeeByEmployeeId', desc: 'My profile', tier: 'safe' },
      { id: 'AllocationController.getAllocationsForEmployee', desc: 'Project allocations', tier: 'safe' },
      { id: 'TaskCountController.getTaskCounts', desc: 'Task summary', tier: 'safe' },
      { id: 'HolidayController.getHolidaysForEmployee', desc: 'Company holidays', tier: 'safe' },
      { id: 'EmployeeController.updateEmployeePersonalDetails', desc: 'Update profile/bio', tier: 'confirm' },
      { id: 'EmployeeController.updateEmployeeBankDetails', desc: 'Update bank details', tier: 'confirm' },
      { id: 'InsuranceNomineeController.getNominees', desc: 'View nominees', tier: 'safe' },
      { id: 'InsuranceNomineeController.addNominee', desc: 'Add nominee', tier: 'confirm' },
    ],
  },
]

function TierChip({ tier }) {
  const map = {
    safe: 'chip-safe',
    confirm: 'chip-confirm',
    blocked: 'chip-blocked',
  }
  return <span className={`chip ${map[tier] || 'chip-neutral'}`}>{tier}</span>
}

export default function AgentInspector({ isOpen, onClose, thoughts = [], employeeId = '' }) {
  const [searchTerm, setSearchTerm] = useState('')
  const [activeTab, setActiveTab] = useState('registry') // 'registry' | 'telemetry' | 'security'
  const [auditEntries, setAuditEntries] = useState([])
  const [securityEvents, setSecurityEvents] = useState([])
  const [securityLoading, setSecurityLoading] = useState(false)

  const loadSecurityData = useCallback(async () => {
    setSecurityLoading(true)
    const [audit, events] = await Promise.all([
      fetchAuditTrail(employeeId, 50),
      fetchSecurityEvents(50),
    ])
    setAuditEntries(audit)
    setSecurityEvents(events)
    setSecurityLoading(false)
  }, [employeeId])

  useEffect(() => {
    if (isOpen && activeTab === 'security') {
      loadSecurityData()
    }
  }, [isOpen, activeTab, loadSecurityData])

  if (!isOpen) return null

  const totalEndpoints = FAST_PATH_ENDPOINTS.reduce((n, c) => n + c.endpoints.length, 0)

  const filteredFastPath = FAST_PATH_ENDPOINTS.map(cat => ({
    ...cat,
    endpoints: cat.endpoints.filter(
      e =>
        e.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
        e.desc.toLowerCase().includes(searchTerm.toLowerCase())
    ),
  })).filter(cat => cat.endpoints.length > 0)

  return (
    <aside className="w-[340px] border-l border-slate-200 bg-slate-50 flex flex-col h-full z-20">
      {/* Panel Header */}
      <div className="p-4 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-agent-accent/10 text-agent-accent border border-agent-accent/20">
            <Radar className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-xs font-bold text-slate-800 tracking-wide uppercase">Operations Rail</h3>
            <p className="text-[10px] text-slate-500 font-agent-mono">agent.xevyte.internal</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-slate-100 text-slate-500 hover:text-slate-700 transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* System Status Cards */}
      <div className="p-3 grid grid-cols-2 gap-2 border-b border-slate-200">
        <div className="panel rounded-xl p-2.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10px] font-semibold text-slate-500 uppercase tracking-wide">
            <span>LLM Engine</span>
            <Cpu className="w-3.5 h-3.5 text-agent-accent" />
          </div>
          <div className="mt-1.5 flex items-center gap-1.5">
            <span className="status-dot" />
            <span className="text-xs font-bold text-slate-800 font-agent-mono">gpt-4o-mini</span>
          </div>
        </div>

        <div className="panel rounded-xl p-2.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10px] font-semibold text-slate-500 uppercase tracking-wide">
            <span>Guardrails</span>
            <ShieldCheck className="w-3.5 h-3.5 text-agent-amber" />
          </div>
          <div className="mt-1.5 flex items-center gap-1.5">
            <Lock className="w-3 h-3 text-agent-amber" />
            <span className="text-xs font-bold text-slate-800">2-Layer</span>
          </div>
        </div>
      </div>

      {/* Tab Selectors */}
      <div className="flex border-b border-slate-200 text-xs font-semibold text-slate-500 px-3 pt-2">
        <button
          onClick={() => setActiveTab('registry')}
          className={`flex-1 pb-2.5 border-b-2 transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'registry' ? 'border-agent-accent text-agent-accent font-bold' : 'border-transparent hover:text-slate-700'
          }`}
        >
          <Wrench className="w-3.5 h-3.5" />
          Tools
        </button>
        <button
          onClick={() => setActiveTab('telemetry')}
          className={`flex-1 pb-2.5 border-b-2 transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'telemetry' ? 'border-agent-accent text-agent-accent font-bold' : 'border-transparent hover:text-slate-700'
          }`}
        >
          <Activity className="w-3.5 h-3.5" />
          Live
        </button>
        <button
          onClick={() => setActiveTab('security')}
          className={`flex-1 pb-2.5 border-b-2 transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'security' ? 'border-agent-accent text-agent-accent font-bold' : 'border-transparent hover:text-slate-700'
          }`}
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          Security
        </button>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {activeTab === 'registry' && (
          <>
            <div className="space-y-1.5">
              <span className="text-[11px] font-bold text-slate-600 tracking-wide uppercase">Live Tools (3)</span>
              <div className="space-y-1">
                {LIVE_TOOLS.map((tool, i) => (
                  <div key={i} className="p-2 rounded-lg panel-inset hover:border-agent-accent/25 transition-all group">
                    <div className="flex items-center justify-between gap-2">
                      <code className="text-[11px] font-agent-mono font-bold text-slate-700 group-hover:text-agent-accent truncate">
                        {tool.name}
                      </code>
                      <TierChip tier={tool.tier} />
                    </div>
                    <p className="text-[10px] text-slate-500 mt-1 leading-tight">{tool.desc}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="pt-1 pb-0.5">
              <div className="h-px bg-slate-100" />
            </div>

            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
              <input
                type="text"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                placeholder={`Search ${totalEndpoints} fast-path endpoints…`}
                className="w-full pl-8 pr-3 py-1.5 panel-inset rounded-lg text-xs text-slate-800 focus:outline-none focus:border-agent-accent transition-all placeholder:text-slate-600"
              />
            </div>
            <p className="text-[10px] text-slate-600 leading-relaxed -mt-1">
              Not separate tools — these are catalog <code className="font-agent-mono">endpoint_id</code>s the
              agent calls directly via <code className="font-agent-mono">call_xevyte_api</code>, skipping the
              search step for common actions. The remaining endpoints are reached via
              <code className="font-agent-mono"> search_api_catalog</code>.
            </p>

            {filteredFastPath.map((cat, idx) => (
              <div key={idx} className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-600 tracking-wide uppercase">{cat.category}</span>
                  <span className="text-[9px] font-agent-mono text-slate-600">{cat.endpoints.length}</span>
                </div>

                <div className="space-y-1">
                  {cat.endpoints.map((ep, eIdx) => (
                    <div key={eIdx} className="p-2 rounded-lg panel-inset hover:border-agent-accent/25 transition-all group">
                      <div className="flex items-center justify-between gap-2">
                        <code className="text-[10px] font-agent-mono font-bold text-slate-700 group-hover:text-agent-accent truncate">
                          {ep.id}
                        </code>
                        <TierChip tier={ep.tier} />
                      </div>
                      <p className="text-[10px] text-slate-500 mt-1 leading-tight">{ep.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </>
        )}

        {activeTab === 'telemetry' && (
          <div className="space-y-3">
            <div className="panel-inset rounded-xl p-3 space-y-2 font-agent-mono text-[11px]">
              <div className="flex items-center justify-between text-slate-500 border-b border-slate-200 pb-1.5">
                <span className="flex items-center gap-1.5">
                  <Server className="w-3 h-3 text-agent-accent" /> Gateway
                </span>
                <span className="text-agent-accent font-bold">ACTIVE</span>
              </div>
              <div className="flex items-center justify-between text-slate-500 border-b border-slate-200 pb-1.5">
                <span className="flex items-center gap-1.5">
                  <Database className="w-3 h-3 text-slate-600" /> Database
                </span>
                <span className="text-slate-700 font-bold">PostgreSQL</span>
              </div>
              <div className="flex items-center justify-between text-slate-500">
                <span className="flex items-center gap-1.5">
                  <Zap className="w-3 h-3 text-agent-amber" /> Cache TTL
                </span>
                <span className="text-agent-amber font-bold">30s</span>
              </div>
            </div>

            <div className="space-y-1.5">
              <h4 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Live Execution</h4>
              {thoughts && thoughts.length > 0 ? (
                thoughts.map((item, i) => (
                  <div key={i} className="p-2 rounded-lg panel-inset text-[11px] font-agent-mono leading-tight space-y-1">
                    <div className="flex items-center gap-1.5 text-agent-accent font-bold">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>{item.name || 'Agent step'}</span>
                    </div>
                    <p className="text-slate-500 text-[10px] leading-relaxed">{item.text}</p>
                  </div>
                ))
              ) : (
                <div className="p-4 text-center text-slate-600 text-xs font-medium border border-dashed border-slate-300 rounded-xl">
                  No active executions running
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'security' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Two-Layer Guardrails</h4>
              <button
                onClick={loadSecurityData}
                className="p-1 rounded-md hover:bg-slate-100 text-slate-500 hover:text-agent-accent transition-colors"
                title="Refresh"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${securityLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="panel rounded-xl p-2.5">
                <div className="flex items-center gap-1.5 text-[10px] font-semibold text-slate-500 uppercase">
                  <ShieldCheck className="w-3.5 h-3.5 text-agent-accent" /> Layer 1
                </div>
                <div className="mt-1 text-xs font-bold text-slate-800">Regex Pre-filter</div>
                <div className="text-[10px] text-slate-500">~0ms, known patterns</div>
              </div>
              <div className="panel rounded-xl p-2.5">
                <div className="flex items-center gap-1.5 text-[10px] font-semibold text-slate-500 uppercase">
                  <Cpu className="w-3.5 h-3.5 text-agent-amber" /> Layer 2
                </div>
                <div className="mt-1 text-xs font-bold text-slate-800">LLM Intent Check</div>
                <div className="text-[10px] text-slate-500">catches rephrasing</div>
              </div>
            </div>

            <div className="space-y-1.5">
              <h4 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-agent-amber" /> Blocked Attempts
              </h4>
              {securityEvents.length > 0 ? (
                securityEvents.slice(0, 15).map((ev, i) => (
                  <div key={i} className="p-2 rounded-lg bg-agent-red/5 border border-agent-red/20 text-[11px] leading-tight space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 font-bold text-agent-red">
                        <ShieldAlert className="w-3.5 h-3.5" />
                        {ev.event_type || 'blocked'}
                      </span>
                      <span className="chip chip-blocked">{ev.detection_layer}</span>
                    </div>
                    <p className="text-slate-500 text-[10px] leading-relaxed truncate font-agent-mono">{ev.matched_signal}</p>
                    <p className="text-slate-600 text-[9px]">{ev.created_at ? new Date(ev.created_at).toLocaleString() : ''}</p>
                  </div>
                ))
              ) : (
                <div className="p-4 text-center text-slate-600 text-xs font-medium border border-dashed border-slate-300 rounded-xl">
                  {securityLoading ? 'Loading…' : 'No blocked attempts recorded'}
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <h4 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider flex items-center gap-1.5">
                <ListChecks className="w-3.5 h-3.5 text-agent-accent" /> Tool Audit Trail
              </h4>
              {auditEntries.length > 0 ? (
                auditEntries.slice(0, 20).map((entry, i) => (
                  <div key={i} className="p-2 rounded-lg panel-inset text-[11px] leading-tight space-y-1.5">
                    <div className="flex items-center justify-between">
                      <code className="font-agent-mono font-bold text-slate-700 text-[11px]">{entry.tool_name}</code>
                      {entry.success ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-agent-accent" />
                      ) : (
                        <XCircle className="w-3.5 h-3.5 text-agent-red" />
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[9px]">
                      <TierChip tier={entry.risk_tier} />
                      <span className="text-slate-600 font-agent-mono">{entry.duration_ms ? `${Math.round(entry.duration_ms)}ms` : ''}</span>
                      <span className="text-slate-600 ml-auto font-agent-mono">
                        {entry.created_at ? new Date(entry.created_at).toLocaleTimeString() : ''}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="p-4 text-center text-slate-600 text-xs font-medium border border-dashed border-slate-300 rounded-xl">
                  {securityLoading ? 'Loading…' : 'No tool executions logged yet'}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer Info */}
      <div className="p-3 border-t border-slate-200 text-[10px] text-slate-600 flex items-center justify-between font-agent-mono">
        <span>xeva-agent v3.0.0</span>
        <span className="flex items-center gap-1 text-agent-accent font-bold">
          <span className="status-dot" /> Live API Spec Integration
        </span>
      </div>
    </aside>
  )
}
