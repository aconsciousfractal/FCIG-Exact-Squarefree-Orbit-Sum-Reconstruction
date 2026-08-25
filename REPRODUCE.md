# Reproducing the paper and certified atlas

Run every command from the repository root.

## Environment

- CPython 3.12, 3.13, or 3.14;
- `pypdf==6.14.2` for PDF structure and text checks;
- a TeX engine only for rebuilding the paper. Exact byte identity additionally
  requires the canonical MiKTeX environment recorded in
  `PDF_BUILD_TOOLCHAIN.json`.

```bash
python -m pip install --require-hashes -r requirements.txt
```

The mathematical checks use only the Python standard library. No network,
external dataset, subscription service, or cited article PDF is required.

## Core verification

```bash
python -B -m unittest discover -s tests -v
python -B -O -m unittest discover -s tests -v
python -B scripts/verify.py --profile core
python -B -O scripts/verify.py --profile core
```

The core profile verifies:

1. every path and SHA-256 row in `MANIFEST_SHA256.txt`;
2. the four carriers, actions, orbit counts, and coordinate profiles;
3. the four-vertex residual pairs, cubic witnesses, exact `7/19` and `11/29`
   minima, and their complete lower certificates;
4. an independent reconstruction of the canonical four-action payload;
5. the five-vertex residual pairs, degree-four injectivity, upper witnesses,
   and every reachable node of the two complete lower DAGs;
6. the tree/index-two and conditional-extension statements;
7. `certificates/theorem_summary.json` against data, TeX, PDF, README, and
   the public claim boundary;
8. PDF metadata, page geometry, embedded fonts, attachments, and active
   actions;
9. the closed visual-QA JSON record, its exact Markdown projection, PASS
   semantics, complete page census, and binding to the current PDF bytes;
10. the canonical PDF toolchain lock, including compiler identity, commands,
    deterministic environment, and the 104-file loaded TeX inventory;
11. the checked-out Git ancestry and current tree, together with ordinary-Git
   delivery without filters, Git LFS pointers, symlinks, historical governance
   paths, hidden index flags, or worktree/index byte drift.

A successful run ends with:

```text
PASS_ORBIT_SUM_PACKAGE_CORE
```

## Full independent replay

```bash
python scripts/verify.py --profile full
```

The full profile regenerates both four-vertex enumeration implementations,
both exact minimum searches, both family-degree implementations, the structural certificate, and
the five-vertex canonical payload in disposable directories. It compares the
resulting canonical objects byte-for-byte with `certificates/`. The large
five-vertex lower DAGs are semantically rechecked rather than rediscovered by
an optimizer. It also requires the isolated PDF to be byte-identical and the
observed toolchain to equal `PDF_BUILD_TOOLCHAIN.json`.

A successful run ends with:

```text
PASS_ORBIT_SUM_PACKAGE_FULL
```

## Build the paper

```bash
python scripts/build_paper.py
python scripts/build_manifest.py
python scripts/build_build_attestation.py
python scripts/verify.py --profile core --skip-git-boundary
```

The builder copies only manuscript sources to an isolated temporary directory,
disables shell escape, fixes `SOURCE_DATE_EPOCH`, and replaces the title-named
PDF only after a successful build. Use
`python -B scripts/build_paper.py --check-byte-identical --check-toolchain-lock`
to require both exact-byte reproduction and the canonical compiler/package
identity. `--write-toolchain-lock` is intentionally separate: it is only for
an explicitly reviewed PDF/toolchain update and still requires byte identity
with the tracked PDF.

`docs/PDF_VISUAL_QA.json` is not generated automatically as a PASS record.
After any PDF-byte change, render and inspect every page, update the JSON and
its Markdown projection, then rebuild the manifest and attestation. The
verifier checks the binding and semantics but cannot replace human inspection.

The canonical lock describes a Windows MiKTeX 25.12 build. A different hosted
runner may test portability, but hosted byte identity is not asserted until an
observed run reports the same PDF hash. The versioned attestation records this
boundary rather than treating a mutable runner image as equivalent to the
canonical environment.

## Clean-checkout verification

After committing the prepared package locally, run from a clean checkout:

```bash
python scripts/verify.py --profile core --git-state candidate
python -O scripts/verify.py --profile core --git-state candidate
```

Candidate mode requires the final versioned tree to be untagged. After review,
an annotated `v2.0.0` tag may be added to that same commit and checked with:

```bash
python scripts/verify.py --profile core --git-state release
```

Development mode is the default and permits ordinary descendant commits,
branches, remote-tracking refs, and existing version tags. In every mode the
Git boundary scans the checked-out ancestry for historical governance paths
and compares `HEAD`, index, and raw worktree bytes. It uses Git plumbing for
attributes and does not parse the human output of `git lfs status`; therefore
it works in repositories with or without a remote and with or without Git LFS
installed.

Review and publication receipts are post-build event records and therefore
are not committed into the versioned source tree they describe. A receipt may
be retained as a release asset or external archive record, but it must bind at
least the commit, tree, annotated tag, manifest, build-attestation, and PDF
SHA-256 values. This keeps the reviewed build byte-identical when it is tagged
and published.
On Windows, the verifier normalizes the project root to the extended-length
path form before enumerating or opening governed files; configure Git with
`core.longpaths=true` when cloning into a root whose deepest tracked path can
exceed 260 characters.

## Mathematical limits

- results are exact only for `n=4,5` and the four declared actions;
- `7,11,14,17` are minima inside the fixed squarefree dictionaries;
- conditional totals `8,12,26,32` solve a different problem;
- the eight `A5` tree-blind pairs have no asserted physical interpretation;
- the source audit provides attribution and scope subtraction, not priority.
