# Manuscript

The source in this directory builds the single unified four- and five-vertex
paper. It contains only manuscript content and publication-neutral metadata.

Build from the repository root:

```text
python scripts/build_paper.py
```

The canonical byte-identical environment is fixed in
`PDF_BUILD_TOOLCHAIN.json`. Check both output bytes and toolchain identity with:

```text
python -B scripts/build_paper.py --check-byte-identical --check-toolchain-lock
```

The stable output is:

```text
paper/Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf
```

Figures and tables are TeX-native, author-generated objects. No third-party
image or article PDF is included.
