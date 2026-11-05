import type { JsonScalar, QuerySolution, ObjectType, CanonicalObjectType, ExplanationKey } from '../../types/api'
import { displayValue, inferredValueType, parseTypedValue, type ValueType } from '../knowledge/valueParsing'

export interface ProofSelection {
  queryKey: { subject: string; predicate: string; object: JsonScalar }
  objectType: ValueType
}

export function valueTypeToObjectType(valueType: ValueType): CanonicalObjectType {
  return valueType === 'null' ? 'none' : valueType
}

export function objectTypeToValueType(objectType: string | null | undefined): ValueType | undefined {
  if (objectType === 'none' || objectType === 'null') return 'null'
  if (objectType === 'str' || objectType === 'int' || objectType === 'float' || objectType === 'bool') return objectType
  return undefined
}

export function proofHrefForKey(key: ExplanationKey, objectType?: ObjectType | null): string {
  const [subject, predicate, object] = key
  const type = objectTypeToValueType(objectType) ?? inferredValueType(object)
  return `/proofs?subject=${encodeURIComponent(String(subject))}&predicate=${encodeURIComponent(predicate)}&object=${encodeURIComponent(object === null ? '' : displayValue(object))}&object_type=${encodeURIComponent(valueTypeToObjectType(type))}`
}

export function proofHrefForSolution(solution: Pick<QuerySolution, 'key' | 'object_type'>): string {
  return proofHrefForKey(solution.key, solution.object_type)
}

export function parseProofSelection(params: URLSearchParams): ProofSelection | null {
  const subject = params.get('subject')
  const predicate = params.get('predicate')
  const rawObject = params.get('object')
  if (subject === null || predicate === null || rawObject === null) return null
  const objectType = objectTypeToValueType(params.get('object_type')) ?? 'str'
  return { queryKey: { subject, predicate, object: parseTypedValue(rawObject, objectType) }, objectType }
}
