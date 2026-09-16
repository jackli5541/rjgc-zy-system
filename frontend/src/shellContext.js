import { inject } from 'vue'

export const shellContextKey = Symbol('shell-context')

export function useShellContext() {
  const context = inject(shellContextKey)
  if (!context) throw new Error('Shell context is unavailable')
  return context
}
