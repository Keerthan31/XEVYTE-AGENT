import React from 'react'
import { User, CreditCard, Shield, Briefcase, Heart, MapPin, Phone, Mail, Award, CheckCircle2 } from 'lucide-react'

export function ProfileCard({ data }) {
  if (!data) return null
  return (
    <div className="my-3 p-4 rounded-2xl bg-gradient-to-r from-teal-500/10 via-white to-cyan-500/10 border border-teal-500/20 shadow-sm space-y-3">
      <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-teal-600 text-slate-800 flex items-center justify-center font-bold text-sm shadow-sm">
            {data.firstName ? data.firstName[0] : 'E'}
          </div>
          <div>
            <h4 className="text-sm font-bold text-slate-800">{data.firstName} {data.lastName}</h4>
            <p className="text-xs text-slate-500 font-mono">{data.employeeId} • {data.role || 'Employee'}</p>
          </div>
        </div>
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
          ACTIVE
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="p-2 rounded-lg bg-slate-50 border border-slate-100 flex items-center gap-2">
          <Mail className="w-3.5 h-3.5 text-teal-600 shrink-0" />
          <span className="truncate text-slate-700 font-medium">{data.email || 'N/A'}</span>
        </div>
        <div className="p-2 rounded-lg bg-slate-50 border border-slate-100 flex items-center gap-2">
          <Phone className="w-3.5 h-3.5 text-teal-600 shrink-0" />
          <span className="truncate text-slate-700 font-medium">{data.contactNo || 'N/A'}</span>
        </div>
        <div className="p-2 rounded-lg bg-slate-50 border border-slate-100 flex items-center gap-2">
          <Briefcase className="w-3.5 h-3.5 text-indigo-600 shrink-0" />
          <span className="truncate text-slate-700 font-medium">{data.department || 'General'}</span>
        </div>
        <div className="p-2 rounded-lg bg-slate-50 border border-slate-100 flex items-center gap-2">
          <MapPin className="w-3.5 h-3.5 text-amber-600 shrink-0" />
          <span className="truncate text-slate-700 font-medium">{data.workLocation || 'Office'}</span>
        </div>
      </div>
    </div>
  )
}

export function BankDetailsCard({ data }) {
  if (!data) return null
  return (
    <div className="my-3 p-4 rounded-2xl bg-gradient-to-r from-blue-500/10 via-white to-indigo-500/10 border border-blue-500/20 shadow-sm space-y-3">
      <div className="flex items-center justify-between border-b border-slate-100 pb-2">
        <div className="flex items-center gap-2 text-blue-700 font-bold text-xs uppercase tracking-wide">
          <CreditCard className="w-4 h-4" /> Bank & Statutory Details
        </div>
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
          Verified
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
          <span className="text-[10px] text-slate-600 font-semibold uppercase block">Bank Name</span>
          <span className="font-bold text-slate-800">{data.bankName || 'N/A'}</span>
        </div>
        <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
          <span className="text-[10px] text-slate-600 font-semibold uppercase block">Account Number</span>
          <span className="font-bold font-mono text-slate-800">{data.bankAccountNumber || 'N/A'}</span>
        </div>
        <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
          <span className="text-[10px] text-slate-600 font-semibold uppercase block">IFSC Code</span>
          <span className="font-bold font-mono text-slate-800">{data.bankIfscCode || 'N/A'}</span>
        </div>
        <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
          <span className="text-[10px] text-slate-600 font-semibold uppercase block">UAN Number</span>
          <span className="font-bold font-mono text-slate-800">{data.uanNumber || 'N/A'}</span>
        </div>
      </div>
    </div>
  )
}

export function NomineeCard({ nominees }) {
  if (!nominees || !Array.isArray(nominees) || nominees.length === 0) return null
  return (
    <div className="my-3 p-4 rounded-2xl bg-gradient-to-r from-purple-500/10 via-white to-pink-500/10 border border-purple-500/20 shadow-sm space-y-2">
      <div className="flex items-center gap-2 text-purple-700 font-bold text-xs uppercase tracking-wide border-b border-slate-100 pb-2">
        <Shield className="w-4 h-4" /> Insurance Nominees ({nominees.length})
      </div>
      <div className="space-y-2">
        {nominees.map((n, i) => (
          <div key={i} className="p-2.5 rounded-xl bg-slate-50 border border-slate-200/80 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2.5">
              <Heart className="w-4 h-4 text-purple-500 shrink-0" />
              <div>
                <span className="font-bold text-slate-800">{n.nomineeName}</span>
                <span className="text-[10px] text-slate-500 block font-medium">Relationship: {n.relationship}</span>
              </div>
            </div>
            {n.dateOfBirth && (
              <span className="text-[10px] font-mono font-bold bg-white px-2 py-1 rounded-md border border-slate-200 text-slate-600">
                DOB: {n.dateOfBirth}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
