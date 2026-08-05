import React from 'react'
import { Calendar, Ticket, User, Bell, Briefcase, FileText, CreditCard, Shield, Sparkles } from 'lucide-react'

const ENTERPRISE_MODULES = [
  {
    title: 'Time & Leave Management',
    desc: 'Check balances, apply for leaves, view holiday lists & attendance',
    icon: Calendar,
    color: 'from-teal-500/10 to-cyan-500/10 border-teal-500/20 text-teal-700',
    iconBg: 'bg-teal-500 text-white',
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
    color: 'from-blue-500/10 to-indigo-500/10 border-blue-500/20 text-blue-700',
    iconBg: 'bg-blue-600 text-white',
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
    color: 'from-purple-500/10 to-pink-500/10 border-purple-500/20 text-purple-700',
    iconBg: 'bg-purple-600 text-white',
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
    color: 'from-amber-500/10 to-orange-500/10 border-amber-500/20 text-amber-700',
    iconBg: 'bg-amber-500 text-white',
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
          <Sparkles className="w-4 h-4 text-teal-600 animate-pulse" />
          <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
            Autonomous HRMS Capabilities
          </h3>
        </div>
        <span className="text-[10px] font-bold text-teal-700 bg-teal-50 border border-teal-200 px-2 py-0.5 rounded-full">
          24 Tools Active
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {ENTERPRISE_MODULES.map((mod, idx) => {
          const IconComponent = mod.icon
          return (
            <div 
              key={idx} 
              className={`p-4 rounded-2xl bg-gradient-to-br ${mod.color} border backdrop-blur-md shadow-sm transition-all duration-200 hover:shadow-md hover:scale-[1.01] flex flex-col justify-between space-y-3`}
            >
              <div className="flex items-start gap-3">
                <div className={`p-2.5 rounded-xl ${mod.iconBg} shadow-sm shrink-0`}>
                  <IconComponent className="w-4 h-4" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-slate-800">{mod.title}</h4>
                  <p className="text-xs text-slate-600 mt-0.5 leading-snug">{mod.desc}</p>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5 pt-1">
                {mod.prompts.map((p, pIdx) => (
                  <button
                    key={pIdx}
                    onClick={() => onSelectPrompt(p.text)}
                    className="text-[11px] font-semibold bg-white/90 hover:bg-white text-slate-700 hover:text-teal-700 border border-slate-200/80 hover:border-teal-400 px-2.5 py-1 rounded-lg transition-all shadow-2xs hover:shadow-xs"
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
