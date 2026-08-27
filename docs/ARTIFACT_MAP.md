# Statement-to-artifact map

| Statement layer | Primary artifact | What is checked |
| --- | --- | --- |
| Common model | `docs/NORMALIZATION_LOCK.md` | carrier, actions, squarefree coordinates, integer evaluation, canonical order |
| Four-vertex orbits and coordinates | `certificates/orbit_atlas/primary/` and `independent/` | `218/368` pattern orbits and degree profiles `(1,5,13)/(1,7,21)` |
| Four-vertex collision boundary | `quadratic_collision_atlas.json` and `cubic_witness_map.json` in both orbit-atlas directories | `39/51` residual pairs and degree-three separators |
| Four-vertex global minima | `certificates/minimum_fingerprints/` | explicit `7/11` supports, all-pair separation, complete lower DAGs |
| Readable four-vertex lower bound | `certificates/family_degree/structural/finite_theorem_certificate.json` | forced linear coordinate, `K5/K7` cover blocks, disjoint cubic constraints |
| Four-vertex optimum landscapes | `certificates/structural/structural_certificate.json` | complete `10/896` census, degree profiles, tree-count rows, and exact product decomposition |
| Four-action canonical payload | `certificates/five_vertex/canonical_payload.json` | orbit counts, profiles, residual pairs, tree classes, conditional extensions |
| Independent payload reconstruction | `scripts/five_vertex/checker/reconstruct.py` and `certificates/five_vertex/independent/reconstructed_payload.json` | independent group generation, orbit evaluation, complete byte identity |
| Five-vertex upper witnesses | `certificates/five_vertex/canonical_payload.json` | explicit separating coordinate supports of cardinalities `14` and `17` |
| Five-vertex global lower bounds | `certificates/five_vertex/branch_dag_S5.json.gz` and `branch_dag_A5.json.gz` | recomputed separator masks and every reachable branch, packing, and coverage node |
| Signed `A5` split channel | `certificates/structural/a5_signed_matrix.csv` and `scripts/five_vertex/checker/reconstruct.py` | independent `54`-by-`35` reconstruction, six ranks, primitive rank-four blind block, and forced parent |
| `A4` exchange graphs | `certificates/structural/structural_certificate.json` and `scripts/verify_structural_certificates.py` | all exchange edges, explicit factor labels, free graded `C2^3` action, and global `896`-vertex product graph |
| Exact statement crosswalk | `certificates/theorem_summary.json` | four-case theorem tuple, residual/tree/conditional rows, and scope ceiling |
| Paper | `paper/main.tex`, included sources, and title-named PDF | theorem wording, bibliography, limits, and layout |
| PDF visual QA | `docs/PDF_VISUAL_QA.json` and `docs/PDF_VISUAL_QA.md` | PASS semantics, exact PDF binding, full page census, render parameters, and exact human-readable projection |
| PDF build environment | `PDF_BUILD_TOOLCHAIN.json` | canonical engine and bibliography processor, command sequence, deterministic environment, and 106 loaded TeX files |
| Package identity | `MANIFEST_SHA256.txt` and `BUILD_ATTESTATION.json` | file set, bytes, PDF/QA/toolchain identity, scope, and event-free build facts |

The aggregate entry point is `scripts/verify.py`.
