# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# THE HARNESS FLOOR (fuzz/coverage.sh) AND THE RECORDS (fuzz/records.sh). Reads `llvm-cov show` of one harness
# source (`LINE|COUNT|source`; records.sh feeds the plain source the same way, with a count of 1) and prints, for every
# property check in it, one line
#
#   <file>:<check line>:<abort line>:<count>:<the check's first source line>
#
# A property check is an abort() and the statement that guards it: the `if` whose
# condition ends in the abort, or, for a bare abort() in a block (an `else` arm, a
# switch's `default:`), the statement that opens that block. <count> is how often the
# seed corpus executed that statement's first line; 0 is a property no seed tests. A stop
# that is not a property prints `-` as its count: it needs no seed.
# Comments are stripped before anything is matched, so an abort() named in prose is
# not a site.
#
# THE RECORDS. The comment lines directly above the check's statement, its own lines, and
# the comment lines directly above the abort() hold what breaks the check, as the OSS
# Verify enrolment reads them (docs/build-contract.md there, "The checks of a fuzz target"):
#
#   mutant: <path>:<line> `<old>` -> `<new>`
#   input: <a seed of the harness's corpus>
#
# one pair or more, or one line `not a property: <reason>` for a stop that is no property,
# such as the harness's own allocation failing. With -v records=1 this prints, in place
# of the lines above, one line for each record, its fields separated by the unit
# separator (octal 037), since <new> can be empty:
#
#   <file> <abort line> <path> <line> <old> <new> <input>
#
# THE RATCHET. A check with no record and no `not a property:` line, a `mutant:` line not
# of that form or with no `input:` after it, an `input:` with no `mutant:` before it, or a
# check with both a record and `not a property:` is named on standard error, and the exit
# status is 1.
BEGIN { FS = "|" }
{
	ln = $1 + 0
	cnt = $2
	gsub(/[ \t]/, "", cnt)
	src = $0
	sub(/^[^|]*\|[^|]*\|/, "", src)
	code = src
	if (incomment) {
		if (code ~ /\*\//) { sub(/^.*\*\//, "", code); incomment = 0 }
		else code = ""
	}
	while (match(code, /\/\*([^*]|\*+[^*\/])*\*+\//))
		code = substr(code, 1, RSTART - 1) substr(code, RSTART + RLENGTH)
	if (code ~ /\/\*/) { sub(/\/\*.*$/, "", code); incomment = 1 }
	sub(/\/\/.*$/, "", code)
	gsub(/^[ \t]+|[ \t]+$/, "", code)
	C[ln] = code; N[ln] = cnt; S[ln] = src
	if (code ~ /(^|[^A-Za-z0-9_])abort\(\);/) site[++ns] = ln
}

# The first line of the statement that ends on line l.
function stmt_start(l) {
	while (l > 1 && C[l - 1] != "" && C[l - 1] !~ /[;{}:]$/) l--
	return l
}

# A line of comment and no code.
function comment_only(l,    t) {
	t = S[l]
	gsub(/[ \t]/, "", t)
	return C[l] == "" && t != ""
}

# A comment line without its markers: leading spaces, `//`, `/*` and `*`, and a trailing `*/`.
function clean(t) {
	gsub(/^[ \t]+|[ \t]+$/, "", t)
	sub(/\*\/$/, "", t)
	sub(/^[ \t\/*]+/, "", t)
	gsub(/[ \t]+$/, "", t)
	return t
}

# The comment lines directly above line l into L[] from position n; the new count.
function above(l, n,    k, first) {
	for (first = l - 1; first >= 1 && comment_only(first); first--)
		;
	for (k = first + 1; k < l; k++)
		L[++n] = k
	return n
}

function problem(l, why) {
	printf "%s:%d: %s\n", file, l, why > "/dev/stderr"
	bad = 1
}

# Read the records of the check whose statement is lines s to l (the abort); 1 for a stop that is not a property.
function records_of(s, l,    n, k, i, t, seen, nrec, nap, pending, p, m, path, line) {
	n = above(s, 0)
	for (k = s; k <= l; k++)
		L[++n] = k
	if (l > s)
		n = above(l, n)
	nrec = nap = 0
	pending = ""
	for (i = 1; i <= n; i++) {
		if (L[i] in seen)
			continue
		seen[L[i]] = 1
		t = S[L[i]]
		if (C[L[i]] != "") {
			# a comment after code on the same line
			if (!match(t, /\/\*.*$/))
				continue
			t = substr(t, RSTART)
		}
		t = clean(t)
		if (pending != "") {
			if (t ~ /^input:[ \t]*[^ \t]/) {
				sub(/^input:[ \t]*/, "", t)
				nrec++
				if (records)
					printf "%s\037%d\037%s\037%s\n", file, l, pending, t
			} else
				problem(l, "the line after a mutant: line is not `input: <seed>`")
			pending = ""
			continue
		}
		if (t ~ /^mutant:/) {
			if (t !~ /^mutant:[ \t]*[^ \t`]+:[0-9]+[ \t]+`[^`]*`[ \t]*->[ \t]*`[^`]*`$/) {
				problem(l, "a mutant: line is not `mutant: <path>:<line> `<old>` -> `<new>``")
				continue
			}
			split(t, p, "`")
			m = p[1]
			sub(/^mutant:[ \t]*/, "", m)
			gsub(/[ \t]+$/, "", m)
			path = m
			sub(/:[0-9]+$/, "", path)
			line = substr(m, length(path) + 2)
			if (p[2] == "")
				problem(l, "the mutant at " m " replaces nothing")
			else
				pending = path "\037" line "\037" p[2] "\037" p[4]
		} else if (t ~ /^input:/)
			problem(l, "an input: line has no mutant: line before it")
		else if (t ~ /^not a property:[ \t]*[^ \t]/)
			nap++
	}
	if (pending != "")
		problem(l, "a mutant: line has no input: line after it")
	if (nap && nrec)
		problem(l, "both a record and not a property: keep one")
	if (!nap && !nrec)
		problem(l, "no mutant: and input: record and no not a property: line")
	return nap > 0 && nrec == 0
}

END {
	for (i = 1; i <= ns; i++) {
		l = site[i]
		s = stmt_start(l)
		if (s == l && C[l] ~ /^abort\(\);/) {
			d = 0
			for (s = l - 1; s >= 1 && d >= 0; s--)
				for (k = length(C[s]); k >= 1; k--) {
					c = substr(C[s], k, 1)
					if (c == "}") d++
					else if (c == "{" && --d < 0) break
				}
			s = stmt_start(s + 1)
		}
		nap = records_of(s, l)
		if (records)
			continue
		t = S[s]
		gsub(/^[ \t]+/, "", t)
		printf "%s:%d:%d:%s:%s\n", file, s, l, nap ? "-" : N[s], t
	}
	exit bad
}
