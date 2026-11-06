import type { JsonScalar, QuerySolution, ObjectType, CanonicalObjectType, ExplanationKey } from '../../types/api'
import { displayValue, inferredValueType, parseContextMap, parseTypedValue, type ValueType } from '../knowledge/valueParsing'

export interface ProofSelection {
  queryKey: { subject: string; predicate: string; object: JsonScalar }
  objectType: ValueType
  contextFilter?: Record<string, string>
}

export function valueTypeToObjectType(valueType: ValueType): CanonicalObjectType {
  return valueType === 'null' ? 'none' : valueType
}

export function objectTypeToValueType(objectType: string | null | undefined): ValueType | undefined {
  if (objectType === 'none' || objectType === 'null') return 'null'
  if (objectType === 'str' || objectType === 'int' || objectType === 'float' || objectType === 'bool') return objectType
  return undefined
}

export function proofHrefForKey(key: ExplanationKey, objectType?: ObjectType | null, contextFilter?: Record<string, string>): string {
  const [subject, predicate, object] = key
  const type = objectTypeToValueType(objectType) ?? inferredValueType(object)
  const base = `/proofs?subject=${encodeURIComponent(String(subject))}&predicate=${encodeURIComponent(predicate)}&object=${encodeURIComponent(object === null ? '' : displayValue(object))}&object_type=${encodeURIComponent(valueTypeToObjectType(type))}`
  return contextFilter && Object.keys(contextFilter).length ? `${base}&context_filter=${encodeURIComponent(JSON.stringify(contextFilter))}` : base
}

export function proofHrefForSolution(solution: Pick<QuerySolution, 'key' | 'object_type'>, contextFilter?: Record<string, string>): string {
  return proofHrefForKey(solution.key, solution.object_type, contextFilter)
}

export function parseProofSelection(params: URLSearchParams): ProofSelection | null {
  const subject = params.get('subject')
  const predicate = params.get('predicate')
  const rawObject = params.get('object')
  if (subject === null || predicate === null || rawObject === null) return null
  const objectType = objectTypeToValueType(params.get('object_type')) ?? 'str'
  const contextFilter = params.has('context_filter') ? parseContextMap(params.get('context_filter') ?? '') : undefined
  return { queryKey: { subject, predicate, object: parseTypedValue(rawObject, objectType) }, objectType, ...(contextFilter ? { contextFilter } : {}) }
}
