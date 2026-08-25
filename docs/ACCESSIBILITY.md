# Accessibility notes

The manuscript is text-based and its figures and tables are generated in TeX,
so mathematical labels remain selectable in the PDF. Color is used only as a
secondary organizational cue; the four theorem-panel boxes and certificate
diagram also carry explicit text labels.

The repository provides the complete manuscript source, plain-text claim
boundary, reviewer guide, and machine-readable certificate data. Commands and
expected endpoints are duplicated in `REPRODUCE.md` rather than being encoded
only in figures.

The PDF is checked for encryption, attachments, unsafe active actions,
consistent page geometry, an English language declaration, text extraction,
and embedded fonts. An all-page rendered review is recorded separately in
`docs/PDF_VISUAL_QA.md`.

The distributed PDF is not claimed to be a structurally tagged PDF. Readers
who require a reflowable or machine-oriented representation should use the
LaTeX source and the plain-text or JSON surfaces listed above. This limitation
is explicit; selectable text and successful extraction do not substitute for
semantic tagging.
