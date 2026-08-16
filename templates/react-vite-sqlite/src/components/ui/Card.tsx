import type { ReactNode } from 'react'

export interface CardProps {
  title?: string
  children: ReactNode
  className?: string
}

/** Reusable card container primitive. */
export function Card({ title, children, className = '' }: CardProps) {
  return (
    <div
      className={`bg-white rounded-lg shadow-sm border border-slate-200 p-5 ${className}`}
    >
      {title && (
        <h2 className="text-lg font-semibold text-slate-800 mb-3">{title}</h2>
      )}
      {children}
    </div>
  )
}
