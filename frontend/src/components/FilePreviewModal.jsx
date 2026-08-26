import React, { useState, useEffect } from 'react'
import { X, Download, Table, FileText, Image as ImageIcon, Search, Copy, Check, Eye } from 'lucide-react'

// Lightweight CSV parser supporting quotes, commas, newlines
function parseCSV(text) {
  if (!text) return []
  const lines = []
  let row = []
  let cell = ''
  let inQuotes = false

  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    const nextChar = text[i + 1]

    if (char === '"') {
      if (inQuotes && nextChar === '"') {
        cell += '"'
        i++
      } else {
        inQuotes = !inQuotes
      }
    } else if (char === ',' && !inQuotes) {
      row.push(cell.trim())
      cell = ''
    } else if ((char === '\r' || char === '\n') && !inQuotes) {
      if (char === '\r' && nextChar === '\n') i++
      row.push(cell.trim())
      if (row.some(c => c.length > 0)) lines.push(row)
      row = []
      cell = ''
    } else {
      cell += char
    }
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell.trim())
    if (row.some(c => c.length > 0)) lines.push(row)
  }
  return lines
}

function isHtmlContent(text) {
  if (!text || typeof text !== 'string') return false
  const t = text.trim().toLowerCase()
  return t.startsWith('<!doctype html') || t.startsWith('<html') || t.includes('<title>xeva') || t.includes('/@vite/client')
}

export default function FilePreviewModal({ isOpen, onClose, fileData }) {
  const [searchTerm, setSearchTerm] = useState('')
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(false)
  const [content, setContent] = useState('')
  const [parsedRows, setParsedRows] = useState([])

  const filename = fileData?.filename || 'Attached File'
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const isCsv = ['csv', 'txt', 'tsv'].includes(ext)
  const isPdf = ext === 'pdf'
  const isImage = ['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)

  function isTabular(name) {
    const e = name?.split('.').pop()?.toLowerCase() || ''
    return ['csv', 'tsv'].includes(e)
  }

  useEffect(() => {
    if (!isOpen || !fileData) {
      setContent('')
      setParsedRows([])
      setSearchTerm('')
      return
    }

    const loadContent = async () => {
      setLoading(true)
      try {
        if (fileData.text && !isHtmlContent(fileData.text)) {
          setContent(fileData.text)
          if (isTabular(fileData.filename)) {
            setParsedRows(parseCSV(fileData.text))
          }
        } else if (fileData.file instanceof File || fileData.file instanceof Blob) {
          if (isCsv || ['txt', 'json', 'md', 'tsv'].includes(ext)) {
            const text = await fileData.file.text()
            if (!isHtmlContent(text)) {
              setContent(text)
              if (isTabular(fileData.filename)) {
                setParsedRows(parseCSV(text))
              }
            }
          }
        } else {
          // Attempt to fetch file from server with exhaustive URL candidates
          const candidates = [
            fileData.url,
            `/downloads/${encodeURIComponent(fileData.filename)}`,
            `/downloads/${fileData.filename}`,
            `/api/agent/files/${encodeURIComponent(fileData.filename)}`,
            `/api/agent/files/${fileData.filename}`
          ].filter(Boolean)

          let textData = null

          for (const url of candidates) {
            try {
              const res = await fetch(url)
              if (res.ok) {
                const candidate = await res.text()
                if (!isHtmlContent(candidate) && candidate.trim().length > 0) {
                  textData = candidate
                  break
                }
              }
            } catch (err) {
              // Try next candidate
            }
          }

          if (textData) {
            setContent(textData)
            if (isTabular(fileData.filename)) {
              const rows = parseCSV(textData)
              setParsedRows(rows)
            }
          } else {
            setContent('')
            setParsedRows([])
          }
        }
      } catch (err) {
        console.error('Failed to read file content', err)
      } finally {
        setLoading(false)
      }
    }

    loadContent()
  }, [isOpen, fileData])

  if (!isOpen || !fileData) return null

  const fileUrl = fileData.url || (fileData.file ? URL.createObjectURL(fileData.file) : `/downloads/${encodeURIComponent(filename)}`)

  const handleDownload = () => {
    let url = fileData.url
    if (!url && fileData.file) {
      url = URL.createObjectURL(fileData.file)
    } else if (!url && content) {
      const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
      url = URL.createObjectURL(blob)
    } else if (!url) {
      url = `/downloads/${encodeURIComponent(filename)}`
    }

    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  const handleCopy = () => {
    if (!content) return
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const headers = parsedRows.length > 0 ? parsedRows[0] : []
  const dataRows = parsedRows.length > 1 ? parsedRows.slice(1) : []

  const filteredRows = dataRows.filter(row => {
    if (!searchTerm.trim()) return true
    return row.some(cell => cell.toLowerCase().includes(searchTerm.toLowerCase()))
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-5xl max-h-[88vh] flex flex-col overflow-hidden animate-scale-up">
        {/* Header */}
        <div className="p-4 px-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/70">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-xl border ${
              isCsv 
                ? 'bg-emerald-50 text-emerald-600 border-emerald-200' 
                : isPdf 
                ? 'bg-rose-50 text-rose-600 border-rose-200'
                : isImage
                ? 'bg-blue-50 text-blue-600 border-blue-200'
                : 'bg-slate-100 text-slate-700 border-slate-200'
            }`}>
              {isCsv ? <Table size={20} /> : isPdf ? <FileText size={20} /> : isImage ? <ImageIcon size={20} /> : <FileText size={20} />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-slate-800">{filename}</h3>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded font-mono uppercase ${
                  isCsv ? 'bg-emerald-100 text-emerald-700' : isPdf ? 'bg-rose-100 text-rose-700' : 'bg-slate-200 text-slate-700'
                }`}>
                  {ext.toUpperCase()}
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                {parsedRows.length > 0 ? `${dataRows.length} records • ${headers.length} columns` : 'File Preview & Inspection'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {content && (
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:text-slate-900 bg-white border border-slate-200 rounded-lg hover:border-slate-300 shadow-sm transition-all"
                title="Copy raw content"
              >
                {copied ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            )}

            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 shadow-sm transition-all"
              title="Download file to computer"
            >
              <Download size={14} />
              Download
            </button>

            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-700 rounded-lg hover:bg-slate-100 transition-colors ml-1"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Search Bar for CSV / Data */}
        {isCsv && parsedRows.length > 0 && (
          <div className="p-3 px-6 bg-slate-50/40 border-b border-slate-100 flex items-center justify-between gap-4">
            <div className="relative flex-1 max-w-md">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search within file records..."
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-agent-accent focus:ring-1 focus:ring-agent-accent/20"
              />
            </div>
            <span className="text-xs text-slate-500 font-agent-mono">
              Showing {filteredRows.length} of {dataRows.length} rows
            </span>
          </div>
        )}

        {/* Modal Body */}
        <div className="flex-1 overflow-auto p-6 bg-slate-50/20">
          {loading ? (
            <div className="h-64 flex flex-col items-center justify-center gap-2 text-slate-400">
              <div className="w-8 h-8 border-2 border-agent-accent/30 border-t-agent-accent rounded-full animate-spin" />
              <span className="text-xs font-medium">Reading file contents...</span>
            </div>
          ) : isCsv && parsedRows.length > 0 ? (
            <div className="border border-slate-200 rounded-xl overflow-hidden shadow-sm bg-white">
              <div className="overflow-x-auto max-h-[55vh]">
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="bg-slate-100 text-slate-700 font-semibold sticky top-0 border-b border-slate-200 shadow-sm">
                    <tr>
                      <th className="p-2.5 px-3 border-r border-slate-200 bg-slate-100 text-slate-400 font-mono text-[10px] w-12 text-center">#</th>
                      {headers.map((h, i) => (
                        <th key={i} className="p-2.5 px-3 border-r border-slate-200 whitespace-nowrap text-slate-700 font-bold">
                          {h || `Column ${i + 1}`}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-slate-700">
                    {filteredRows.map((row, rIdx) => (
                      <tr key={rIdx} className="hover:bg-slate-50/80 transition-colors">
                        <td className="p-2 px-3 border-r border-slate-100 text-slate-400 font-mono text-[10px] text-center bg-slate-50/40">
                          {rIdx + 1}
                        </td>
                        {headers.map((_, cIdx) => (
                          <td key={cIdx} className="p-2 px-3 border-r border-slate-100 whitespace-nowrap font-sans">
                            {row[cIdx] !== undefined && row[cIdx] !== '' ? (
                              row[cIdx]
                            ) : (
                              <span className="text-slate-300 italic font-mono text-[10px]">&mdash;</span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : isPdf ? (
            <div className="flex flex-col gap-4 w-full h-[65vh]">
              <div className="flex items-center justify-between bg-slate-50 p-2.5 px-4 rounded-xl border border-slate-200">
                <div className="flex items-center gap-2">
                  <FileText size={18} className="text-rose-500" />
                  <span className="text-xs font-semibold text-slate-700">{filename}</span>
                </div>
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-all"
                >
                  <Download size={13} /> Download PDF
                </button>
              </div>
              <iframe
                src={fileUrl}
                title={filename}
                className="w-full flex-1 rounded-xl border border-slate-200 bg-slate-100 shadow-inner"
              />
            </div>
          ) : isImage ? (
            <div className="flex items-center justify-center p-4 bg-slate-900/90 rounded-xl overflow-hidden min-h-[300px]">
              <img 
                src={fileUrl} 
                alt={filename} 
                className="max-h-[60vh] max-w-full object-contain rounded-lg shadow-lg"
                onError={(e) => {
                  e.target.onerror = null
                  e.target.src = `/api/agent/files/${encodeURIComponent(filename)}`
                }}
              />
            </div>
          ) : content ? (
            <div className="bg-slate-900 text-slate-100 p-4 rounded-xl font-mono text-xs overflow-auto max-h-[55vh] leading-relaxed shadow-inner">
              <pre>{content}</pre>
            </div>
          ) : (
            <div className="h-48 flex flex-col items-center justify-center text-slate-400">
              <p className="text-sm">No preview available for this file.</p>
              <button onClick={handleDownload} className="mt-2 text-xs text-agent-accent font-semibold hover:underline">
                Download file
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
