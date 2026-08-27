# Exact Squarefree Orbit-Sum Reconstruction of Four- and Five-Vertex Loopless Digraphs

Companion repository for the manuscript

> **Exact Squarefree Orbit-Sum Reconstruction of Four- and Five-Vertex
> Loopless Digraphs: Minimum Separating Fingerprints, Tree Separators, and a
> Certified Atlas**<br>
> Oleksiy Babanskyy.

The repository contains the manuscript, exact finite certificates, and the
code needed to check the advertised computations. The four- and five-vertex
cases use one model: Boolean loopless directed graphs, relabelling by the
symmetric or alternating group, and cumulative integer orbit sums of
squarefree arc supports.

PDF: [`paper/Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf`](paper/Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf).

## Main theorem

For the four finite actions, the exact least separating degree, the size of
the complete dictionary at that degree, and the least size of a separating
subfamily are:

| action | degree | dictionary size | minimum subfamily |
| --- | ---: | ---: | ---: |
| `S4` | 3 | 19 | 7 |
| `A4` | 3 | 29 | 11 |
| `S5` | 4 | 83 | 14 |
| `A5` | 4 | 124 | 17 |

The four-vertex lower bounds have short structural certificates. The
five-vertex lower bounds are certified by complete branch DAGs with `63,589`
and `213,648` reachable nodes. The checkers reconstruct every separator mask
from explicit pattern pairs; optimizer status is never treated as proof.

One degree below reconstruction, the residual-pair counts are
`39, 51, 190, 113`. Tree-supported top-degree coordinates individually
separate `39, 51, 190, 105` of those pairs. The eight remaining `A5` pairs
are finite index-two split pairs. The manuscript also treats the distinct
conditional problem in which all lower-degree coordinates are retained.

The complete four-vertex optimum landscapes contain `10` and `896`
fingerprints. The `128` conditional cubic `A4` optima have exchange graph
`4(K4 Cartesian Q3)` and a free graded `C2^3` action; the exchange graph on
all `896` global `A4` optima is explicitly
`4(K7 Cartesian K4 Cartesian Q3)`. For the eight tree-blind `A5` pairs, the
signed non-tree channel has a primitive rank-four integral core. It forces
one of the two `A5` children above parent `00115` and requires selected split
coordinates from at least two non-tree parents.

## Claim boundary

Every minimum is relative to the declared cumulative squarefree
support-orbit dictionary. The results cover exactly `n=4,5` and the actions
`S4,A4,S5,A5`; they do not cover arbitrary invariants, `n>5`, physical
chirality, or chemical realizability. No novelty, priority, or firstness
claim is made. See [`docs/CLAIM_LEDGER.md`](docs/CLAIM_LEDGER.md),
[`docs/PUBLIC_CLAIM_BOUNDARY.md`](docs/PUBLIC_CLAIM_BOUNDARY.md), and
[`docs/PRIOR_ART_BOUNDARY.md`](docs/PRIOR_ART_BOUNDARY.md).

## Verification

With CPython 3.12 or later:

```bash
python -m pip install --require-hashes -r requirements.txt
python scripts/verify.py --profile core
python -O scripts/verify.py --profile core
python scripts/verify.py --profile full
```

The core profile checks the manifest, all distributed certificates, the
independent five-vertex reconstruction, both lower DAGs, the theorem summary,
the structural-landscape certificate and independently reconstructed signed
matrix, the claim boundary, the PDF, its machine-bound visual-QA record, and
the canonical build-toolchain lock. The full profile additionally regenerates
the independent finite enumerations in disposable directories and requires a
byte-identical PDF build under the locked toolchain. See
[`REPRODUCE.md`](REPRODUCE.md).

## Layout

```text
paper/          LaTeX source and title-named PDF
certificates/   exact finite data, witnesses, and complete proof DAGs
scripts/        generators, independent checkers, build tools, and verifier
tests/          package, semantic, and Git-boundary regression tests
schemas/        mathematical data contracts and serialization specifications
docs/           claim, prior-art, normalization, artifact, and QA records
```

`MANIFEST_SHA256.txt` binds the distributed package. `PDF_BUILD_TOOLCHAIN.json`
records the exact canonical compiler, commands, deterministic environment, and
106 loaded TeX files. `docs/PDF_VISUAL_QA.json` binds a closed, machine-checked
all-page QA declaration to the exact PDF; its truth remains a human observation.
`BUILD_ATTESTATION.json` binds those records and immutable build facts. Review,
publication, archive, and DOI events are deliberately
recorded outside the versioned source tree so that adding the annotated
`v2.1.0` tag does not make the build attestation false.

## License and citation

The MIT license covers original code, generated finite data, and supporting
documentation. Copyright in the manuscript source and compiled PDF is
retained by the author. See [`LICENSE_SCOPE.md`](LICENSE_SCOPE.md),
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md), and
[`CITATION.cff`](CITATION.cff).
