import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function runPnpm(args, options) {
  const pnpmPath = process.env.npm_execpath
  if (pnpmPath?.endsWith('.cjs')) {
    return execFileSync(process.execPath, [pnpmPath, ...args], options)
  }
  return execFileSync(pnpmPath || 'pnpm', args, options)
}

test('pnpm runs a dependency-free script without creating install artifacts', (context) => {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'groundwork-pnpm-readonly-'))
  context.after(() => fs.rmSync(repoRoot, { recursive: true, force: true }))

  const manifest = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'package.json'), 'utf8'))
  manifest.scripts = { probe: 'node -e "process.stdout.write(\'probe ok\\\\n\')"' }
  fs.writeFileSync(
    path.join(repoRoot, 'package.json'),
    `${JSON.stringify(manifest, null, 2)}\n`
  )
  fs.writeFileSync(
    path.join(repoRoot, 'pnpm-workspace.yaml'),
    fs.readFileSync(path.join(REPO_ROOT, 'pnpm-workspace.yaml'), 'utf8')
  )

  const output = runPnpm(['--dir', repoRoot, 'run', 'probe'], {
    encoding: 'utf8',
    env: process.env,
  })
  assert.match(output, /probe ok/)
  for (const artifact of ['pnpm-lock.yaml', 'node_modules', '.pnpm-store']) {
    assert.equal(fs.existsSync(path.join(repoRoot, artifact)), false, artifact)
  }
})
