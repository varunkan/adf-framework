import type { InputHTMLAttributes } from 'react'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
}

/** Reusable labeled input primitive — pass `label` plus any native <input> prop. */
export function Input({ label, className = '', id, ...rest }: InputProps) {
  return (
    <label className="block">
      {label && (
        <span className="block text-sm font-medium text-slate-700 mb-1">{label}</span>
      )}
      <input
        id={id}
        className={`w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-emerald-500 ${className}`}
        {...rest}
      />
    </label>
  )
}
