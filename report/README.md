# TenderWorks B.Tech. Project Report

This folder contains a new LaTeX report based on the IIT Jodhpur BTP report template and the Tenderworks project source.

## Before submission

Edit the metadata commands near the top of `main.tex`:

- `\authorname`
- `\rn`
- `\supname`
- `\deptname`

Review the declaration, certificate, acknowledgements, and all claims about scope and evaluation before submitting.

## Build

With a LaTeX installation that includes `pdflatex` and BibTeX:

```text
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

The report uses the bundled IIT Jodhpur logo and `IEEEtran.bst`. Project examples and prices are synthetic; the report explicitly describes this limitation.
