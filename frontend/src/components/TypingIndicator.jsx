import React from 'react'
import { Bot } from 'lucide-react'

export default function TypingIndicator() {
  return (
    <div className="flex items-end gap-2 msg-animate">
      <div className="w-8 h-8 rounded-full bg-white border border-[#00b3a4]/20 shadow-sm flex items-center justify-center">
        <Bot size={14} className="text-[#00b3a4]" />
      </div>
      <div className="chat-bubble-ai flex items-center gap-1.5 py-3 px-5">
        <span className="typing-dot w-2 h-2 bg-[#00b3a4] rounded-full" />
        <span className="typing-dot w-2 h-2 bg-[#00b3a4] rounded-full" />
        <span className="typing-dot w-2 h-2 bg-[#00b3a4] rounded-full" />
      </div>
    </div>
  )
}
