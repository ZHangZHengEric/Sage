import { describe, expect, it } from 'vitest'

import { buildClipboardTextFromMessageContent, flattenMessageForComposerRebuild } from '../composerFromMessageFlatten.js'

describe('composerFromMessageFlatten', () => {
  it('dedupes duplicate ![](http…) lines in pasted plain text', () => {
    const u = 'https://cdn.example.com/a/b/outin_v3.jpg'
    const text = `hello\n![](${u})\n![](${u})\nbye`
    const segs = flattenMessageForComposerRebuild(text)
    const imgs = segs.filter((s) => s.kind === 'remoteImage')
    expect(imgs).toHaveLength(1)
    expect(imgs[0].url).toBe(u)
  })

  it('dedupes duplicate sage sandbox ![](…) lines (same agent + filename)', () => {
    const href =
      'file:///Users/me/.sage/agents/agent_1/upload_files/outin_v3.jpg'
    const text = `a\n![](${href})\n![](${href})`
    const segs = flattenMessageForComposerRebuild(text)
    const imgs = segs.filter((s) => s.kind === 'sageSandboxImage')
    expect(imgs).toHaveLength(1)
    expect(imgs[0].agentId).toBe('agent_1')
    expect(imgs[0].filename).toBe('outin_v3.jpg')
  })

  it('still pairs image_url block with trailing markdown ![](same URL) once', () => {
    const u = 'https://cdn.example.com/x.png'
    const content = [
      { type: 'image_url', image_url: { url: u } },
      { type: 'text', text: `\n![](${u})` }
    ]
    const segs = flattenMessageForComposerRebuild(content)
    expect(segs.filter((s) => s.kind === 'remoteImage')).toHaveLength(1)
  })

  it('parses multimodal content stored as JSON string', () => {
    const u = 'https://cdn.example.com/outin.jpg'
    const jsonStr = JSON.stringify([
      { type: 'text', text: 'hello' },
      { type: 'image_url', image_url: { url: u } }
    ])
    const segs = flattenMessageForComposerRebuild(jsonStr)
    expect(segs.filter((s) => s.kind === 'remoteImage')).toHaveLength(1)
    const clip = buildClipboardTextFromMessageContent(jsonStr)
    expect(clip).toContain('![](')
    expect(clip).toContain(u)
  })

  it('supports image_url with flat url property (no nested image_url object)', () => {
    const u = 'https://cdn.example.com/flat.png'
    const segs = flattenMessageForComposerRebuild([
      { type: 'text', text: 'x' },
      { type: 'image_url', url: u }
    ])
    expect(segs.filter((s) => s.kind === 'remoteImage')).toHaveLength(1)
  })
})
