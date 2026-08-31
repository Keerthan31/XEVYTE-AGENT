import React, { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bot, User, Copy, Check, Terminal, X, Loader2, Sparkles, Cpu, FileText, File, Paperclip, Table, Image as ImageIcon } from 'lucide-react'
import TicketForm from './TicketForm.jsx'
import LeaveForm from './LeaveForm.jsx'

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function renderUserContent(rawText, onOpenFile, attachment) {
  if (!rawText) return null

  // Check for attachment patterns: "📎 filename.csv" or "[Attached file: filename.csv]"
  const attachMatches = [...rawText.matchAll(/(?:📎\s*([^\n\r]+)|\[Attached file:\s*([^\]\n\r]+)\])/g)]
  
  if (attachMatches.length === 0 && !attachment) {
    return <div className="turn-user text-[13.5px] leading-relaxed whitespace-pre-wrap px-4 py-2.5 shadow-sm">{rawText}</div>
  }

  const filename = (attachment?.filename || attachMatches[0]?.[1] || attachMatches[0]?.[2] || '').trim()
  const cleanText = rawText.replace(/(?:📎\s*[^\n\r]+|\[Attached file:\s*[^\]\n\r]+\])/g, '').trim()
  const ext = filename.split('.').pop()?.toLowerCase() || ''

  const isSpreadsheet = ['csv', 'xlsx', 'xls'].includes(ext)
  const isPdf = ext === 'pdf'
  const isImage = ['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)

  return (
    <div className="flex flex-col gap-2 items-end">
      {cleanText && (
        <div className="turn-user text-[13.5px] leading-relaxed whitespace-pre-wrap px-4 py-2.5 shadow-sm">
          {cleanText}
        </div>
      )}
      <div 
        onClick={() => onOpenFile && onOpenFile(attachment || { filename })}
        className="flex items-center gap-3 p-2.5 px-3.5 rounded-xl bg-white border border-slate-200/90 shadow-sm hover:border-agent-accent hover:shadow-md transition-all max-w-sm cursor-pointer group/card"
        title="Click to open and inspect file contents"
      >
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 transition-transform group-hover/card:scale-105 ${
          isSpreadsheet 
            ? 'bg-emerald-50 text-emerald-600 border border-emerald-200' 
            : isPdf 
            ? 'bg-rose-50 text-rose-600 border border-rose-200'
            : isImage
            ? 'bg-blue-50 text-blue-600 border border-blue-200'
            : 'bg-slate-50 text-slate-600 border border-slate-200'
        }`}>
          {isSpreadsheet ? <Table size={18} /> : isPdf ? <FileText size={18} /> : isImage ? <ImageIcon size={18} /> : <File size={18} />}
        </div>
        <div className="flex flex-col min-w-0 pr-1 text-left">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-semibold text-slate-800 truncate max-w-[180px] group-hover/card:text-agent-accent transition-colors">
              {filename}
            </span>
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase font-mono ${
              isSpreadsheet 
                ? 'bg-emerald-100 text-emerald-700' 
                : isPdf 
                ? 'bg-rose-100 text-rose-700'
                : 'bg-slate-100 text-slate-700'
            }`}>
              {ext.toUpperCase()}
            </span>
          </div>
          <div className="flex items-center gap-1 mt-0.5">
            <span className="text-[10px] text-agent-accent font-semibold">Click to view & inspect</span>
          </div>
        </div>
      </div>
    </div>
  )
}

const DEFAULT_LOADING_STEPS = [
  "Analyzing your request...",
  "Searching HRMS catalog & APIs...",
  "Processing parameters & permissions...",
  "Executing requested action...",
  "Generating response..."
]

export default function MessageBubble({ 
  role, 
  content, 
  ts, 
  onSend, 
  pendingToken, 
  isLast, 
  onConfirmBtn,
  isLoading,
  thoughts,
  onOpenFile,
  attachment
}) {
  const isUser = role === 'user'
  const [copied, setCopied] = useState(false)
  const [stepIndex, setStepIndex] = useState(0)

  // Cycle through loading steps if thoughts aren't actively updating
  useEffect(() => {
    if (!content) {
      const timer = setInterval(() => {
        setStepIndex((prev) => (prev + 1) % DEFAULT_LOADING_STEPS.length)
      }, 2500)
      return () => clearInterval(timer)
    }
  }, [content])

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
        <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-white border border-agent-accent/25 text-agent-accent mt-0.5 shadow-sm">
          <User size={13} />
        </div>
        <div className="flex flex-col gap-1 items-end max-w-[85%]">
          {renderUserContent(displayContent, onOpenFile, attachment)}
          {ts && <span className="text-[10px] font-agent-mono text-slate-400 px-1">{formatTime(ts)}</span>}
        </div>
      </div>
    )
  }

  const activeThought = thoughts && thoughts.length > 0 ? thoughts[thoughts.length - 1] : null
  const currentStatusText = activeThought?.text || DEFAULT_LOADING_STEPS[stepIndex]

  return (
    <div className="flex items-start gap-3 turn-animate">
      <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-gradient-to-br from-[#00d4bd] to-[#009084] text-[#04120f] mt-0.5 shadow-[0_0_16px_rgba(0,212,189,0.25)]">
        <Bot size={13} />
      </div>

      <div className="flex flex-col gap-1 items-start max-w-[88%] flex-1 min-w-0">
        {displayContent ? (
          <div className="turn-agent text-[13.5px] leading-relaxed prose prose-invert prose-sm max-w-none relative group/bubble px-4 py-3 w-full shadow-sm">
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
                  const isApiDownload = href && (href.includes('/api/customers/') || href.includes('/api/contracts/') || href.includes('/download'));
                  
                  const handleClick = async (e) => {
                    if (isApiDownload) {
                      e.preventDefault();
                      try {
                        const token = localStorage.getItem('xeva_standalone_token') || sessionStorage.getItem('token');
                        let fetchUrl = href;
                        if (href.startsWith('http://localhost:8082')) {
                          fetchUrl = href.replace('http://localhost:8082', '');
                        }
                        const res = await fetch(fetchUrl, {
                          headers: { 'Authorization': `Bearer ${token}` }
                        });
                        if (!res.ok) throw new Error('Download failed');
                        const blob = await res.blob();
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        const disposition = res.headers.get('Content-Disposition');
                        let filename = 'download.pdf';
                        if (disposition && disposition.indexOf('filename=') !== -1) {
                            const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                            const matches = filenameRegex.exec(disposition);
                            if (matches != null && matches[1]) { 
                              filename = matches[1].replace(/['"]/g, '');
                            }
                        } else {
                            filename = Array.isArray(children) ? children.join('') : (typeof children === 'string' ? children : 'download.pdf');
                        }
                        a.download = filename;
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                        window.URL.revokeObjectURL(url);
                      } catch (err) {
                        console.error('Download error:', err);
                        window.open(href, '_blank');
                      }
                    }
                  };

                  if (isApiDownload) {
                    return <a href={href} onClick={handleClick} className="text-agent-accent underline underline-offset-2 decoration-agent-accent/40 hover:decoration-agent-accent cursor-pointer">{children}</a>
                  }

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
                    <div className="overflow-x-auto my-3 border border-slate-200 rounded-lg">
                      <table className="min-w-full text-left text-sm divide-y divide-slate-200">{children}</table>
                    </div>
                  )
                },
                thead({ children }) {
                  return <thead className="bg-slate-50">{children}</thead>
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
          /* ── INFORMATIVE AGENT WORKING / LOADING CARD ── */
          <div className="turn-agent px-4 py-3 rounded-2xl border border-agent-accent/25 bg-gradient-to-r from-teal-50/60 via-emerald-50/40 to-white shadow-sm flex flex-col gap-2.5 min-w-[280px] sm:min-w-[340px] turn-animate">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="w-5 h-5 rounded-md bg-agent-accent/15 flex items-center justify-center text-agent-accent">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                </div>
                <span className="text-xs font-semibold text-agent-accent tracking-wide font-agent-mono">
                  {currentStatusText}
                </span>
              </div>
              
              <div className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-agent-accent rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-agent-accent rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-agent-accent rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>

            {thoughts && thoughts.length > 1 && (
              <div className="pt-2 border-t border-slate-200/60 flex flex-col gap-1.5">
                {thoughts.slice(-3).map((t, idx) => (
                  <div key={idx} className="flex items-center gap-2 text-[11px] font-agent-mono">
                    {t.status === 'loading' ? (
                      <Loader2 className="w-2.5 h-2.5 text-agent-accent animate-spin flex-shrink-0" />
                    ) : (
                      <Check className="w-2.5 h-2.5 text-emerald-600 flex-shrink-0" />
                    )}
                    <span className={t.status === 'loading' ? 'text-agent-accent font-medium' : 'text-slate-500'}>
                      {t.text}
                    </span>
                  </div>
                ))}
              </div>
            )}
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
              className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-2 px-4 rounded-xl transition-colors text-sm shadow-sm cursor-pointer"
            >
              <Check size={16} /> Confirm Approval
            </button>
            <button
              onClick={() => onConfirmBtn(pendingToken, false)}
              className="flex-1 flex items-center justify-center gap-2 bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium py-2 px-4 rounded-xl transition-colors text-sm shadow-sm cursor-pointer"
            >
              <X size={16} /> Decline
            </button>
          </div>
        )}

        {ts && <span className="text-[10px] font-agent-mono text-slate-400 px-1">{formatTime(ts)}</span>}
      </div>
    </div>
  )
}

