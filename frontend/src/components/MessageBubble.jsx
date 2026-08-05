import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bot, User, Copy, Check } from 'lucide-react'
import TicketForm from './TicketForm.jsx'
import LeaveForm from './LeaveForm.jsx'

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function MessageBubble({ role, content, ts, onSend }) {
  const isUser = role === 'user'
  const [copied, setCopied] = useState(false)

  let displayContent = content;
  let formType = null;
  let formPrefill = {};

  if (!isUser && typeof content === 'string') {
    const formMatch = content.match(/\[UI_FORM:\s*([A-Z_]+)\s*\|\s*prefill:\s*({[^\]]+})\]/);
    if (formMatch) {
      formType = formMatch[1];
      try {
        formPrefill = JSON.parse(formMatch[2]);
      } catch (e) {
        console.error("Failed to parse form prefill JSON", e);
      }
      displayContent = content.replace(formMatch[0], '').trim();
    }
  }

  const handleCopy = () => {
    if (!displayContent) return
    navigator.clipboard.writeText(displayContent)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleFormSubmit = (data) => {
    if (!onSend) return;
    const dataString = Object.entries(data)
      .map(([k, v]) => `${k}: ${v}`)
      .join(', ');
    onSend(`Here are the form details: ${dataString}`);
  };

  return (
    <div className={`flex items-end gap-2.5 msg-animate group ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center shadow-sm
        ${isUser
          ? 'bg-gradient-to-br from-[#00c4b4] to-[#009084] text-white shadow-[#00b3a4]/30'
          : 'bg-white border border-[#00b3a4]/20 text-[#00b3a4]'}`}
      >
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>

      {/* Bubble + timestamp */}
      <div className={`flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'}`}>
        {isUser ? (
          <div className="chat-bubble-user text-sm leading-relaxed whitespace-pre-wrap">
            {displayContent}
          </div>
        ) : (
          <div className="flex flex-col w-full max-w-full relative">
            {displayContent ? (
              <div className="chat-bubble-ai text-sm leading-relaxed prose prose-sm max-w-none text-slate-800 relative group/bubble">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    code({ className, children }) {
                      const isBlock = /language-/.test(className || '')
                      return !isBlock
                        ? <code className="bg-[#00b3a4]/10 px-1.5 py-0.5 rounded-md text-[#00b3a4] text-xs font-mono">{children}</code>
                        : <pre className="bg-slate-50 border border-slate-100 rounded-xl p-3 overflow-x-auto mt-2">
                            <code className="text-xs font-mono text-slate-700">{children}</code>
                          </pre>
                    },
                    strong({ children }) {
                      return <strong className="text-[#00b3a4] font-semibold">{children}</strong>
                    },
                    ul({ children }) {
                      return <ul className="list-disc pl-4 my-2 space-y-1">{children}</ul>
                    },
                    li({ children }) {
                      return <li className="text-slate-700">{children}</li>
                    },
                    table({ children }) {
                      return (
                        <div className="overflow-x-auto my-3 border border-slate-200 rounded-lg">
                          <table className="min-w-full text-left text-sm divide-y divide-slate-200">
                            {children}
                          </table>
                        </div>
                      )
                    },
                    thead({ children }) {
                      return <thead className="bg-slate-50">{children}</thead>
                    },
                    th({ children }) {
                      return <th className="px-4 py-2 font-semibold text-slate-700">{children}</th>
                    },
                    td({ children }) {
                      return <td className="px-4 py-2 text-slate-600 border-t border-slate-100">{children}</td>
                    }
                  }}
                >
                  {displayContent}
                </ReactMarkdown>

                {/* Copy Button */}
                <button
                  onClick={handleCopy}
                  title="Copy response"
                  className="absolute top-2 right-2 p-1.5 rounded-lg bg-slate-100/80 hover:bg-slate-200 text-slate-500 hover:text-slate-700 opacity-0 group-hover/bubble:opacity-100 transition-all cursor-pointer"
                >
                  {copied ? <Check size={13} className="text-emerald-600" /> : <Copy size={13} />}
                </button>
              </div>
            ) : (
              <div className="chat-bubble-ai flex items-center gap-1.5 py-3 px-5 w-fit">
                <span className="typing-dot w-2 h-2 bg-[#00b3a4] rounded-full" />
                <span className="typing-dot w-2 h-2 bg-[#00b3a4] rounded-full" />
                <span className="typing-dot w-2 h-2 bg-[#00b3a4] rounded-full" />
              </div>
            )}
            
            {formType === 'TICKET' && (
              <TicketForm prefill={formPrefill} onSubmit={handleFormSubmit} />
            )}
            {formType === 'LEAVE' && (
              <LeaveForm prefill={formPrefill} onSubmit={handleFormSubmit} />
            )}
            {formType === 'GRIEVANCE' && (
              <div className="bg-yellow-50 text-yellow-800 p-3 rounded-lg text-xs border border-yellow-200 my-2">
                [Grievance Form Under Construction]
              </div>
            )}
          </div>
        )}

        {ts && (
          <div className="flex items-center gap-2 px-1">
            <span className="text-[10px] text-slate-400">{formatTime(ts)}</span>
          </div>
        )}
      </div>
    </div>
  )
}
