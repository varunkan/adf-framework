import type { ButtonHTMLAttributes } from 'react'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger'
}

const variants: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary: 'bg-emerald-600 hover:bg-emerald-700 text-white',
  secondary: 'bg-slate-100 hover:bg-slate-200 text-slate-800',
  danger: 'bg-red-600 hover:bg-red-700 text-white',
}

/** Reusable button primitive — pass `variant` plus any native <button> prop. */
export function Button({ variant = 'primary', className = '', ...rest }: ButtonProps) {
  return (
    <button
      className={`px-4 py-2 rounded-md font-medium transition-colors disabled:opacity-50 ${variants[variant]} ${className}`}
      {...rest}
    />
  )
}
