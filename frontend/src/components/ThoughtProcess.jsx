import React from 'react';
import { Loader2, CheckCircle2 } from 'lucide-react';

export default function ThoughtProcess({ thoughts }) {
  if (!thoughts || thoughts.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 my-2 px-4 msg-animate">
      {thoughts.map((thought, idx) => (
        <div key={idx} className="flex items-center gap-2 text-sm">
          {thought.status === 'loading' ? (
            <Loader2 className="w-4 h-4 text-teal-500 animate-spin flex-shrink-0" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-teal-600 flex-shrink-0" />
          )}
          <span
            className={`${
              thought.status === 'loading'
                ? 'text-teal-700 font-medium animate-pulse'
                : 'text-slate-500'
            }`}
          >
            {thought.text}
          </span>
        </div>
      ))}
    </div>
  );
}
