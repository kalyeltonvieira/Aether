import type { JsonScalar } from '../../types/api'

export type ValueType = 'str' | 'int' | 'float' | 'bool' | 'null'

export function parseTypedValue(raw: string, type: ValueType): JsonScalar {
  const normalized = raw.trim()
  if (type === 'int') {
    if (!/^-?\d+$/.test(normalized)) throw new Error('Informe um inteiro válido.')
    const value = Number(normalized)
    if (!Number.isSafeInteger(value)) throw new Error('Inteiro fora da precisão segura do navegador; use a API Python para inteiros maiores.')
    return value
  }
  if (type === 'float') {
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(normalized)) throw new Error('Informe um número válido.')
    const value = Number(normalized)
    if (!Number.isFinite(value)) throw new Error('Informe um número finito.')
    return value
  }
  if (type === 'bool') {
    if (normalized === 'true') return true
    if (normalized === 'false') return false
    throw new Error('Booleano deve ser true ou false.')
  }
  if (type === 'null') return null
  return raw
}

export function displayValue(value: unknown): string {
  return typeof value === 'string' ? value : Object.is(value, -0) ? '-0.0' : JSON.stringify(value)
}

export function inferredValueType(value: unknown): ValueType {
  if (value === null) return 'null'
  if (typeof value === 'boolean') return 'bool'
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float'
  return 'str'
}

export const valueTypes: { value: ValueType; label: string }[] = [
  { value: 'str', label: 'texto / str' },
  { value: 'int', label: 'inteiro / int' },
  { value: 'float', label: 'float' },
  { value: 'bool', label: 'booleano / bool' },
  { value: 'null', label: 'null' },
]

export function parseContextMap(raw: string): Record<string, string> | undefined {
  if (!raw.trim()) return undefined
  let parsed: unknown
  try { parsed = JSON.parse(raw) } catch { throw new Error('Contexto deve ser um objeto JSON válido.') }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Contexto deve ser um objeto JSON de rótulos string.')
  }
  const entries = Object.entries(parsed as Record<string, unknown>)
  if (entries.length > 32) throw new Error('Contexto pode conter no máximo 32 rótulos.')
  for (const [key, value] of entries) {
    if (!key.trim() || key.length > 64) throw new Error('Chaves de contexto devem ter de 1 a 64 caracteres.')
    if (typeof value !== 'string' || !value.trim() || value.length > 256) {
      throw new Error('Valores de contexto devem ser strings não vazias de até 256 caracteres.')
    }
  }
  return Object.fromEntries(entries.sort(([left], [right]) => left.localeCompare(right))) as Record<string, string>
}
