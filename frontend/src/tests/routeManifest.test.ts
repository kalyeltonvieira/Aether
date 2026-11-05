import { describe, expect, it } from 'vitest'
import manifest from '../../public/manus-routes.json'

describe('route manifest', () => {
  it('declares every requested page route and no API paths', () => {
    const paths = manifest.routes.map((route) => route.path)
    expect(paths).toEqual(['/', '/knowledge', '/graph', '/reasoning', '/proofs', '/memory', '/events', '/performance', '/settings'])
    expect(paths.some((path) => path.startsWith('/api'))).toBe(false)
  })
})
