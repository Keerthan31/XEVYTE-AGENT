import React, { useState } from 'react';

export default function LeaveForm({ prefill = {}, onSubmit, onCancel }) {
  const [type, setType] = useState(prefill.type || '');
  const [startDate, setStartDate] = useState(prefill.start_date || '');
  const [endDate, setEndDate] = useState(prefill.end_date || '');
  const [reason, setReason] = useState(prefill.reason || '');

  const leaveTypes = ['Casual Leave', 'Sick Leave', 'Earned Leave', 'Optional Leave', 'Compensatory Off', 'Loss of Pay'];

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!type || !startDate || !endDate || !reason) return;
    onSubmit({ type, start_date: startDate, end_date: endDate, reason });
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden my-3 w-full max-w-sm">
      <div className="bg-slate-50 px-4 py-3 border-b border-slate-200">
        <h3 className="text-sm font-semibold text-slate-800">Apply for Leave</h3>
        <p className="text-xs text-slate-500">Please provide the details below.</p>
      </div>
      <form onSubmit={handleSubmit} className="p-4 space-y-4">
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Leave Type *</label>
          <select 
            value={type} 
            onChange={e => setType(e.target.value)}
            className="w-full text-sm border border-slate-200 rounded-lg p-2 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-[#00b3a4]/20 focus:border-[#00b3a4] outline-none transition-all"
            required
          >
            <option value="" disabled>Select leave type</option>
            {leaveTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Start Date *</label>
            <input 
              type="date" 
              value={startDate} 
              onChange={e => setStartDate(e.target.value)}
              className="w-full text-sm border border-slate-200 rounded-lg p-2 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-[#00b3a4]/20 focus:border-[#00b3a4] outline-none transition-all"
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">End Date *</label>
            <input 
              type="date" 
              value={endDate} 
              onChange={e => setEndDate(e.target.value)}
              className="w-full text-sm border border-slate-200 rounded-lg p-2 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-[#00b3a4]/20 focus:border-[#00b3a4] outline-none transition-all"
              required
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Reason *</label>
          <textarea 
            value={reason} 
            onChange={e => setReason(e.target.value)}
            placeholder="Reason for leave..."
            rows={2}
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
