import React, { useState } from 'react'
import { 
  Activity, 
  ShieldCheck, 
  Cpu, 
  Wrench, 
  Zap, 
  CheckCircle2, 
  Server, 
  ChevronRight,
  Search,
  Database,
  Lock
} from 'lucide-react'

const HRMS_TOOL_CATEGORIES = [
  {
    category: 'Time & Attendance',
    color: 'text-teal-600 bg-teal-50 border-teal-200',
    badge: '3 Tools',
    tools: [
      { name: 'get_attendance_summary', desc: 'Fetch monthly attendance records' },
      { name: 'check_today_attendance', desc: 'Check status for today' },
      { name: 'mark_attendance', desc: 'Clock in / clock out' }
    ]
  },
  {
    category: 'Leave Management',
    color: 'text-cyan-600 bg-cyan-50 border-cyan-200',
    badge: '5 Tools',
    tools: [
      { name: 'get_leave_balance', desc: 'Read remaining leave quotas' },
      { name: 'get_leave_history', desc: 'Fetch past leave applications' },
      { name: 'apply_leave', desc: 'Submit new leave request' },
      { name: 'cancel_leave', desc: 'Withdraw pending application' },
      { name: 'action_leave', desc: 'Approve / Reject team leaves' }
    ]
  },
  {
    category: 'Helpdesk & Grievance',
    color: 'text-blue-600 bg-blue-50 border-blue-200',
    badge: '5 Tools',
    tools: [
      { name: 'submit_ticket', desc: 'Create IT / HR support ticket' },
      { name: 'get_my_tickets', desc: 'List active helpdesk tickets' },
      { name: 'raise_grievance', desc: 'Escalate workplace issues' },
      { name: 'get_notifications', desc: 'Fetch system alerts' },
      { name: 'mark_notification_read', desc: 'Dismiss unread alerts' }
    ]
  },
  {
    category: 'Profile & Allocations',
    color: 'text-indigo-600 bg-indigo-50 border-indigo-200',
    badge: '4 Tools',
    tools: [
      { name: 'get_my_profile', desc: 'Fetch employee personal profile' },
      { name: 'get_my_allocations', desc: 'List active project allocations' },
      { name: 'get_task_summary', desc: 'Read assigned workplace tasks' },
      { name: 'get_holidays', desc: 'Fetch company holiday list' }
    ]
  },
  {
    category: 'Self-Service Updates',
    color: 'text-amber-600 bg-amber-50 border-amber-200',
    badge: '7 Tools',
    tools: [
      { name: 'update_personal_details', desc: 'Update phone & addresses' },
      { name: 'update_bank_details', desc: 'Update Bank, IFSC, UAN, PF, ESI' },
      { name: 'get_my_nominees', desc: 'List insurance nominees' },
      { name: 'add_nominee', desc: 'Add new insurance nominee' },
      { name: 'update_employee_bio', desc: 'Update bio, hobbies, job likes' },
      { name: 'get_pending_approvals', desc: 'List manager pending tasks' },
      { name: 'get_approved_leave_dates', desc: 'List team approved leaves' }
    ]
  }
]

export default function AgentInspector({ isOpen, onClose, thoughts = [] }) {
  const [searchTerm, setSearchTerm] = useState('')
  const [activeTab, setActiveTab] = useState('registry') // 'registry' | 'telemetry'

  if (!isOpen) return null

  const filteredCategories = HRMS_TOOL_CATEGORIES.map(cat => ({
    ...cat,
    tools: cat.tools.filter(t => 
      t.name.toLowerCase().includes(searchTerm.toLowerCase()) || 
      t.desc.toLowerCase().includes(searchTerm.toLowerCase())
    )
  })).filter(cat => cat.tools.length > 0)

  return (
    <aside className="w-80 border-l border-teal-500/10 bg-white/80 backdrop-blur-xl flex flex-col h-full shadow-xl transition-all duration-300 z-20">
      {/* Panel Header */}
      <div className="p-4 border-b border-teal-500/10 flex items-center justify-between bg-gradient-to-r from-teal-50/50 to-white">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-teal-500/10 text-teal-600">
            <Cpu className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-xs font-bold text-slate-800 tracking-wide uppercase">Agent Operations</h3>
            <p className="text-[10px] text-slate-500 font-medium">Real-time Telemetry & Tools</p>
          </div>
        </div>
        <button 
          onClick={onClose}
          className="p-1 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      {/* System Status Cards */}
      <div className="p-3 grid grid-cols-2 gap-2 border-b border-slate-100 bg-slate-50/40">
        <div className="p-2.5 rounded-xl bg-white border border-teal-500/15 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-semibold text-slate-500">
            <span>LLM Engine</span>
            <Cpu className="w-3.5 h-3.5 text-teal-600" />
          </div>
          <div className="mt-1 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span className="text-xs font-bold text-slate-800">GPT-4o-mini</span>
          </div>
        </div>

        <div className="p-2.5 rounded-xl bg-white border border-teal-500/15 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between text-[11px] font-semibold text-slate-500">
            <span>Guardrails</span>
            <ShieldCheck className="w-3.5 h-3.5 text-blue-600" />
          </div>
          <div className="mt-1 flex items-center gap-1.5">
            <Lock className="w-3 h-3 text-blue-500" />
            <span className="text-xs font-bold text-slate-800">PII Shield</span>
          </div>
        </div>
      </div>

      {/* Tab Selectors */}
      <div className="flex border-b border-slate-100 text-xs font-semibold text-slate-500 px-3 pt-2">
        <button
          onClick={() => setActiveTab('registry')}
          className={`flex-1 pb-2 border-b-2 transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'registry' 
              ? 'border-teal-500 text-teal-700 font-bold' 
              : 'border-transparent hover:text-slate-700'
          }`}
        >
          <Wrench className="w-3.5 h-3.5" />
          Tools (24)
        </button>
        <button
          onClick={() => setActiveTab('telemetry')}
          className={`flex-1 pb-2 border-b-2 transition-all flex items-center justify-center gap-1.5 ${
            activeTab === 'telemetry' 
              ? 'border-teal-500 text-teal-700 font-bold' 
              : 'border-transparent hover:text-slate-700'
          }`}
        >
          <Activity className="w-3.5 h-3.5" />
          Telemetry
        </button>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 custom-scrollbar">
        {activeTab === 'registry' && (
          <>
            {/* Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search 24 tools..."
                className="w-full pl-8 pr-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs focus:outline-none focus:border-teal-500 focus:bg-white transition-all placeholder:text-slate-400"
              />
            </div>

            {/* Tool Categories */}
            {filteredCategories.map((cat, idx) => (
              <div key={idx} className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-600 tracking-wide">{cat.category}</span>
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${cat.color}`}>
                    {cat.badge}
                  </span>
                </div>

                <div className="space-y-1">
                  {cat.tools.map((tool, tIdx) => (
                    <div 
                      key={tIdx} 
                      className="p-2 rounded-lg bg-slate-50/70 border border-slate-100 hover:border-teal-500/30 hover:bg-white transition-all group"
                    >
                      <div className="flex items-center justify-between">
                        <code className="text-[11px] font-mono font-bold text-slate-700 group-hover:text-teal-700">
                          {tool.name}
                        </code>
                        <Zap className="w-3 h-3 text-slate-300 group-hover:text-amber-500 transition-colors" />
                      </div>
                      <p className="text-[10px] text-slate-500 mt-0.5 leading-tight">{tool.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </>
        )}

        {activeTab === 'telemetry' && (
          <div className="space-y-3">
            <div className="p-3 rounded-xl bg-slate-900 text-white space-y-2 font-mono text-[11px]">
              <div className="flex items-center justify-between text-slate-400 border-b border-slate-800 pb-1.5">
                <span className="flex items-center gap-1.5"><Server className="w-3 h-3 text-teal-400" /> Gateway</span>
                <span className="text-teal-400 font-bold">8082 ACTIVE</span>
              </div>
              <div className="flex items-center justify-between text-slate-400 border-b border-slate-800 pb-1.5">
                <span className="flex items-center gap-1.5"><Database className="w-3 h-3 text-indigo-400" /> Database</span>
                <span className="text-indigo-400 font-bold">PostgreSQL</span>
              </div>
              <div className="flex items-center justify-between text-slate-400">
                <span className="flex items-center gap-1.5"><Zap className="w-3 h-3 text-amber-400" /> Cache TTL</span>
                <span className="text-amber-400 font-bold">30s Active</span>
              </div>
            </div>

            <div className="space-y-1.5">
              <h4 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Live Execution Logs</h4>
              {thoughts && thoughts.length > 0 ? (
                thoughts.map((item, i) => (
                  <div key={i} className="p-2 rounded-lg bg-slate-50 border border-slate-200 text-[11px] font-mono leading-tight space-y-1">
                    <div className="flex items-center gap-1.5 text-teal-700 font-bold">
                      <CheckCircle2 className="w-3.5 h-3.5 text-teal-500" />
                      <span>{item.name || 'Agent Thought'}</span>
                    </div>
                    <p className="text-slate-600 text-[10px] leading-relaxed">{item.text}</p>
                  </div>
                ))
              ) : (
                <div className="p-4 text-center text-slate-400 text-xs font-medium border border-dashed border-slate-200 rounded-xl">
                  No active executions running
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer Info */}
      <div className="p-3 border-t border-slate-100 bg-slate-50 text-[10px] text-slate-400 flex items-center justify-between font-medium">
        <span>Xevyte HRMS AI v2.6</span>
        <span className="flex items-center gap-1 text-emerald-600 font-bold">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> 24 Tools Registered
        </span>
      </div>
    </aside>
  )
}
