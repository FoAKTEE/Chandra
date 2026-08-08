# PRD One-Column Compact Paper Template

This directory is a ready-to-use scaffold for generating a paper from a code repository and its generated figures.

Start by reading `PAPER_GENERATION_CONTRACT.md` — the single normative file of rules the writing agent must follow. (`PAPER_TEMPLATE.md` is a thin alias that points to it.)

## Files

- `PAPER_GENERATION_CONTRACT.md`: the enforceable instructions for the writing agent.
- `PAPER_TEMPLATE.md`: stable alias → `PAPER_GENERATION_CONTRACT.md`.
- `AGENTS.md`: short pointer for code agents that automatically read repository guidance.
- `main.tex`: single LaTeX driver.
- `macros.tex`: shared commands, including the default figure macro using `0.8\columnwidth`.
- `sections/`: one `.tex` file per manuscript section.
- `figures/`: repository-generated figures.
- `bibliography.bib`: BibTeX database.
- `reference/example_paper.tex`: uploaded PRD-style example for structural reference only.

## Build

Run:

```bash
make
```

or directly:

```bash
latexmk -pdf main.tex
```

If `latexmk` is unavailable, run:

```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```
