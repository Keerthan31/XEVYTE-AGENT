import React, { useState } from 'react'

export default function AgentAdaptiveForm({ payload, onSubmit }) {
  const [formData, setFormData] = useState({})

  const { missing_fields = [] } = payload

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit(formData)
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 bg-white border border-slate-200 rounded-xl p-4 shadow-sm w-full max-w-sm">
      <h3 className="text-sm font-semibold text-slate-800 mb-3">Please provide additional details</h3>
      
      <div className="space-y-3">
        {missing_fields.map(field => (
          <div key={field} className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-600 capitalize">
              {field.replace(/([A-Z])/g, ' $1').trim()} <span className="text-agent-red">*</span>
            </label>
            <input
              type="text"
              name={field}
              required
              className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:border-agent-accent focus:ring-1 focus:ring-agent-accent text-slate-800"
              onChange={handleChange}
              placeholder={`Enter ${field}`}
            />
          </div>
        ))}
      </div>

      <button
        type="submit"
        className="mt-4 w-full bg-agent-accent hover:bg-[#00c2ad] text-white font-medium py-2 rounded-lg transition-colors text-sm"
      >
        Submit
      </button>
    </form>
  )
}
