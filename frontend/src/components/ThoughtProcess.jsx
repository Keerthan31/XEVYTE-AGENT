import React from 'react'
import { Loader2, Check, Terminal } from 'lucide-react'

export default function ThoughtProcess({ thoughts }) {
  if (!thoughts || thoughts.length === 0) return null

  return (
    <div className="flex items-start gap-3 my-1 turn-animate">
      <div className="w-7 flex-shrink-0" />
      <div className="flex flex-col gap-0 pl-1 -mt-1">
        {thoughts.map((thought, idx) => (
          <div key={idx} className="trace-line flex items-start gap-2.5 pb-3">
            <div className={`trace-node ${thought.status === 'loading' ? 'is-active' : 'is-done'}`}>
              {thought.status === 'loading' ? (
                <Loader2 className="w-3 h-3 text-agent-accent animate-spin" />
              ) : (
                <Check className="w-3 h-3 text-agent-accent" />
              )}
            </div>
            <div className="flex items-center gap-1.5 pt-0.5">
              <Terminal size={11} className="text-slate-600" />
              <span className={`text-xs font-agent-mono ${thought.status === 'loading' ? 'text-agent-accent' : 'text-slate-600'}`}>
                {thought.text}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
