import React, { useState } from 'react';

export default function TicketForm({ prefill = {}, onSubmit, onCancel }) {
  const [category, setCategory] = useState(prefill.category || '');
  const [subcategory, setSubcategory] = useState(prefill.subcategory || '');
  const [issueSummary, setIssueSummary] = useState(prefill.issue_summary || '');
  const [description, setDescription] = useState(prefill.detailed_description || '');

  const categories = ['IT', 'HR', 'Admin', 'Finance', 'Facilities'];

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!category || !issueSummary || !description) return;
    onSubmit({ category, subcategory, issue_summary: issueSummary, detailed_description: description });
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden my-3 w-full max-w-sm">
      <div className="bg-slate-50 px-4 py-3 border-b border-slate-200">
        <h3 className="text-sm font-semibold text-slate-800">Raise a Ticket</h3>
        <p className="text-xs text-slate-500">Please provide the details below.</p>
      </div>
      <form onSubmit={handleSubmit} className="p-4 space-y-4">
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Category *</label>
          <select 
            value={category} 
            onChange={e => setCategory(e.target.value)}
            className="w-full text-sm border border-slate-200 rounded-lg p-2 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-[#00b3a4]/20 focus:border-[#00b3a4] outline-none transition-all"
            required
          >
            <option value="" disabled>Select category</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Type (Subcategory)</label>
          <input 
            type="text" 
            value={subcategory} 
            onChange={e => setSubcategory(e.target.value)}
            placeholder="e.g., Laptop Issue"
            className="w-full text-sm border border-slate-200 rounded-lg p-2 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-[#00b3a4]/20 focus:border-[#00b3a4] outline-none transition-all"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Subject *</label>
          <input 
            type="text" 
            value={issueSummary} 
            onChange={e => setIssueSummary(e.target.value)}
            placeholder="Short summary (max 150 chars)"
            maxLength={150}
            className="w-full text-sm border border-slate-200 rounded-lg p-2 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-[#00b3a4]/20 focus:border-[#00b3a4] outline-none transition-all"
            required
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Description *</label>
          <textarea 
            value={description} 
            onChange={e => setDescription(e.target.value)}
            placeholder="Detailed description of the issue..."
            rows={3}
            className="w-full text-sm border border-slate-200 rounded-lg p-2 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-[#00b3a4]/20 focus:border-[#00b3a4] outline-none transition-all resize-none"
            required
          />
        </div>

        <div className="flex gap-2 pt-2">
          {onCancel && (
            <button 
              type="button" 
              onClick={onCancel}
              className="flex-1 py-2 text-sm font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
            >
              Cancel
            </button>
          )}
          <button 
            type="submit" 
            className="flex-1 py-2 text-sm font-medium text-white bg-[#00b3a4] hover:bg-[#009084] rounded-lg transition-colors"
          >
            Submit Details
          </button>
        </div>
      </form>
    </div>
  );
}
