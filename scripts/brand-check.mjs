#!/usr/bin/env node
/**
 * Brand leak check: lists user-visible "OpenAlgo" text and links to OpenAlgo
 * properties that would reach a FastAlgo user.
 *
 * What counts: string literals, JSX text and URLs in frontend source, plus the
 * backend files that produce user-facing text (emails, bot messages, metadata).
 * What does not: comments, import specifiers, identifiers such as the
 * `openalgo` SDK, the `openalgo-charts` package, CSS classes, storage keys and
 * route names, which stay unchanged by design (UI-only rebrand).
 *
 * Intentional mentions (the AGPL attribution) are allowed per file below.
 *
 * Usage: node scripts/brand-check.mjs [--list]
 * Exit code 1 when anything is found, so it can gate a release.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

const ROOT = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

const FRONTEND_DIRS = ['frontend/src']
const FRONTEND_EXT = /\.(tsx?|jsx?)$/
const SKIP_FILE = /(\.test\.|\.spec\.|[\\/]test[\\/]|[\\/]__tests__[\\/]|[\\/]e2e[\\/])/

// Backend files whose strings reach a user (M1.7). Kept explicit on purpose:
// most backend mentions are identifiers, logger names or comments.
const BACKEND_FILES = [
  'utils/email_utils.py',
  'services/telegram_bot_service.py',
  'services/telegram_alert_service.py',
  'services/whatsapp_bot_service.py',
  'services/whatsapp_alert_service.py',
  'blueprints/mcp_oauth.py',
  'blueprints/react_app.py',
  'blueprints/telegram.py',
  'blueprints/whatsapp.py',
  'blueprints/admin.py',
  'blueprints/agent.py',
  'blueprints/health.py',
  'blueprints/auth.py',
  'services/agent/prompts.py',
  'frontend/index.html',
  'frontend/public/docs/gocharting_webhook_setup.md',
]

// Files allowed to name OpenAlgo, and why.
const ALLOW = {
  'frontend/src/brand/brand.ts': 'AGPL attribution and upstream link',
  'frontend/src/pages/About.tsx': 'AGPL attribution page',
}

const VISIBLE_NAME = /OpenAlgo/
const UPSTREAM_LINK =
  /(openalgo\.in|marketcalls\/openalgo|github\.com\/marketcalls|x\.com\/openalgo|twitter\.com\/openalgo|youtube\.com\/@openalgo|openalgo\.in\/discord)/i

function walk(dir, out) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) {
      if (name === 'node_modules' || name === 'dist') continue
      walk(full, out)
    } else if (FRONTEND_EXT.test(name) && !SKIP_FILE.test(full)) {
      out.push(full)
    }
  }
  return out
}

/** Remove comments while keeping line numbers. Good enough for source we own. */
function stripComments(src, python) {
  if (python) {
    // Docstrings: a triple-quoted string that opens a line on its own (not an
    // assignment or argument). Assigned triple-quoted text, such as bot help
    // messages, still counts.
    const noDocstrings = src.replace(/^([ \t]*)("""|''')[\s\S]*?\2/gm, (m) => m.replace(/[^\n]/g, ''))
    return noDocstrings
      .split('\n')
      .map((line) => {
        const t = line.trimStart()
        // Comments and log lines only reach log files, never a user.
        return t.startsWith('#') || /^logger\.\w+\(/.test(t) ? '' : line
      })
      .join('\n')
  }
  // Block comments, JSX comments, line comments outside strings/URLs.
  let out = src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ''))
  out = out
    .split('\n')
    .map((line) => {
      const t = line.trimStart()
      if (t.startsWith('//')) return ''
      // Trailing // comment not preceded by ':' (URLs) and not inside a quote run.
      const idx = line.search(/(?<![:'"`\w])\/\/(?!\S*['"`])/)
      return idx > 0 ? line.slice(0, idx) : line
    })
    .join('\n')
  return out
}

function isIdentifierLine(line) {
  const t = line.trim()
  return (
    /^import\s/.test(t) ||
    /from\s+['"][^'"]*['"]/.test(t) ||
    /^export\s+(type|interface)\s/.test(t) ||
    // Identifiers and type names, not text: OpenAlgoChart, OpenAlgoClient, etc.
    (!/['"`>]/.test(t.replace(/OpenAlgo[A-Z]\w*/g, '')) && /OpenAlgo[A-Z]\w*/.test(t))
  )
}

function scan(file) {
  const rel = relative(ROOT, file).split(sep).join('/')
  if (ALLOW[rel]) return []
  const python = file.endsWith('.py')
  const text = stripComments(readFileSync(file, 'utf8'), python)
  const hits = []
  text.split('\n').forEach((line, i) => {
    if (!line.trim() || isIdentifierLine(line)) return
    // Drop identifier-style occurrences (OpenAlgoChart, useOpenAlgoX) before testing.
    const visible = line.replace(/\b\w*OpenAlgo[A-Z]\w*\b/g, '').replace(/\bopenalgo[-_]\w+/g, '')
    if (VISIBLE_NAME.test(visible) || UPSTREAM_LINK.test(line)) {
      hits.push({ file: rel, line: i + 1, text: line.trim().slice(0, 140) })
    }
  })
  return hits
}

const files = FRONTEND_DIRS.flatMap((d) => walk(join(ROOT, d), []))
for (const f of BACKEND_FILES) {
  try {
    statSync(join(ROOT, f))
    files.push(join(ROOT, f))
  } catch {
    // File removed or renamed: nothing to check.
  }
}

const hits = files.flatMap(scan)
const byFile = new Map()
for (const h of hits) byFile.set(h.file, [...(byFile.get(h.file) ?? []), h])

if (process.argv.includes('--list')) {
  for (const [file, list] of byFile) {
    console.log(`\n${file} (${list.length})`)
    for (const h of list) console.log(`  ${h.line}: ${h.text}`)
  }
} else {
  for (const [file, list] of [...byFile].sort((a, b) => b[1].length - a[1].length)) {
    console.log(`${String(list.length).padStart(4)}  ${file}`)
  }
}
console.log(`\nbrand-check: ${hits.length} visible mention(s) in ${byFile.size} file(s)`)
process.exit(hits.length ? 1 : 0)
