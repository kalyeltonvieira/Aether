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
