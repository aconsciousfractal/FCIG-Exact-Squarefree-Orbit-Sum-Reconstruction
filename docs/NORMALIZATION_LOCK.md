# Mathematical normalization and canonical encoding

This file fixes the common model used by the manuscript, generators, and
checkers. It is normative for every distributed certificate.

## Carrier and actions

For `n in {4,5}`, the carrier is

```text
Omega_n = {(i,j) : 0 <= i,j < n and i != j}.
```

A pattern is a Boolean subset of `Omega_n`, equivalently a loopless simple
directed graph. The scientific groups are `S_n` and `A_n`, acting by
simultaneous vertex relabelling:

```text
g.(i,j) = (g(i),g(j)).
```

Scientific equivalence is orbit equivalence under the named group only.
Complementation, arc transpose, and relabellings outside that group are not
part of the quotient.

## Canonical pattern encoding

Arcs are ordered lexicographically by source and then target, omitting loops.
Bit `k` records membership of the `k`-th arc. A group orbit is represented by
the least unsigned bitmask in that orbit. Hexadecimal masks are lowercase and
fixed-width: three digits for `n=4`, five for `n=5`.

Pattern identifiers have the form

```text
GROUP:n:mask
```

where `GROUP` is one of `S4,A4,S5,A5`.

## Squarefree orbit-sum coordinates

A degree-`d` support is a `d`-element subset of distinct arcs. It represents
the squarefree monomial formed from those arcs. Supports are quotiented by the
same named vertex action and canonically represented by the least unsigned
support mask. Coordinate identifiers have the form

```text
GROUP:n:d:mask
```

Coordinates are ordered first by degree and then by canonical support mask.
For a Boolean pattern `P` and support orbit `R`, the integer evaluation is

```text
a_R(P) = number of distinct T in R with T subset of P.
```

Reciprocal arcs are distinct variables. No factorial or stabilizer
normalization is applied.

## Cumulative signatures and minima

The degree-`d` signature uses every coordinate orbit of degrees `1` through
`d`. The reconstruction degree is the least `d` for which this signature is
injective on pattern orbits.

For a fixed cumulative dictionary, each unordered pair of pattern orbits
defines the set of coordinates that separate it. A separating fingerprint is
a hitting set for all such pair-separation sets. Its global minimum is taken
inside that fixed dictionary only.

The conditional extension problem is different: every coordinate below the
top degree is retained, and only the number of added top-degree coordinates is
minimized.

## Tree and index-two terminology

A top-degree coordinate is tree-supported when the underlying undirected
simple support is connected on all `n` vertices and has `n-1` edges. This
classification does not merge reciprocal arcs in the monomial itself.

An `A_n` pair is called an index-two split pair when its two `A_n` pattern
orbits lie in one `S_n` orbit. This is a finite group-action term and carries
no physical interpretation. Canonical payloads encode this property with the
field `index_two_split_pair`; the associated index and count fields use the
same terminology.

## Canonical JSON

Canonical payloads use UTF-8 JSON, lexicographically sorted object keys,
compact separators, integer-valued finite data, and one trailing line feed.
Independent reconstructions are compared on the complete canonical payload,
not only on a summary verdict.
