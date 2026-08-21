/**
 * Run the agent decision-layer tests.
 *
 *     node scripts/run-agent-tests.mjs
 *
 * Bundles `src/lib/agentLogic.test.ts` with the esbuild that Vite already
 * depends on and executes the result, so checking three pure modules costs no
 * new dependency and no test-framework config. Exits non-zero if any check
 * fails, which is what makes it usable in CI.
 */

import { build } from 'esbuild';
import { pathToFileURL } from 'node:url';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dir = await mkdtemp(join(tmpdir(), 'orionflow-agent-tests-'));
const out = join(dir, 'tests.mjs');

try {
    const result = await build({
        entryPoints: ['src/lib/agentLogic.test.ts'],
        bundle: true,
        format: 'esm',
        platform: 'node',
        target: 'node18',
        write: false,
        logLevel: 'warning',
    });

    await writeFile(out, result.outputFiles[0].text, 'utf8');
    await import(pathToFileURL(out).href);
} finally {
    await rm(dir, { recursive: true, force: true });
}
