# Verification architecture

The package separates mathematical proof objects from transport checks.

1. **Model identity.** Carrier, action, squarefree coordinate family,
   evaluation, and canonical order are fixed in `docs/NORMALIZATION_LOCK.md`.
2. **Enumeration identity.** Independent implementations reconstruct the same
   finite pattern and coordinate orbits.
3. **Upper bounds.** Every displayed coordinate family is evaluated on every
   canonical pattern orbit and shown injective.
4. **Lower bounds.** Complete proof DAGs exclude every smaller hitting set;
   each branch and leaf is checked from explicit separator masks.
5. **Statement identity.** `certificates/theorem_summary.json` fixes the exact
   four-case tuple and scope ceiling and is checked against data, TeX, PDF,
   README, ledger, and claim boundary.
6. **Transport identity.** The manifest and SHA-256 values bind bytes only
   after semantic checks; a hash never substitutes for a proof step.
7. **Repository identity.** A clean verification scans the checked-out
   ancestry, compares `HEAD`, index, and raw worktree bytes, and rejects
   historical governance paths, filters, Git LFS pointers, symlinks,
   replacement objects, alternates, and hidden index flags. Development mode
   permits normal history and refs; candidate mode requires the intended tag
   to be absent; release mode requires annotated `v2.0.0` on the same `HEAD`.
8. **PDF identity.** Metadata, text boundary, embedded fonts, page geometry,
   attachments, and active actions are checked directly.
9. **Visual-QA identity.** A closed JSON record must declare PASS, enumerate
   all 21 pages, and match the exact PDF path, hash, size, geometry, renderer,
   and DPI. Its Markdown projection is exact. The verifier checks this binding,
   while the visual observation itself remains human evidence.
10. **Build-environment identity.** The canonical PDF lock fixes the MiKTeX
    engine, BibTeX, commands, deterministic environment, and 104 loaded TeX
    files. The full replay requires both this lock and byte-identical output;
    a hosted run is not claimed until it is actually observed.

`scripts/verify.py --profile core` checks all distributed evidence. The
`full` profile additionally regenerates the independent scientific surfaces
in disposable directories. Neither profile accepts optimizer status as a
lower-bound oracle.
