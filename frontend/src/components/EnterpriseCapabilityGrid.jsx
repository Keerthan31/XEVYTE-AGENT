import React from 'react'
import { Calendar, Ticket, User, Bell, Briefcase, FileText, CreditCard, Shield, Sparkles } from 'lucide-react'

const ENTERPRISE_MODULES = [
  {
    title: 'Time & Leave Management',
    desc: 'Check balances, apply for leaves, view holiday lists & attendance',
    icon: Calendar,
    accent: 'text-agent-accent border-agent-accent/20 bg-agent-accent/10',
    prompts: [
      { label: 'Leave Balance', text: 'Show me my current leave balance' },
      { label: 'Apply Leave', text: 'I want to apply for leave' },
      { label: 'Attendance', text: 'Check my attendance status today' },
      { label: 'Holidays', text: 'What are the upcoming company holidays?' }
    ]
  },
  {
    title: 'Bank & Statutory Details',
    desc: 'View & update Bank details, IFSC, UAN, PF, ESI & Insurance Nominees',
    icon: CreditCard,
    accent: 'text-sky-400 border-sky-400/20 bg-sky-400/10',
    prompts: [
      { label: 'Update Bank Details', text: 'I want to update my bank account details' },
      { label: 'Insurance Nominees', text: 'Who are my current insurance nominees?' },
      { label: 'Add Nominee', text: 'I want to add a new insurance nominee' }
    ]
  },
  {
    title: 'Helpdesk & Grievances',
    desc: 'Submit IT tickets, track ticket status, and escalate workplace issues',
    icon: Ticket,
    accent: 'text-violet-400 border-violet-400/20 bg-violet-400/10',
    prompts: [
      { label: 'Raise IT Ticket', text: 'I want to raise an IT helpdesk ticket' },
      { label: 'My Tickets', text: 'Show my open helpdesk tickets' },
      { label: 'Raise Grievance', text: 'I want to submit a formal grievance' }
    ]
  },
  {
    title: 'Profile & Allocations',
    desc: 'Manage bio, hobbies, address info & view project allocations',
    icon: User,
    accent: 'text-agent-amber border-agent-amber/20 bg-agent-amber/10',
    prompts: [
      { label: 'My Profile', text: 'Show me my employee profile' },
      { label: 'Project Allocations', text: 'Show me what projects I am currently allocated to' },
      { label: 'Update Bio', text: 'I want to update my personal bio and hobbies' }
    ]
  }
]

export default function EnterpriseCapabilityGrid({ onSelectPrompt }) {
  return (
    <div className="space-y-4 my-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="w-3.5 h-3.5 text-agent-accent" />
          <h3 className="text-[11px] font-bold text-slate-600 uppercase tracking-wider">
            Autonomous HRMS Capabilities
          </h3>
        </div>
        <span className="chip chip-safe">Live API Integration</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {ENTERPRISE_MODULES.map((mod, idx) => {
          const IconComponent = mod.icon
          return (
            <div key={idx} className="command-tile">
              <div className="flex items-start gap-3">
                <div className={`p-2.5 rounded-xl border ${mod.accent} shrink-0`}>
                  <IconComponent className="w-4 h-4" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-slate-800">{mod.title}</h4>
                  <p className="text-xs text-slate-500 mt-0.5 leading-snug">{mod.desc}</p>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5 pt-1">
                {mod.prompts.map((p, pIdx) => (
                  <button
                    key={pIdx}
                    onClick={() => onSelectPrompt(p.text)}
                    className="text-[11px] font-semibold panel-inset hover:border-agent-accent/40 hover:text-agent-accent text-slate-600 px-2.5 py-1 rounded-lg transition-all"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
