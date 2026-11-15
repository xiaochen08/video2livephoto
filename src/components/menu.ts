export interface MenuItem {
  id: string
  label: string
  hint?: string
  danger?: boolean
  disabled?: boolean
  run: () => void
}
