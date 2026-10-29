#!/usr/bin/env node
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
//
// build.mjs: renders the repository's docs/ into the static site GitHub Pages serves (.github/workflows/pages.yml),
// the plugin-hostd technical manual.
//
//   node tools/site/build.mjs [--src <repository root>] [--out <dir>]
//
// Defaults: the repository this file sits in, and build/site under it. Every link in the output is relative, so the
// tree reads the same under any prefix it is served from.
//
// THE SHAPE comes from docs/site.yml: the sections in navigation order, the entries of each (a page of docs/, or a
// page elsewhere), and the row of captures on the landing page, docs/index.md. Each section gets an index page, every
// page the navigation, and a footer with its source path and the date of its last commit. The Evidence section is
// generated: every file under a docs/**/evidence/ directory, by topic and date, with the pages that cite it.
//
// PENDING. An entry marked `pending: true` names a page that is not in docs/ yet: it is shown as "coming: <title>"
// with no link, and a link to it from a page is shown as its text, marked coming. When the file arrives the site
// links it and the build says to drop the flag. A page entry without the flag whose file is missing fails the build.
//
// WHAT IS PUBLISHED. Every markdown page under docs/ except the directories UNPUBLISHED names (design material: it
// stays in the repository and never reaches the site) and except files under an evidence/ directory, which are
// evidence, not pages. Every published page must be an entry of site.yml or be reached by links from one; a page
// nobody can reach fails the build by name.
//
// WHAT A PAGE MAY POINT AT, checked page by page; every refusal names the page and the target:
//   - another published page: rendered as a link to its .html;
//   - a pending page of site.yml: rendered as its text, marked coming;
//   - section:<id>, a section of site.yml: a link to that section's index page;
//   - any other file under docs/ (a figure, a capture, a data file): copied into the site beside the pages, and only
//     when a page references it, so nothing under docs/ is published that no page points at;
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
import { parse as parseYaml } from 'yaml';

/** Directories directly under docs/ that are never published. */
export const UNPUBLISHED = ['design'];

const REPO_URL = 'https://github.com/FreeMixer/plugin-hostd';
const IMAGE = /\.(png|jpe?g|gif|svg|webp)$/i;

export class SiteError extends Error {}

const unpublished = (docsPath) => UNPUBLISHED.includes(docsPath.split('/')[0]);
const isEvidence = (docsPath) => docsPath.split('/').slice(0, -1).includes('evidence');

/** Every file under docs/, relative to it, with forward slashes. */
function docsFiles(docsDir) {
  return readdirSync(docsDir, { recursive: true, withFileTypes: true })
    .filter((e) => e.isFile())
    .map((e) => posix.join(posix.relative(docsDir, e.parentPath ?? e.path).split('\\').join('/'), e.name))
    .sort();
}

/** Every published page, relative to docs/. */
export function publishedPages(docsDir) {
  return docsFiles(docsDir).filter((p) => p.endsWith('.md') && !unpublished(p) && !isEvidence(p));
}

const htmlOf = (page) => page.replace(/\.md$/, '.html');

function slugify(text) {
  return (
    text
      .toLowerCase()
      .replace(/[`*_]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'section'
  );
}

const escapeHtml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** The relative path from the page at `from` (a site path) to the site path `to`. */
const rel = (from, to) => posix.relative(posix.dirname(from), to) || posix.basename(to);

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

// ---------------------------------------------------------------------------------------------------------------
// docs/site.yml
// ---------------------------------------------------------------------------------------------------------------

/** Read and check docs/site.yml against the tree. Returns the site with each entry resolved. */
export function readSite(docsDir) {
  const file = join(docsDir, 'site.yml');
  if (!existsSync(file)) throw new SiteError('docs/site.yml, the shape of the site, does not exist');
  let site;
  try {
    site = parseYaml(readFileSync(file, 'utf8'));
  } catch (e) {
    throw new SiteError(`docs/site.yml: ${e.message}`);
  }
  if (!site || typeof site.title !== 'string') throw new SiteError('docs/site.yml: no title');
  if (!Array.isArray(site.sections) || site.sections.length === 0) throw new SiteError('docs/site.yml: no sections');
  const landing = site.landing?.page ?? 'index.md';
  if (!existsSync(join(docsDir, landing))) throw new SiteError(`docs/${landing}, the landing page, does not exist`);
  const notices = [];
  const ids = new Set();
  const sections = site.sections.map((s, si) => {
    const where = `docs/site.yml: section ${si + 1}`;
    if (!s?.id || !/^[a-z][a-z0-9-]*$/.test(s.id) || !s.title) throw new SiteError(`${where} needs an id ([a-z0-9-]) and a title`);
    if (ids.has(s.id)) throw new SiteError(`${where}: the id ${s.id} is used twice`);
    ids.add(s.id);
    if (s.generated !== undefined && s.generated !== 'evidence') throw new SiteError(`${where}: unknown generated "${s.generated}"`);
    const entries = (s.entries ?? []).map((e, ei) => {
      const at = `docs/site.yml: ${s.id}, entry ${ei + 1}`;
      if (!e?.title || !e.page === !e.url) throw new SiteError(`${at} needs a title and one of page or url`);
      if (e.url) return { kind: 'url', title: e.title, blurb: e.blurb, url: e.url, pending: e.pending === true };
      if (e.page.startsWith('/') || e.page.split('/').includes('..') || !e.page.endsWith('.md')) {
        throw new SiteError(`${at}: ${e.page} is not a page under docs/`);
      }
      if (unpublished(e.page)) throw new SiteError(`${at}: docs/${e.page} is in an unpublished directory`);
      const present = existsSync(join(docsDir, e.page));
      if (!present && e.pending !== true) throw new SiteError(`${at}: docs/${e.page} does not exist (mark it pending: true until it does)`);
      if (present && e.pending === true) notices.push(`docs/${e.page} is in docs/ now: drop its pending flag in docs/site.yml`);
      return { kind: 'page', title: e.title, blurb: e.blurb, page: e.page, live: present };
    });
    return { id: s.id, title: s.title, blurb: s.blurb ?? '', generated: s.generated, entries };
  });
  const captures = (site.landing?.captures ?? []).map((c, i) => {
    const at = `docs/site.yml: capture ${i + 1}`;
    if (!c?.src || !c.caption) throw new SiteError(`${at} needs a src and a caption`);
    if (c.src.startsWith('/') || c.src.split('/').includes('..') || unpublished(c.src) || !IMAGE.test(c.src)) {
      throw new SiteError(`${at}: ${c.src} is not an image under docs/`);
    }
    const present = existsSync(join(docsDir, c.src));
    if (!present && c.pending !== true) throw new SiteError(`${at}: docs/${c.src} does not exist (mark it pending: true until it does)`);
    if (present && c.pending === true) notices.push(`docs/${c.src} is in docs/ now: drop its pending flag in docs/site.yml`);
    return { src: c.src, caption: c.caption, live: present };
  });
  const pending = new Set(sections.flatMap((s) => s.entries.filter((e) => e.kind === 'page' && !e.live).map((e) => e.page)));
  return { title: site.title, landing, sections, captures, pending, notices };
}

// ---------------------------------------------------------------------------------------------------------------
// References
// ---------------------------------------------------------------------------------------------------------------

/**
 * Resolve one reference of a page. Returns { href } to write into the page, { copy } when a file under docs/ is to be
 * copied into the site, { page } when it is a published page, and { coming: true } for a pending page. Throws
 * SiteError, naming the page and the target, on a refusal.
 */
export function resolveTarget({ root, page, target, kind, pages, rev, pending = new Set(), sections = [] }) {
  const where = `docs/${page}`;
  if (target.startsWith('section:')) {
    // A section's index page, which site.yml makes and no markdown file holds.
    const id = target.slice('section:'.length);
    if (kind !== 'link' || !sections.includes(id)) throw new SiteError(`${where}: ${target} names no section of docs/site.yml`);
    return { href: rel(page, sectionPath(id)) };
  }
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
  if (!existsSync(onDisk)) {
    if (kind === 'link' && fromRoot.startsWith('docs/') && pending.has(fromRoot.slice('docs/'.length))) return { coming: true };
    throw new SiteError(`${where}: ${target} does not exist (${fromRoot})`);
  }

  if (fromRoot.startsWith('docs/')) {
    const inDocs = fromRoot.slice('docs/'.length);
    if (unpublished(inDocs)) {
      throw new SiteError(`${where}: ${target} is in docs/${inDocs.split('/')[0]}, which is not published`);
    }
    if (statSync(onDisk).isDirectory()) {
      // A directory has no page of its own: a link to it is a link to its listing on GitHub, and nothing is copied.
      if (kind === 'image') throw new SiteError(`${where}: the image ${target} is a directory`);
      return { href: `${REPO_URL}/tree/${rev}/${fromRoot}${suffix}` };
    }
    const r = rel(page, inDocs);
    if (inDocs.endsWith('.md') && kind === 'link' && pages.includes(inDocs)) {
      return { href: htmlOf(r) + suffix, page: inDocs };
    }
    if (inDocs.endsWith('.md') && kind === 'link' && !isEvidence(inDocs)) throw new SiteError(`${where}: ${target} is not a published page`);
    return { href: r + suffix, copy: inDocs };
  }
  if (kind === 'image') throw new SiteError(`${where}: the image ${target} is outside docs/; images are published from docs/ only`);
  const what = statSync(onDisk).isDirectory() ? 'tree' : 'blob';
  return { href: `${REPO_URL}/${what}/${rev}/${fromRoot}${suffix}` };
}

// ---------------------------------------------------------------------------------------------------------------
// The page frame: navigation, footer
// ---------------------------------------------------------------------------------------------------------------

const STYLE = `
:root { color-scheme: light dark; --fg: #1d2125; --bg: #fdfdfc; --dim: #5b636b; --edge: #d9dcdf; --code: #f2f3f4; --link: #0b5cad; --side: #f6f7f8; }
@media (prefers-color-scheme: dark) { :root { --fg: #e4e6e8; --bg: #121417; --dim: #9aa2aa; --edge: #2c3136; --code: #1b1f23; --link: #6cb0f5; --side: #171a1e; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.6 system-ui, sans-serif; }
.top { border-bottom: 1px solid var(--edge); padding: .75rem 1rem; }
.top a { color: var(--fg); font-weight: 600; text-decoration: none; }
.frame { display: grid; grid-template-columns: 17rem minmax(0, 1fr); max-width: 76rem; margin: 0 auto; }
nav.side { background: var(--side); border-right: 1px solid var(--edge); padding: 1rem; font-size: .9rem; }
nav.side h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; margin: 1.2rem 0 .3rem; }
nav.side h2:first-child { margin-top: 0; }
nav.side h2 a { color: var(--fg); text-decoration: none; }
nav.side ul { list-style: none; margin: 0; padding: 0; }
nav.side li { margin: .15rem 0; }
nav.side a[aria-current] { font-weight: 600; color: var(--fg); }
.coming { color: var(--dim); }
span.coming::after { content: " (coming)"; }
nav.side span.coming::after, .entries span.coming::after { content: ""; }
main { padding: 1rem 2rem 2rem; min-width: 0; }
footer { color: var(--dim); font-size: .85rem; border-top: 1px solid var(--edge); margin-top: 3rem; padding-top: 1rem; }
a { color: var(--link); }
pre, code { font-family: ui-monospace, monospace; font-size: .9em; background: var(--code); }
pre { padding: .75rem; overflow-x: auto; border-radius: 4px; }
pre code { background: none; }
table { border-collapse: collapse; display: block; overflow-x: auto; }
th, td { border: 1px solid var(--edge); padding: .3rem .6rem; text-align: left; vertical-align: top; }
img { max-width: 100%; height: auto; }
.captures { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; margin: 1.5rem 0; }
.captures figure { margin: 0; border: 1px solid var(--edge); border-radius: 4px; padding: .5rem; }
.captures .slot { aspect-ratio: 4 / 3; display: flex; align-items: center; justify-content: center; background: var(--side); color: var(--dim); font-size: .85rem; }
.captures figcaption { font-size: .85rem; color: var(--dim); margin-top: .4rem; }
.thumb { max-width: 12rem; max-height: 8rem; border: 1px solid var(--edge); display: block; margin: .3rem 0; }
@media (max-width: 48rem) { .frame { grid-template-columns: 1fr; } nav.side { border-right: 0; border-bottom: 1px solid var(--edge); } .captures { grid-template-columns: 1fr; } main { padding: 1rem; } }
`;

const sectionPath = (id) => `section/${id}.html`;

function entryLink(from, e) {
  if ((e.kind === 'url' && e.pending) || (e.kind === 'page' && !e.live)) {
    return `<span class="coming">coming: ${escapeHtml(e.title)}</span>`;
  }
  if (e.kind === 'url') return `<a href="${escapeHtml(e.url)}">${escapeHtml(e.title)}</a>`;
  const cur = htmlOf(e.page) === from ? ' aria-current="page"' : '';
  return `<a href="${rel(from, htmlOf(e.page))}"${cur}>${escapeHtml(e.title)}</a>`;
}

function navHtml(site, from) {
  const out = ['<nav class="side" aria-label="Contents">'];
  for (const s of site.sections) {
    const cur = sectionPath(s.id) === from ? ' aria-current="page"' : '';
    out.push(`<h2><a href="${rel(from, sectionPath(s.id))}"${cur}>${escapeHtml(s.title)}</a></h2>`);
    if (s.entries.length > 0) out.push(`<ul>${s.entries.map((e) => `<li>${entryLink(from, e)}</li>`).join('')}</ul>`);
  }
  out.push('</nav>');
  return out.join('\n');
}

function frame({ site, from, title, body, source, date, rev }) {
  const sourceLine = source
    ? `Source: <a href="${REPO_URL}/blob/${rev}/${source}">${escapeHtml(source)}</a>, last changed ${escapeHtml(date)}.`
    : 'Generated from docs/site.yml by tools/site/build.mjs.';
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)} | ${escapeHtml(site.title)}</title>
<link rel="stylesheet" href="${rel(from, 'style.css')}">
</head>
<body>
<header class="top"><a href="${rel(from, 'index.html')}">${escapeHtml(site.title)}</a></header>
<div class="frame">
${navHtml(site, from)}
<main>
${body}
<footer>${sourceLine} Built from <a href="${REPO_URL}">FreeMixer/plugin-hostd</a> at ${escapeHtml(rev.slice(0, 12))}.</footer>
</main>
</div>
</body>
</html>
`;
}

/** The date of the last commit that touched `path`, or "not committed". */
function lastChanged(root, path) {
  try {
    return execFileSync('git', ['-C', root, 'log', '-1', '--format=%cs', '--', path], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() || 'not committed';
  } catch {
    return 'not committed';
  }
}

// ---------------------------------------------------------------------------------------------------------------
// The build
// ---------------------------------------------------------------------------------------------------------------

/** Build the site. Returns { pages, copied, notices }; throws SiteError on a refusal. */
export function buildSite({ root, out, rev }) {
  const docsDir = join(root, 'docs');
  const site = readSite(docsDir);
  const pages = publishedPages(docsDir);
  const md = makeRenderer();
  const copies = new Set();
  const linksOf = new Map();
  const citedBy = new Map();
  const rendered = [];

  for (const page of pages) {
    const source = readFileSync(join(docsDir, page), 'utf8');
    const env = {};
    const linked = new Set();
    linksOf.set(page, linked);
    const tokens = md.parse(source, env);
    const visit = (list) => {
      list.forEach((tok, i) => {
        if (tok.children) visit(tok.children);
        const attr = tok.type === 'image' ? 'src' : tok.type === 'link_open' ? 'href' : null;
        if (!attr) return;
        const kind = tok.type === 'image' ? 'image' : 'link';
        const r = resolveTarget({ root, page, target: tok.attrGet(attr), kind, pages, rev, pending: site.pending, sections: site.sections.map((s) => s.id) });
        if (r.coming) {
          // A link to a page that is not here yet: its text stays, marked coming, and no link is written.
          const close = list.slice(i).find((t) => t.type === 'link_close');
          tok.tag = 'span';
          tok.attrs = [['class', 'coming']];
          if (close) close.tag = 'span';
          return;
        }
        tok.attrSet(attr, r.href);
        if (r.copy) {
          copies.add(r.copy);
          if (!citedBy.has(r.copy)) citedBy.set(r.copy, new Set());
          citedBy.get(r.copy).add(page);
        }
        if (r.page) linked.add(r.page);
      });
    };
    visit(tokens);
    const h1 = tokens.findIndex((t) => t.type === 'heading_open' && t.tag === 'h1');
    const title = h1 >= 0 ? tokens[h1 + 1].content : page.replace(/\.md$/, '');
    let body = md.renderer.render(tokens, md.options, env);
    if (page === site.landing) body = body.replace('<p>{{captures}}</p>', capturesHtml(site, copies));
    rendered.push({ page, title, body });
  }

  // Every page is an entry of site.yml or reached by links from one (the landing page counts as one).
  const starts = [site.landing, ...site.sections.flatMap((s) => s.entries.filter((e) => e.kind === 'page' && e.live).map((e) => e.page))];
  const reached = new Set(starts);
  const queue = [...starts];
  while (queue.length > 0) {
    for (const next of linksOf.get(queue.shift()) ?? []) {
      if (!reached.has(next)) {
        reached.add(next);
        queue.push(next);
      }
    }
  }
  const unreachable = pages.filter((p) => !reached.has(p));
  if (unreachable.length > 0) {
    throw new SiteError(
      `these published pages are not in docs/site.yml and no page links them: ${unreachable.map((p) => `docs/${p}`).join(', ')}`,
    );
  }

  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  const write = (path, text) => {
    mkdirSync(dirname(join(out, path)), { recursive: true });
    writeFileSync(join(out, path), text);
  };
  for (const { page, title, body } of rendered) {
    const from = page === site.landing ? 'index.html' : htmlOf(page);
    write(from, frame({ site, from, title, body, source: `docs/${page}`, date: lastChanged(root, `docs/${page}`), rev }));
  }
  for (const s of site.sections) {
    const from = sectionPath(s.id);
    const body = s.generated === 'evidence' ? evidenceHtml({ root, docsDir, from, copies, citedBy, rev }) : sectionHtml(s, from);
    write(from, frame({ site, from, title: s.title, body: `<h1>${escapeHtml(s.title)}</h1>\n<p>${escapeHtml(s.blurb)}</p>\n${body}`, rev }));
  }
  for (const r of copies) {
    mkdirSync(dirname(join(out, r)), { recursive: true });
    cpSync(join(docsDir, r), join(out, r));
  }
  writeFileSync(join(out, 'style.css'), STYLE.trimStart());
  writeFileSync(join(out, '.nojekyll'), '');

  // Presence check against the output, not the plan.
  const expected = ['index.html', ...pages.filter((p) => p !== site.landing).map(htmlOf), ...site.sections.map((s) => sectionPath(s.id)), ...copies];
  const absent = expected.filter((f) => !existsSync(join(out, f)));
  if (absent.length > 0) throw new SiteError(`not written: ${absent.join(', ')}`);
  for (const dir of UNPUBLISHED) if (existsSync(join(out, dir))) throw new SiteError(`the site carries ${dir}/, which is not published`);
  return { pages, copied: [...copies].sort(), notices: site.notices };
}

function capturesHtml(site, copies) {
  if (site.captures.length === 0) return '';
  const figs = site.captures.map((c) => {
    if (!c.live) return `<figure><div class="slot">coming</div><figcaption>${escapeHtml(c.caption)}</figcaption></figure>`;
    copies.add(c.src);
    return `<figure><a href="${escapeHtml(c.src)}"><img src="${escapeHtml(c.src)}" alt="${escapeHtml(c.caption)}"></a><figcaption>${escapeHtml(c.caption)}</figcaption></figure>`;
  });
  return `<div class="captures">\n${figs.join('\n')}\n</div>`;
}

function sectionHtml(s, from) {
  if (s.entries.length === 0) return '';
  const items = s.entries.map((e) => `<li>${entryLink(from, e)}${e.blurb ? `: ${escapeHtml(e.blurb)}` : ''}</li>`);
  return `<ul class="entries">\n${items.join('\n')}\n</ul>`;
}

/**
 * The evidence index: every file under an evidence/ directory of docs/, grouped by topic (the directory that holds
 * the evidence/ directory, and the first directory under it) and dated (a YYYY-MM-DD in its path, else its last
 * commit). A file a page cites is published and linked here, a figure shown as a thumbnail; a file no page cites is
 * linked in the repository on GitHub and is not copied.
 */
function evidenceHtml({ root, docsDir, from, copies, citedBy, rev }) {
  const files = docsFiles(docsDir).filter((p) => isEvidence(p) && !unpublished(p));
  if (files.length === 0) return '<p>No evidence files yet.</p>';
  const groups = new Map();
  for (const f of files) {
    const parts = f.split('/');
    const at = parts.indexOf('evidence');
    const owner = parts.slice(0, at).join('/') || 'docs';
    const sub = parts.length - at > 2 ? parts[at + 1] : '';
    const topic = sub ? `${owner} / ${sub}` : owner;
    const dated = /(\d{4}-\d{2}-\d{2})/.exec(f)?.[1] ?? lastChanged(root, `docs/${f}`);
    if (!groups.has(topic)) groups.set(topic, { topic, owner, date: dated, files: [] });
    const g = groups.get(topic);
    if (dated > g.date) g.date = dated;
    g.files.push(f);
  }
  const ordered = [...groups.values()].sort((a, b) => a.owner.localeCompare(b.owner) || b.date.localeCompare(a.date) || a.topic.localeCompare(b.topic));
  const out = [];
  for (const g of ordered) {
    out.push(`<h2 id="${slugify(g.topic)}">${escapeHtml(g.topic)}, ${escapeHtml(g.date)}</h2>\n<ul>`);
    for (const f of g.files) {
      const cited = [...(citedBy.get(f) ?? [])].sort();
      const name = escapeHtml(f.split('/').slice(f.split('/').indexOf('evidence') + 1).join('/'));
      let line;
      if (copies.has(f)) {
        line = `<a href="${rel(from, f)}">${name}</a>`;
        if (IMAGE.test(f)) line += `<a href="${rel(from, f)}"><img class="thumb" src="${rel(from, f)}" alt="${name}"></a>`;
      } else {
        line = `<a href="${REPO_URL}/blob/${rev}/docs/${f}">${name}</a>`;
      }
      const by =
        cited.length > 0
          ? ` cited by ${cited.map((p) => `<a href="${rel(from, htmlOf(p))}">${escapeHtml(p)}</a>`).join(', ')}`
          : ' <small class="coming">no page cites it; in the repository only</small>';
      out.push(`<li>${line}${by}</li>`);
    }
    out.push('</ul>');
  }
  return out.join('\n');
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
    const { pages, copied, notices } = buildSite({ root, out, rev });
    console.log(`site: ${pages.length} page(s) and ${copied.length} referenced file(s) written to ${out}`);
    for (const p of pages) console.log(`  page  docs/${p}`);
    for (const f of copied) console.log(`  file  docs/${f}`);
    for (const n of notices) console.log(`site: note: ${n}`);
  } catch (e) {
    if (!(e instanceof SiteError)) throw e;
    console.error(`site: ${e.message}`);
    process.exit(1);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
