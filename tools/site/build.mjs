#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
//
// build.mjs: renders the repository's docs/**/*.md into a static site, the one GitHub Pages serves
// (.github/workflows/pages.yml).
//
//   node tools/site/build.mjs [--src <repository root>] [--out <dir>]
//
// Defaults: the repository this file sits in, and build/site under it. The output is self-contained and every link
// in it is relative, so the same tree reads the same under any prefix it is served from.
//
// WHAT IS PUBLISHED. Every markdown page under docs/ except the directories UNPUBLISHED names (design material:
// it stays in the repository and never reaches the site). docs/index.md is the landing page, and every other
// published page must be reachable from it by links: a page nobody can reach from the landing page fails the build
// by name.
//
// WHAT A PAGE MAY POINT AT, checked page by page; every refusal names the page and the target:
//   - another published page: rendered as a link to its .html;
//   - any other file under docs/ (a figure, a capture, a data file): copied into the site beside the pages, and only
//     when a published page references it, so nothing under docs/ is published that no page points at;
//   - a directory under docs/, by a LINK: the link goes to its listing in the repository on GitHub;
//   - a file of the repository outside docs/, by a LINK: the link goes to that file in the repository on GitHub, at
//     the commit the site was built from; nothing outside docs/ is copied;
//   - REFUSED: an image outside docs/, anything in an unpublished directory, a target that does not exist, a path
//     that leaves the repository, and an absolute path.
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join, posix, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import MarkdownIt from 'markdown-it';

/** Directories directly under docs/ that are never published. */
export const UNPUBLISHED = ['design'];

const REPO_URL = 'https://github.com/FreeMixer/plugin-hostd';

export class SiteError extends Error {}

/** Every published page, as a path relative to docs/ with forward slashes. */
export function publishedPages(docsDir) {
  return readdirSync(docsDir, { recursive: true })
    .map((p) => String(p).split('\\').join('/'))
    .filter((p) => p.endsWith('.md') && !UNPUBLISHED.includes(p.split('/')[0]))
    .sort();
}

/** True when `docsPath` (relative to docs/) lies in an unpublished directory. */
const unpublished = (docsPath) => UNPUBLISHED.includes(docsPath.split('/')[0]);

function slugify(text) {
  return (
    text
      .toLowerCase()
      .replace(/[`*_]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'section'
  );
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function makeRenderer() {
  // No raw HTML: a page is markdown, and a tag in it is shown, not run.
  const md = new MarkdownIt({ html: false, linkify: false, typographer: false });
  md.core.ruler.push('heading_ids', (state) => {
    const seen = new Map();
    state.tokens.forEach((tok, i) => {
      if (tok.type !== 'heading_open') return;
      const base = slugify(state.tokens[i + 1].content);
      const n = seen.get(base) ?? 0;
      seen.set(base, n + 1);
      tok.attrSet('id', n === 0 ? base : `${base}-${n}`);
    });
  });
  return md;
}

/**
 * Resolve one reference of a page. Returns { href } to write into the page, and { copy } when a file under docs/ is
 * to be copied into the site. Throws SiteError, naming the page and the target, on a refusal.
 */
export function resolveTarget({ root, page, target, kind, pages, rev }) {
  const where = `docs/${page}`;
  if (target === '' || target.startsWith('#') || /^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith('//')) {
    return { href: target };
  }
  if (target.startsWith('/')) throw new SiteError(`${where}: ${target} is an absolute path; reference it relatively`);
  const cut = target.search(/[?#]/);
  const pathPart = decodeURI(cut < 0 ? target : target.slice(0, cut));
  const suffix = cut < 0 ? '' : target.slice(cut);
  const fromRoot = posix.normalize(posix.join('docs', posix.dirname(page), pathPart));
  if (fromRoot === '..' || fromRoot.startsWith('../')) throw new SiteError(`${where}: ${target} leaves the repository`);
  const onDisk = join(root, fromRoot);
  if (!existsSync(onDisk)) throw new SiteError(`${where}: ${target} does not exist (${fromRoot})`);

  if (fromRoot.startsWith('docs/')) {
    const inDocs = fromRoot.slice('docs/'.length);
    if (unpublished(inDocs)) {
      throw new SiteError(`${where}: ${target} is in docs/${inDocs.split('/')[0]}, which is not published`);
    }
    const rel = posix.relative(posix.dirname(page), inDocs) || posix.basename(inDocs);
    if (inDocs.endsWith('.md') && kind === 'link') {
      if (!pages.includes(inDocs)) throw new SiteError(`${where}: ${target} is not a published page`);
      return { href: rel.replace(/\.md$/, '.html') + suffix, page: inDocs };
    }
    if (statSync(onDisk).isDirectory()) {
      // A directory has no page of its own: a link to it is a link to its listing on GitHub, and nothing is copied.
      if (kind === 'image') throw new SiteError(`${where}: the image ${target} is a directory`);
      return { href: `${REPO_URL}/tree/${rev}/${fromRoot}${suffix}` };
    }
    return { href: rel + suffix, copy: inDocs };
  }
  if (kind === 'image') throw new SiteError(`${where}: the image ${target} is outside docs/; images are published from docs/ only`);
  const what = statSync(onDisk).isDirectory() ? 'tree' : 'blob';
  return { href: `${REPO_URL}/${what}/${rev}/${fromRoot}${suffix}` };
}

const STYLE = `
:root { color-scheme: light dark; --fg: #1d2125; --bg: #fdfdfc; --dim: #5b636b; --edge: #d9dcdf; --code: #f2f3f4; --link: #0b5cad; }
@media (prefers-color-scheme: dark) { :root { --fg: #e4e6e8; --bg: #121417; --dim: #9aa2aa; --edge: #2c3136; --code: #1b1f23; --link: #6cb0f5; } }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.6 system-ui, sans-serif; }
header, main, footer { max-width: 52rem; margin: 0 auto; padding: 0 1rem; }
header { padding-top: 1rem; border-bottom: 1px solid var(--edge); }
header a { color: var(--fg); font-weight: 600; text-decoration: none; }
footer { color: var(--dim); font-size: .85rem; border-top: 1px solid var(--edge); padding: 1rem; margin-top: 3rem; }
a { color: var(--link); }
pre, code { font-family: ui-monospace, monospace; font-size: .9em; background: var(--code); }
pre { padding: .75rem; overflow-x: auto; border-radius: 4px; }
pre code { background: none; }
table { border-collapse: collapse; display: block; overflow-x: auto; }
th, td { border: 1px solid var(--edge); padding: .3rem .6rem; text-align: left; vertical-align: top; }
img { max-width: 100%; height: auto; }
`;

function pageHtml({ title, body, depth, rev }) {
  const up = depth === 0 ? '' : '../'.repeat(depth);
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)} | plugin-hostd</title>
<link rel="stylesheet" href="${up}style.css">
</head>
<body>
<header><p><a href="${up}index.html">plugin-hostd documentation</a></p></header>
<main>
${body}</main>
<footer>Built from <a href="${REPO_URL}/tree/${rev}/docs">docs/</a> of <a href="${REPO_URL}">FreeMixer/plugin-hostd</a> at ${rev.slice(0, 12)}.</footer>
</body>
</html>
`;
}

/** Build the site. Returns { pages, copied }; throws SiteError on a refusal. */
export function buildSite({ root, out, rev }) {
  const docsDir = join(root, 'docs');
  if (!existsSync(join(docsDir, 'index.md'))) throw new SiteError('docs/index.md, the landing page, does not exist');
  const pages = publishedPages(docsDir);
  const md = makeRenderer();
  const copies = new Set();
  const linksOf = new Map();
  const rendered = [];

  for (const page of pages) {
    const source = readFileSync(join(docsDir, page), 'utf8');
    const env = {};
    const linked = new Set();
    linksOf.set(page, linked);
    const tokens = md.parse(source, env);
    const visit = (list) => {
      for (const tok of list) {
        if (tok.children) visit(tok.children);
        const attr = tok.type === 'image' ? 'src' : tok.type === 'link_open' ? 'href' : null;
        if (!attr) continue;
        const r = resolveTarget({ root, page, target: tok.attrGet(attr), kind: tok.type === 'image' ? 'image' : 'link', pages, rev });
        tok.attrSet(attr, r.href);
        if (r.copy) copies.add(r.copy);
        if (r.page) linked.add(r.page);
      }
    };
    visit(tokens);
    const h1 = tokens.findIndex((t) => t.type === 'heading_open' && t.tag === 'h1');
    const title = h1 >= 0 ? tokens[h1 + 1].content : page.replace(/\.md$/, '');
    rendered.push({ page, title, body: md.renderer.render(tokens, md.options, env) });
  }

  // Every page is reachable from the landing page, directly or through pages it links.
  const reached = new Set(['index.md']);
  const queue = ['index.md'];
  while (queue.length > 0) {
    for (const next of linksOf.get(queue.shift())) {
      if (!reached.has(next)) {
        reached.add(next);
        queue.push(next);
      }
    }
  }
  const unreachable = pages.filter((p) => !reached.has(p));
  if (unreachable.length > 0) {
    throw new SiteError(`no link from docs/index.md reaches these published pages: ${unreachable.map((p) => `docs/${p}`).join(', ')}`);
  }

  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  for (const { page, title, body } of rendered) {
    const to = join(out, page.replace(/\.md$/, '.html'));
    mkdirSync(dirname(to), { recursive: true });
    writeFileSync(to, pageHtml({ title, body, depth: page.split('/').length - 1, rev }));
  }
  for (const rel of copies) {
    mkdirSync(dirname(join(out, rel)), { recursive: true });
    cpSync(join(docsDir, rel), join(out, rel));
  }
  writeFileSync(join(out, 'style.css'), STYLE.trimStart());
  writeFileSync(join(out, '.nojekyll'), '');

  // Presence check against the output, not the plan.
  const absent = [...pages.map((p) => p.replace(/\.md$/, '.html')), ...copies].filter((f) => !existsSync(join(out, f)));
  if (absent.length > 0) throw new SiteError(`not written: ${absent.join(', ')}`);
  for (const dir of UNPUBLISHED) if (existsSync(join(out, dir))) throw new SiteError(`the site carries ${dir}/, which is not published`);
  return { pages, copied: [...copies].sort() };
}

function main(argv) {
  const here = dirname(fileURLToPath(import.meta.url));
  const arg = (name, fallback) => {
    const i = argv.indexOf(name);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
  };
  const root = resolve(arg('--src', join(here, '..', '..')));
  const out = resolve(arg('--out', join(root, 'build', 'site')));
  let rev;
  try {
    rev = execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  } catch {
    rev = 'main';
  }
  try {
    const { pages, copied } = buildSite({ root, out, rev });
    console.log(`site: ${pages.length} page(s) and ${copied.length} referenced file(s) written to ${out}`);
    for (const p of pages) console.log(`  page  docs/${p}`);
    for (const f of copied) console.log(`  file  docs/${f}`);
  } catch (e) {
    if (!(e instanceof SiteError)) throw e;
    console.error(`site: ${e.message}`);
    process.exit(1);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
