import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bot, User, Copy, Check, Terminal, X } from 'lucide-react'
import TicketForm from './TicketForm.jsx'
import LeaveForm from './LeaveForm.jsx'

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function MessageBubble({ role, content, ts, onSend, pendingToken, isLast, onConfirmBtn }) {
  const isUser = role === 'user'
  const [copied, setCopied] = useState(false)

  let displayContent = content
  let formType = null
  let formPrefill = {}

  if (!isUser && typeof content === 'string') {
    const formMatch = content.match(/\[UI_FORM:\s*([A-Z_]+)\s*\|\s*prefill:\s*({[^\]]+})\]/)
    if (formMatch) {
      formType = formMatch[1]
      try {
        formPrefill = JSON.parse(formMatch[2])
      } catch (e) {
        console.error('Failed to parse form prefill JSON', e)
      }
      displayContent = content.replace(formMatch[0], '').trim()
    }
  }

  const handleCopy = () => {
    if (!displayContent) return
    navigator.clipboard.writeText(displayContent)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleFormSubmit = (data) => {
    if (!onSend) return
    const dataString = Object.entries(data).map(([k, v]) => `${k}: ${v}`).join(', ')
    onSend(`Here are the form details: ${dataString}`)
  }

  if (isUser) {
    return (
      <div className="flex items-start gap-3 turn-animate flex-row-reverse">
        <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-white border border-agent-accent/25 text-agent-accent mt-0.5">
          <User size={13} />
        </div>
        <div className="flex flex-col gap-1 items-end max-w-[85%]">
          <div className="turn-user text-[13.5px] leading-relaxed whitespace-pre-wrap px-4 py-2.5">
            {displayContent}
          </div>
          {ts && <span className="text-[10px] font-agent-mono text-agent-panel-raised px-1" style={{ color: 'var(--text-muted)' }}>{formatTime(ts)}</span>}
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-3 turn-animate">
      <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-gradient-to-br from-[#00d4bd] to-[#009084] text-[#04120f] mt-0.5 shadow-[0_0_16px_rgba(0,212,189,0.25)]">
        <Bot size={13} />
      </div>

      <div className="flex flex-col gap-1 items-start max-w-[88%] flex-1 min-w-0">
        {displayContent ? (
          <div className="turn-agent text-[13.5px] leading-relaxed prose prose-invert prose-sm max-w-none relative group/bubble px-4 py-3 w-full">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ className, children }) {
                  const isBlock = /language-/.test(className || '')
                  return !isBlock ? (
                    <code className="bg-agent-accent/10 px-1.5 py-0.5 rounded-md text-agent-accent text-xs font-mono">
                      {children}
                    </code>
                  ) : (
                    <pre className="bg-slate-100 border border-slate-200 rounded-xl p-3 overflow-x-auto mt-2">
                      <code className="text-xs font-mono text-slate-800">{children}</code>
                    </pre>
                  )
                },
                strong({ children }) {
                  return <strong className="text-agent-accent font-semibold">{children}</strong>
                },
                a({ children, href }) {
                  return <a href={href} target="_blank" rel="noreferrer" className="text-agent-accent underline underline-offset-2 decoration-agent-accent/40 hover:decoration-agent-accent">{children}</a>
                },
                ul({ children }) {
                  return <ul className="list-disc pl-4 my-2 space-y-1 marker:text-agent-accent/50">{children}</ul>
                },
                li({ children }) {
                  return <li className="text-slate-800">{children}</li>
                },
                p({ children }) {
                  return <p className="text-slate-800 my-1.5 first:mt-0 last:mb-0">{children}</p>
                },
                table({ children }) {
                  return (
                    <div className="overflow-x-auto my-3 border border-white/8 rounded-lg">
                      <table className="min-w-full text-left text-sm divide-y divide-white/8">{children}</table>
                    </div>
                  )
                },
                thead({ children }) {
                  return <thead className="bg-white">{children}</thead>
                },
                th({ children }) {
                  return <th className="px-4 py-2 font-semibold text-slate-800 text-xs uppercase tracking-wide">{children}</th>
                },
                td({ children }) {
                  return <td className="px-4 py-2 text-slate-700 border-t border-slate-200 text-sm">{children}</td>
                },
              }}
            >
              {displayContent}
            </ReactMarkdown>

            <button
              onClick={handleCopy}
              title="Copy response"
              className="absolute top-2 right-2 p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 hover:text-slate-800 opacity-0 group-hover/bubble:opacity-100 transition-all cursor-pointer"
            >
              {copied ? <Check size={13} className="text-agent-accent" /> : <Copy size={13} />}
            </button>
          </div>
        ) : (
          <div className="turn-agent flex items-center gap-1.5 py-3 px-4 w-fit">
            <span className="typing-dot w-1.5 h-1.5 bg-agent-accent rounded-full" />
            <span className="typing-dot w-1.5 h-1.5 bg-agent-accent rounded-full" />
            <span className="typing-dot w-1.5 h-1.5 bg-agent-accent rounded-full" />
          </div>
        )}

        {formType === 'TICKET' && <TicketForm prefill={formPrefill} onSubmit={handleFormSubmit} />}
        {formType === 'LEAVE' && <LeaveForm prefill={formPrefill} onSubmit={handleFormSubmit} />}
        {formType === 'GRIEVANCE' && (
          <div className="bg-agent-amber/10 text-agent-amber p-3 rounded-lg text-xs border border-agent-amber/25 my-2 flex items-center gap-2">
            <Terminal size={13} /> Grievance form under construction
          </div>
        )}

        {pendingToken && isLast && (
          <div className="flex items-center gap-3 mt-3 w-full border-t border-slate-200/60 pt-3">
            <button
              onClick={() => onConfirmBtn(pendingToken, true)}
              className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-2 px-4 rounded-xl transition-colors text-sm"
            >
              <Check size={16} /> Confirm Approval
            </button>
            <button
              onClick={() => onConfirmBtn(pendingToken, false)}
              className="flex-1 flex items-center justify-center gap-2 bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium py-2 px-4 rounded-xl transition-colors text-sm"
            >
              <X size={16} /> Decline
            </button>
          </div>
        )}

        {ts && <span className="text-[10px] font-agent-mono px-1" style={{ color: 'var(--text-muted)' }}>{formatTime(ts)}</span>}
      </div>
    </div>
  )
}
