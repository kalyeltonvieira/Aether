import { describe, expect, it } from 'vitest'
import { parseTypedValue, displayValue } from '../features/knowledge/valueParsing'

describe('fronteira de valores tipados no browser', () => {
  it('preserva booleano, inteiro, texto e null como tipos distintos', () => {
    expect(parseTypedValue('true', 'bool')).toBe(true)
    expect(parseTypedValue('1', 'int')).toBe(1)
    expect(parseTypedValue('1', 'str')).toBe('1')
    expect(parseTypedValue('ignorado', 'null')).toBe(null)
    expect(parseTypedValue('1e3', 'float')).toBe(1000)
  })
  it('recusa prefixos numéricos, infinitos e inteiros sem precisão segura', () => {
    for (const invalid of ['1oops', '', 'Infinity', '0x10']) expect(() => parseTypedValue(invalid, 'float')).toThrow()
    expect(() => parseTypedValue('9007199254740993', 'int')).toThrow(/precisão segura/)
    expect(() => parseTypedValue('1.2', 'int')).toThrow()
    expect(() => parseTypedValue('yes', 'bool')).toThrow()
  })
  it('não arredonda inteiros no intervalo seguro e exibe signed zero', () => {
    expect(parseTypedValue('9007199254740991', 'int')).toBe(Number.MAX_SAFE_INTEGER)
    expect(displayValue(-0)).toBe('-0.0')
  })
})
