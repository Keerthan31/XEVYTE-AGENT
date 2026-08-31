import React, { useState } from 'react'
import logoUrl from '../../assets/image.png'
import { Lock, Mail, ArrowRight, ShieldCheck, Eye, EyeOff, Users, Layers, Shield, ArrowLeft, CheckCircle } from 'lucide-react'

const ENCRYPTION_KEY = import.meta.env.VITE_ENCRYPTION_KEY || ""

// Web Crypto helper matching Scaloz backend AES-GCM key derivation
async function getEncryptionKey(passphrase = ENCRYPTION_KEY) {
  const encoder = new TextEncoder()
  const rawKey = encoder.encode(passphrase.substring(0, 16).padEnd(16, '0'))
  return await window.crypto.subtle.importKey(
    "raw",
    rawKey,
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"]
  )
}

// Encrypt payload before POST
async function encryptPayload(data) {
  if (!data) return data
  try {
    if (!window.crypto || !window.crypto.subtle) {
      console.warn('Web Crypto API not available. Cannot encrypt payload.')
      return null
    }
    const key = await getEncryptionKey(ENCRYPTION_KEY)
    const iv = window.crypto.getRandomValues(new Uint8Array(12))
    const encoder = new TextEncoder()
    const encodedData = encoder.encode(JSON.stringify(data))
    const ciphertextBuffer = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, encodedData)
    const combined = new Uint8Array(12 + ciphertextBuffer.byteLength)
    combined.set(iv, 0)
    combined.set(new Uint8Array(ciphertextBuffer), 12)
    let binary = ""
    for (let i = 0; i < combined.byteLength; i++) {
      binary += String.fromCharCode(combined[i])
    }
    return { payload: btoa(binary) }
  } catch (err) {
    console.error('Payload encryption failed:', err)
    return null
  }
}

// Decrypt response payload from backend
async function decryptPayload(data) {
  if (!data?.payload) return data
  try {
    if (!window.crypto || !window.crypto.subtle) {
      throw new Error('Web Crypto API is not available (you must use http://localhost:5173)')
    }
    const key = await getEncryptionKey(ENCRYPTION_KEY)
    const binaryString = atob(data.payload)
    const len = binaryString.length
    const bytes = new Uint8Array(len)
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i)
    }
    if (bytes.length <= 12) throw new Error('Payload too short for IV')
    const iv = bytes.slice(0, 12)
    const ciphertext = bytes.slice(12)
    const decryptedBuffer = await window.crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      key,
      ciphertext
    )
    const decoder = new TextDecoder()
    return JSON.parse(decoder.decode(decryptedBuffer))
  } catch (err) {
    console.error('Payload decryption failed:', err)
    return { ...data, _decryptionError: err.message }
  }
}

export default function Login({ onLoginSuccess }) {
  // View state: 'login' | 'forgot'
  const [view, setView] = useState('login')

  // Login form states
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Forgot password states
  const [forgotInput, setForgotInput] = useState('')
  const [forgotLoading, setForgotLoading] = useState(false)
  const [forgotError, setForgotError] = useState('')
  const [forgotSuccess, setForgotSuccess] = useState(false)

  // Handle Login Submit
  const handleLoginSubmit = async (e) => {
    e.preventDefault()
    if (!email.trim() || !password.trim()) {
      setError('Please enter both Employee ID/Work Email and Password.')
      return
    }

    setLoading(true)
    setError('')

    try {
      let rawInput = email.trim()
      let empId = rawInput.includes('@') ? rawInput.split('@')[0] : rawInput

      let token = ''
      let authErrorMessage = ''
      let lastErrorMsg = ''

      try {
        const rawPayload = { email: rawInput, password }
        const encryptedBody = await encryptPayload(rawPayload)

        // Try proxied endpoint with both encrypted and raw payloads
        const endpoints = [
          { url: '/api/auth/login', body: encryptedBody },
          { url: '/api/auth/login', body: rawPayload }
        ]

        for (const ep of endpoints) {
          try {
            const res = await fetch(ep.url, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(ep.body)
            })
            
            if (res) {
              const resData = await res.json().catch(() => null)
              
              if (res.ok) {
                // If it succeeds, clear any previous errors
                lastErrorMsg = ''
                
                // Handle encrypted payload response
                if (resData && resData.payload) {
                  const decrypted = await decryptPayload(resData)
                  if (decrypted && (decrypted.token || decrypted.accessToken || decrypted.jwt || decrypted.data?.token)) {
                    token = decrypted.token || decrypted.accessToken || decrypted.jwt || decrypted.data?.token
                    break
                  } else if (decrypted?._decryptionError) {
                    lastErrorMsg = `Payload received, but decryption failed: ${decrypted._decryptionError}`
                  } else {
                    lastErrorMsg = `Decryption succeeded, but token not found! Decrypted content: ${JSON.stringify(decrypted)}`
                  }
                }
                // Handle raw payload response if not already caught
                if (!token && resData && (resData.token || resData.accessToken || resData.jwt || resData.data?.token)) {
                  token = resData.token || resData.accessToken || resData.jwt || resData.data?.token
                  break
                }
                if (!token && !lastErrorMsg) {
                  lastErrorMsg = `Login succeeded at ${ep.url} but couldn't find token. Response: ` + JSON.stringify(resData)
                }
              } else {
                lastErrorMsg = `Login failed at ${ep.url} (${res.status}). Response: ` + JSON.stringify(resData)
              }
            }
          } catch (e) {
            lastErrorMsg = `Connection failed to ${ep.url}: ${e.message}`
          }
        }

      } catch (err) {
        console.warn('Backend login request error:', err)
        lastErrorMsg = err.message
      }

      if (!token) {
        setError(`Backend failed. Details: ${lastErrorMsg}`)
        setLoading(false)
        return
      }

      localStorage.setItem('xeva_standalone_token', token)
      localStorage.setItem('xeva_standalone_emp', empId)
      sessionStorage.setItem('token', token)
      sessionStorage.setItem('employeeId', empId)

      onLoginSuccess({ token, employeeId: empId, email: rawInput })
    } catch (err) {
      setError('Login encountered an unexpected error: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  // Handle Forgot Password Submit
  const handleForgotSubmit = async (e) => {
    e.preventDefault()
    if (!forgotInput.trim()) {
      setForgotError('Please enter your Employee ID or Work Email.')
      return
    }

    setForgotLoading(true)
    setForgotError('')

    try {
      const rawPayload = { employeeId: forgotInput.trim(), portal: 'tenant' }
      const encryptedBody = await encryptPayload(rawPayload)

      let response = await fetch('http://localhost:8085/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(encryptedBody)
      }).catch(() => null)

      if (!response || !response.ok) {
        response = await fetch('http://localhost:8082/api/auth/forgot-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(encryptedBody)
        }).catch(() => null)
      }

      setForgotSuccess(true)
    } catch (err) {
      setForgotError('Failed to send reset link. Please try again.')
    } finally {
      setForgotLoading(false)
    }
  }

  return (
    <div className="flex flex-col lg:flex-row min-h-screen w-screen font-sans bg-[#F4F6F8] overflow-x-hidden">

      {/* ── LEFT SIDE (Dark Navy Brand Banner matching Scaloz UI) ── */}
      <div className="w-full lg:w-1/2 bg-[#0f172a] text-white p-8 lg:p-14 flex flex-col justify-between relative overflow-hidden min-h-[480px] lg:min-h-screen">

        {/* Exact Scaloz 3D Flow Circular Graphic Illustration */}
        <div className="absolute right-[-120px] top-1/2 -translate-y-1/2 w-[580px] lg:w-[680px] pointer-events-none opacity-90 z-0">
          <img src="/scaloz-flow.png" alt="Scaloz Flow Graphic" className="w-full h-auto object-contain" />
        </div>

        {/* Top Header Logo */}
        <div className="z-10">
          <div className="flex items-center gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-white">scaloz<span className="text-cyan-400">.</span></span>
          </div>
          <p className="text-[10px] tracking-widest text-slate-400 uppercase font-semibold mt-0.5">BY XEVYTE</p>
        </div>

        {/* Main Banner Headline & Feature List */}
        <div className="z-10 max-w-lg my-auto py-8">
          <h1 className="text-3xl lg:text-4xl font-extrabold tracking-tight leading-tight mb-4">
            One Platform. <br />
            <span className="text-[#3b82f6]">
              Endless
            </span>{" "}
            Possibilities.
          </h1>
          <p className="text-sm text-slate-300 leading-relaxed mb-8">
            Scaloz unifies your people, processes, and business tools in a single secure workspace to help your organization grow smarter.
          </p>

          <div className="space-y-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-blue-500/10 border border-blue-500/30 flex items-center justify-center shrink-0 text-blue-400">
                <Users className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Empower Your Workforce</h3>
                <p className="text-xs text-slate-400 mt-0.5">Provide your teams with the tools they need to work, collaborate, and innovate anywhere.</p>
              </div>
            </div>

            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-blue-500/10 border border-blue-500/30 flex items-center justify-center shrink-0 text-blue-400">
                <Layers className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Drive Operational Excellence</h3>
                <p className="text-xs text-slate-400 mt-0.5">Automate workflows, simplify processes, and make data-driven decisions with confidence.</p>
              </div>
            </div>

            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full bg-blue-500/10 border border-blue-500/30 flex items-center justify-center shrink-0 text-blue-400">
                <Shield className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Enterprise-Grade Security</h3>
                <p className="text-xs text-slate-400 mt-0.5">Advanced security, compliance standards, and role-based access keep your data safe and secure.</p>
              </div>
            </div>
          </div>
        </div>

        <div className="z-10 text-xs text-slate-500 hidden lg:block" />
      </div>

      {/* ── RIGHT SIDE (Light Grey Container with Centered White Card) ── */}
      <div className="w-full lg:w-1/2 p-6 lg:p-12 flex flex-col justify-between items-center my-auto min-h-screen">

        {/* LOGIN VIEW */}
        {view === 'login' && (
          <div className="w-full max-w-md bg-white rounded-2xl p-8 shadow-xl border border-slate-200/80 my-auto animate-fadeIn">

            {/* Logo Badge Icon */}
            <div className="flex justify-center mb-5">
              <div className="w-14 h-14 bg-teal-600 rounded-2xl p-2.5 flex items-center justify-center shadow-md overflow-hidden">
                <img
                  src="/imp.png"
                  alt="Scaloz Logo"
                  className="w-full h-full object-contain"
                  onError={(e) => { e.target.onerror = null; e.target.src = logoUrl; }}
                />
              </div>
            </div>

            <div className="text-center mb-6">
              <h2 className="text-xl font-bold text-slate-800 tracking-tight">Workforce Intelligence Platform</h2>
              <p className="text-xs text-slate-500 mt-1">Sign in to securely access your unified workforce intelligence workspace.</p>
            </div>

            {/* Error Alert */}
            {error && (
              <div className="mb-5 p-3.5 bg-red-50 border border-red-200 rounded-xl text-red-600 text-xs flex items-center gap-2.5 shadow-sm">
                <ShieldCheck className="w-4 h-4 shrink-0 text-red-500" />
                <span className="font-medium">{error}</span>
              </div>
            )}

            <form onSubmit={handleLoginSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                  Employee ID or Work Email
                </label>
                <input
                  type="text"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Enter employee ID or email"
                  className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 focus:bg-white transition-all placeholder-slate-400"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 focus:bg-white transition-all placeholder-slate-400"
                    required
                  />
                  <button 
                    type="button" 
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>


              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 px-4 bg-teal-600 hover:bg-teal-700 text-white font-semibold rounded-xl shadow-md transition-all duration-200 flex items-center justify-center gap-2 group cursor-pointer text-sm disabled:opacity-70 mt-2"
              >
                {loading ? <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span> : <span>Log In</span>}
              </button>
            </form>

          </div>
        )}

        {/* FORGOT PASSWORD VIEW */}
        {view === 'forgot' && (
          <div className="w-full max-w-md bg-white rounded-2xl p-8 shadow-xl border border-slate-200/80 my-auto animate-fadeIn">

            {forgotSuccess ? (
              <div className="text-center py-4 space-y-5">
                <div className="w-16 h-16 bg-emerald-500 rounded-full flex items-center justify-center text-slate-800 mx-auto shadow-lg shadow-emerald-500/25">
                  <CheckCircle className="w-8 h-8" />
                </div>
                <div>
                  <h2 className="text-2xl font-bold text-slate-800">Request Received</h2>
                  <p className="text-xs text-slate-500 mt-2 leading-relaxed max-w-xs mx-auto">
                    If an account exists for this Employee ID, a password reset link has been sent to your registered work email.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => { setView('login'); setForgotSuccess(false); }}
                  className="inline-flex items-center gap-2 text-teal-600 hover:text-teal-700 font-semibold text-xs transition-colors cursor-pointer pt-2"
                >
                  <ArrowLeft className="w-4 h-4" />
                  <span>Back to Log In</span>
                </button>
              </div>
            ) : (
              <>
                <div className="text-center mb-6">
                  <h2 className="text-xl font-bold text-slate-800 tracking-tight">Forgot Password?</h2>
                  <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
                    Enter your employee ID or email and we'll send a password reset link to your registered work email.
                  </p>
                </div>

                {forgotError && (
                  <div className="mb-5 p-3.5 bg-red-50 border border-red-200 rounded-xl text-red-600 text-xs flex items-center gap-2.5 shadow-sm">
                    <ShieldCheck className="w-4 h-4 shrink-0 text-red-500" />
                    <span className="font-medium">{forgotError}</span>
                  </div>
                )}

                <form onSubmit={handleForgotSubmit} className="space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                      Employee ID or Work Email
                    </label>
                    <input
                      type="text"
                      value={forgotInput}
                      onChange={(e) => setForgotInput(e.target.value)}
                      placeholder="Enter employee ID or email"
                      className="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 focus:bg-white transition-all placeholder-slate-400"
                      required
                      autoFocus
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={forgotLoading || !forgotInput.trim()}
                    className="w-full mt-3 py-3 px-4 bg-teal-600 hover:bg-teal-700 text-white font-semibold rounded-xl shadow-md transition-all duration-200 flex items-center justify-center gap-2 group disabled:opacity-50 cursor-pointer text-sm"
                  >
                    {forgotLoading ? (
                      <span className="inline-block w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <>
                        <span>Send Reset Link</span>
                        <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                      </>
                    )}
                  </button>
                </form>

                <div className="mt-6 pt-4 border-t border-slate-100 flex justify-center">
                  <button
                    type="button"
                    onClick={() => { setView('login'); setForgotError(''); }}
                    className="inline-flex items-center gap-1.5 text-xs text-teal-600 hover:underline font-semibold cursor-pointer"
                  >
                    <ArrowLeft className="w-3.5 h-3.5" />
                    <span>Back to Log In</span>
                  </button>
                </div>
              </>
            )}

          </div>
        )}

        {/* Footer */}
        <div className="mt-6 text-center text-[11px] text-slate-600 space-y-1">
          <p>© 2026 Scaloz. Powered by Xevyte Technologies Pvt. Ltd.</p>
          <div className="flex items-center justify-center gap-3">
            <a href="#terms" className="hover:underline">Terms & Conditions</a>
            <span>|</span>
            <a href="#privacy" className="hover:underline">Privacy Policy</a>
            <span>|</span>
            <a href="#cookies" className="hover:underline">Cookies Policy</a>
          </div>
        </div>

      </div>

    </div>
  )
}
