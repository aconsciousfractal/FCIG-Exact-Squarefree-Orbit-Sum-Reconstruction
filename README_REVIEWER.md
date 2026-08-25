# Reviewer quickstart

This repository contains one finite theorem paper and its certified atlas.

## Ten-minute path

1. Read the title-named PDF in `paper/`, especially Theorem 1.1 and Sections
   4--7.
2. Read `docs/CLAIM_LEDGER.md` and `docs/PUBLIC_CLAIM_BOUNDARY.md`.
3. Inspect `certificates/theorem_summary.json` and `docs/ARTIFACT_MAP.md`.
4. Read `docs/PRIOR_ART_BOUNDARY.md` and the limits in Section 9.

The headline tuples, in action order `S4,A4,S5,A5`, are:

```text
degree:          3, 3, 4, 4
dictionary size: 19, 29, 83, 124
global minimum:  7, 11, 14, 17
```

## Thirty-minute path

```bash
python -m pip install --require-hashes -r requirements.txt
python -B -m unittest discover -s tests -v
python -B scripts/verify.py --profile core
```

The runtime depends on hardware because the command reconstructs all four
finite actions and checks `277,237` lower-DAG nodes. A successful run ends
with `PASS_ORBIT_SUM_PACKAGE_CORE`.

## High-value falsification questions

- Does any statement replace ordered arcs by unordered edges?
- Is every minimum explicitly relative to the fixed squarefree dictionary?
- Are global minima kept separate from conditional top-degree extensions?
- Are the `14/17` lower bounds checked from explicit pattern pairs and
  separator masks, rather than copied solver output?
- Is every lower-DAG node reachable, locally checked, and acyclic?
- Are the eight `A5` exceptions described only as finite index-two split
  pairs, without physical or chemical interpretation?
- Is a finite literature search kept distinct from a novelty claim?
- Does the checked-out ancestry exclude historical governance paths while
  permitting ordinary branches, prior commits, and version tags?
- Does candidate mode reject a premature `v2.0.0` tag, and does release mode
  accept only an annotated `v2.0.0` tag on the verified `HEAD`?
- Does a clean ordinary-Git checkout reproduce the manifest and PDF without
  Git LFS?
- Does changing QA status, PDF binding, page census, renderer, or DPI fail even
  after transport hashes are rebuilt?
- Is canonical PDF byte identity kept distinct from an unobserved hosted run?

## Artifact path

- normalization and serialization: `docs/NORMALIZATION_LOCK.md`;
- four-vertex enumeration: `certificates/orbit_atlas/`;
- four-vertex minima: `certificates/minimum_fingerprints/`;
- readable structural lower bounds: `certificates/family_degree/`;
- five-vertex payload and lower DAGs: `certificates/five_vertex/`;
- independent five-vertex checkers: `scripts/five_vertex/checker/`;
- exact statement crosswalk: `certificates/theorem_summary.json`;
- visual QA: `docs/PDF_VISUAL_QA.json` and its Markdown projection;
- canonical PDF toolchain: `PDF_BUILD_TOOLCHAIN.json`;
- package identity: `MANIFEST_SHA256.txt` and `BUILD_ATTESTATION.json`.

No third-party full text is distributed. A successful local replay is not a
claim of journal peer review or independent external reproduction.
