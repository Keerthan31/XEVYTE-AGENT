import React from 'react'
import { Bot } from 'lucide-react'

export default function TypingIndicator() {
  return (
    <div className="flex items-end gap-2 turn-animate">
      <div className="w-7 h-7 rounded-lg bg-white border border-agent-accent/20 flex items-center justify-center">
        <Bot size={13} className="text-agent-accent" />
      </div>
      <div className="turn-agent flex items-center gap-1.5 py-3 px-4">
        <span className="typing-dot w-1.5 h-1.5 bg-agent-accent rounded-full" />
        <span className="typing-dot w-1.5 h-1.5 bg-agent-accent rounded-full" />
        <span className="typing-dot w-1.5 h-1.5 bg-agent-accent rounded-full" />
      </div>
    </div>
  )
}
