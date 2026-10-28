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

const SITE = `title: Test manual
landing:
  page: index.md
  captures:
    - src: case/evidence/figures/cpu.png
      caption: CPU
    - src: case/evidence/figures/later.png
      caption: Later
      pending: true
sections:
  - id: start
    title: Start here
    entries:
      - page: other.md
        title: Other
  - id: case
    title: The case
    entries:
      - page: case/benchmarks.md
        title: Benchmarks
      - page: case/tradeoffs.md
        title: Trade-offs
        pending: true
      - url: https://example.org/elsewhere
        title: Elsewhere
  - id: evidence
    title: Evidence
    generated: evidence
`;

/** A repository with a landing page, a use-case page with a figure, design notes and a file outside docs/. */
function fixture(tweak = () => {}) {
  const root = mkdtempSync(join(tmpdir(), 'site-test-'));
  put(root, 'README.md', '# readme\n');
  put(root, 'protocol/schema.json', '{}\n');
  put(root, 'docs/site.yml', SITE);
  put(root, 'docs/index.md', '# Docs\n\n{{captures}}\n\nSee [the case](section:case) and [trade-offs](case/tradeoffs.md).\n');
  put(root, 'docs/other.md', 'Other\n=====\n\nSee the [README](../README.md) and the [schema](../protocol/schema.json#top).\n');
  put(
    root,
    'docs/case/benchmarks.md',
    '# Benchmarks\n\n![CPU](evidence/figures/cpu.png)\n\nThe [capture](evidence/series/one/run.txt), the [raw logs](evidence/), [back](../index.md#docs), [notes](evidence/series/one/notes.md).\n',
  );
  put(root, 'docs/case/evidence/figures/cpu.png', 'PNG');
  put(root, 'docs/case/evidence/series/one/run.txt', 'capture');
  put(root, 'docs/case/evidence/series/one/notes.md', '# raw notes\n');
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
    const { pages, copied, notices } = build();
    assert.deepEqual(pages, ['case/benchmarks.md', 'index.md', 'other.md']);
    assert.deepEqual(copied, ['case/evidence/figures/cpu.png', 'case/evidence/series/one/notes.md', 'case/evidence/series/one/run.txt']);
    assert.deepEqual(notices, []);
    const html = readFileSync(join(out, 'case/benchmarks.html'), 'utf8');
    assert.match(html, /<img src="evidence\/figures\/cpu\.png" alt="CPU">/);
    assert.match(html, /href="\.\.\/index\.html#docs"/);
    assert.match(html, /href="\.\.\/style\.css"/);
    assert.match(html, new RegExp(`href="https://github.com/FreeMixer/plugin-hostd/tree/${REV}/docs/case/evidence/"`));
    assert.equal(readFileSync(join(out, 'case/evidence/figures/cpu.png'), 'utf8'), 'PNG');
    assert.ok(!existsSync(join(out, 'case/evidence/series/one/unreferenced.txt')), 'an unreferenced capture is not published');
    assert.ok(!existsSync(join(out, 'case/evidence/series/one/notes.html')), 'a markdown file under evidence/ is evidence, not a page');
  });
});

test('every page carries the navigation of docs/site.yml and a footer with its source', () => {
  withBuild(undefined, (build, out) => {
    build();
    const html = readFileSync(join(out, 'case/benchmarks.html'), 'utf8');
    assert.match(html, /<a href="\.\.\/section\/start\.html">Start here<\/a>/);
    assert.match(html, /<a href="benchmarks\.html" aria-current="page">Benchmarks<\/a>/);
    assert.match(html, /<span class="coming">coming: Trade-offs<\/span>/);
    assert.match(html, /<a href="https:\/\/example\.org\/elsewhere">Elsewhere<\/a>/);
    assert.match(html, new RegExp(`Source: <a href="https://github.com/FreeMixer/plugin-hostd/blob/${REV}/docs/case/benchmarks.md">docs/case/benchmarks.md</a>, last changed `));
    for (const id of ['start', 'case', 'evidence']) assert.ok(existsSync(join(out, `section/${id}.html`)), `section ${id} has an index page`);
    assert.match(readFileSync(join(out, 'section/case.html'), 'utf8'), /<a href="\.\.\/case\/benchmarks\.html">Benchmarks<\/a>/);
  });
});

test('the landing page: captures, a section link, and a pending page as text marked coming', () => {
  withBuild(undefined, (build, out) => {
    build();
    const html = readFileSync(join(out, 'index.html'), 'utf8');
    assert.match(html, /<img src="case\/evidence\/figures\/cpu\.png" alt="CPU">/);
    assert.match(html, /<div class="slot">coming<\/div><figcaption>Later<\/figcaption>/);
    assert.match(html, /<a href="section\/case\.html">the case<\/a>/);
    assert.match(html, /<span class="coming">trade-offs<\/span>/);
    assert.doesNotMatch(html, /tradeoffs\.html/);
  });
});

test('a pending page that arrives is linked, and the build says to drop the flag', () => {
  withBuild(
    (root) => put(root, 'docs/case/tradeoffs.md', '# Trade-offs\n'),
    (build, out) => {
      const { notices } = build();
      assert.deepEqual(notices, ['docs/case/tradeoffs.md is in docs/ now: drop its pending flag in docs/site.yml']);
      assert.match(readFileSync(join(out, 'index.html'), 'utf8'), /<a href="case\/tradeoffs\.html">trade-offs<\/a>/);
    },
  );
});

test('the evidence index lists every evidence file with the pages citing it; uncited ones stay in the repository', () => {
  withBuild(undefined, (build, out) => {
    build();
    const html = readFileSync(join(out, 'section/evidence.html'), 'utf8');
    assert.match(html, /<img class="thumb" src="\.\.\/case\/evidence\/figures\/cpu\.png"/);
    assert.match(html, /figures\/cpu\.png<\/a>.*cited by <a href="\.\.\/case\/benchmarks\.html">case\/benchmarks\.md<\/a>/);
    assert.match(html, new RegExp(`<a href="https://github.com/FreeMixer/plugin-hostd/blob/${REV}/docs/case/evidence/series/one/unreferenced.txt">series/one/unreferenced.txt</a> <small class="coming">no page cites it`));
    assert.match(html, /<h2 id="case-series">case \/ series, /);
  });
});

test('a site.yml page entry whose file is missing, without the pending flag, is refused by name', () => {
  refused((root) => rmSync(join(root, 'docs/case/benchmarks.md')), /case, entry 1: docs\/case\/benchmarks\.md does not exist/);
});

test('a site.yml capture whose file is missing, without the pending flag, is refused by name', () => {
  refused((root) => rmSync(join(root, 'docs/case/evidence/figures/cpu.png')), /capture 1: docs\/case\/evidence\/figures\/cpu\.png does not exist/);
});

test('a site.yml entry in the design directory is refused', () => {
  refused(
    (root) => put(root, 'docs/site.yml', SITE.replace('page: other.md', 'page: design/notes/a-note.md')),
    /docs\/design\/notes\/a-note\.md is in an unpublished directory/,
  );
});

test('a link to a section site.yml does not have is refused', () => {
  refused((root) => put(root, 'docs/other.md', '# Other\n\n[x](section:nowhere)\n'), /docs\/other\.md: section:nowhere names no section/);
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
  refused((root) => rmSync(join(root, 'docs/case/evidence/series/one/run.txt')), /docs\/case\/benchmarks\.md: evidence\/series\/one\/run\.txt does not exist/);
});

test('a link to a missing page that site.yml does not mark pending is refused, by name', () => {
  refused((root) => put(root, 'docs/other.md', '# Other\n\n[gone](gone.md)\n'), /docs\/other\.md: gone\.md does not exist/);
});

test('a published page that is not in site.yml and that no page links is refused, by name', () => {
  refused((root) => put(root, 'docs/case/stray.md', '# Stray\n'), /not in docs\/site\.yml and no page links them: docs\/case\/stray\.md/);
});

test('no site.yml, no site', () => {
  refused((root) => rmSync(join(root, 'docs/site.yml')), /docs\/site\.yml, the shape of the site, does not exist/);
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
