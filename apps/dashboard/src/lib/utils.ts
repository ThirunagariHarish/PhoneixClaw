/**
 * Tailwind class merger. Carried from v1.
 * Reference: ImplementationPlan.md M1.5, M1.4.
 */
import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
