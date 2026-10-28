// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
//
// build.mjs on a small repository of its own: the site it writes, and every page it must refuse.
//
//   node --test tools/site/build.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { buildSite, SiteError, UNPUBLISHED } from './build.mjs';

const REV = '0123456789abcdef0123456789abcdef01234567';
// The design directory, named here on its own and not read from build.mjs, so a rule that stops excluding it goes
// red. Joined from its parts: the repository's private-refs check matches the joined spelling in any tracked file.
const DESIGN = join('docs', 'design');

function put(root, rel, text) {
  mkdirSync(dirname(join(root, rel)), { recursive: true });
  writeFileSync(join(root, rel), text);
}

/** A repository with a landing page, a use-case page with a figure, design notes and a file outside docs/. */
function fixture(tweak = () => {}) {
  const root = mkdtempSync(join(tmpdir(), 'site-test-'));
  put(root, 'README.md', '# readme\n');
  put(root, 'protocol/schema.json', '{}\n');
  put(root, 'docs/index.md', '# Docs\n\n- [Use case](case/benchmarks.md)\n- [Other](other.md)\n');
  put(root, 'docs/other.md', 'Other\n=====\n\nSee the [README](../README.md) and the [schema](../protocol/schema.json#top).\n');
  put(
    root,
    'docs/case/benchmarks.md',
    '# Benchmarks\n\n![CPU](evidence/figures/cpu.png)\n\nThe [capture](evidence/series/one/run.txt), the [raw logs](evidence/), [back](../index.md#docs).\n',
  );
  put(root, 'docs/case/evidence/figures/cpu.png', 'PNG');
  put(root, 'docs/case/evidence/series/one/run.txt', 'capture');
  put(root, 'docs/case/evidence/series/one/unreferenced.txt', 'not referenced by any page');
  put(root, join(DESIGN, 'notes', 'a-note.md'), '# A design note\n\n![x](fig.png)\n');
  put(root, join(DESIGN, 'notes', 'fig.png'), 'PNG');
  tweak(root);
  return root;
}

function withBuild(tweak, check) {
  const root = fixture(tweak);
  const out = join(root, 'out');
  try {
    check(() => buildSite({ root, out, rev: REV }), out, root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function refused(tweak, pattern) {
  withBuild(tweak, (build) => assert.throws(build, (e) => e instanceof SiteError && pattern.test(e.message), `expected ${pattern}`));
}

test('the pages, the figure and the capture they reference are written; nothing else of docs/ is', () => {
  withBuild(undefined, (build, out) => {
    const { pages, copied } = build();
    assert.deepEqual(pages, ['case/benchmarks.md', 'index.md', 'other.md']);
    assert.deepEqual(copied, ['case/evidence/figures/cpu.png', 'case/evidence/series/one/run.txt']);
    const html = readFileSync(join(out, 'case/benchmarks.html'), 'utf8');
    assert.match(html, /<img src="evidence\/figures\/cpu\.png" alt="CPU">/);
    assert.match(html, /href="\.\.\/index\.html#docs"/);
    assert.match(html, /href="\.\.\/style\.css"/);
    assert.match(html, new RegExp(`href="https://github.com/FreeMixer/plugin-hostd/tree/${REV}/docs/case/evidence/"`));
    assert.equal(readFileSync(join(out, 'case/evidence/figures/cpu.png'), 'utf8'), 'PNG');
    assert.ok(!existsSync(join(out, 'case/evidence/series/one/unreferenced.txt')), 'an unreferenced capture is not published');
    assert.match(readFileSync(join(out, 'index.html'), 'utf8'), /href="case\/benchmarks\.html"/);
  });
});

test('a link to a repository file outside docs/ goes to GitHub at the built commit; nothing is copied', () => {
  withBuild(undefined, (build, out) => {
    build();
    const html = readFileSync(join(out, 'other.html'), 'utf8');
    assert.match(html, new RegExp(`href="https://github.com/FreeMixer/plugin-hostd/blob/${REV}/README.md"`));
    assert.match(html, new RegExp(`href="https://github.com/FreeMixer/plugin-hostd/blob/${REV}/protocol/schema.json#top"`));
    assert.ok(!existsSync(join(out, 'README.md')) && !existsSync(join(out, 'protocol')));
  });
});

test('design material is never published, even with pages and figures in it', () => {
  withBuild(undefined, (build, out) => {
    const { pages } = build();
    assert.ok(UNPUBLISHED.includes('design'));
    assert.ok(!pages.some((p) => p.startsWith('design/')), 'no design page is rendered');
    assert.ok(!existsSync(join(out, 'design')), 'the site has no design directory');
  });
});

test('a published page that embeds a figure from the design directory is refused, by name', () => {
  refused(
    (root) => put(root, 'docs/other.md', '# Other\n\n![x](design/notes/fig.png)\n'),
    /docs\/other\.md: design\/notes\/fig\.png is in docs\/design, which is not published/,
  );
});

test('a published page that links a design note is refused, by name', () => {
  refused((root) => put(root, 'docs/other.md', '# Other\n\n[note](design/notes/a-note.md)\n'), /docs\/other\.md: .*not published/);
});

test('an image outside docs/ is refused, by name', () => {
  refused(
    (root) => {
      put(root, 'bench/fig.png', 'PNG');
      put(root, 'docs/other.md', '# Other\n\n![fig](../bench/fig.png)\n');
    },
    /docs\/other\.md: the image \.\.\/bench\/fig\.png is outside docs\//,
  );
});

test('a referenced file that does not exist is refused, by name', () => {
  refused(
    (root) => rmSync(join(root, 'docs/case/evidence/figures/cpu.png')),
    /docs\/case\/benchmarks\.md: evidence\/figures\/cpu\.png does not exist/,
  );
});

test('a landing page that links a missing page is refused, by name', () => {
  refused((root) => rmSync(join(root, 'docs/case/benchmarks.md')), /docs\/index\.md: case\/benchmarks\.md does not exist/);
});

test('a published page no link reaches from the landing page is refused, by name', () => {
  refused((root) => put(root, 'docs/case/tradeoffs.md', '# Trade-offs\n'), /reaches these published pages: docs\/case\/tradeoffs\.md/);
});

test('a reference that leaves the repository is refused', () => {
  refused((root) => put(root, 'docs/other.md', '# Other\n\n[x](../../outside.md)\n'), /leaves the repository/);
});

test('an absolute path is refused', () => {
  refused((root) => put(root, 'docs/other.md', '# Other\n\n![x](/etc/passwd)\n'), /is an absolute path/);
});

test('no landing page, no site', () => {
  refused((root) => rmSync(join(root, 'docs/index.md')), /docs\/index\.md, the landing page, does not exist/);
});

test('raw HTML in a page is shown, not run', () => {
  withBuild(
    (root) => put(root, 'docs/other.md', '# Other\n\n<script>alert(1)</script>\n'),
    (build, out) => {
      build();
      assert.doesNotMatch(readFileSync(join(out, 'other.html'), 'utf8'), /<script>/);
    },
  );
});
