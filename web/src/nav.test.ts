import { describe, expect, it } from 'vitest'
import { NAV } from './nav'

describe('NAV', () => {
  it('defines primary navigation sections', () => {
    const paths = NAV.map((item) => item.path)
    expect(paths).toContain('talk')
    expect(paths).toContain('approvals')
    expect(paths).toContain('activity')
    expect(paths).toContain('settings')
  })
})
