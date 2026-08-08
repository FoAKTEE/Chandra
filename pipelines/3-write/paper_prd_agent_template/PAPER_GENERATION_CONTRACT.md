# Paper Generation Contract for Repository-to-Paper Agent

This file is the controlling instruction document for an agent that reads a code repository, generated figures, logs, tables, and experiment outputs, then writes a complete LaTeX paper. The required output is a PRD-style REVTeX manuscript with a modular section layout.

The agent must treat this document as normative. When there is a conflict between informal instructions elsewhere and this file, follow this file.

## Required output

The agent must generate or update the following files:

```text
main.tex
macros.tex
bibliography.bib
sections/abstract.tex
sections/introduction.tex
sections/related_work.tex
sections/method.tex
sections/experiments.tex
sections/results.tex
sections/discussion.tex
sections/conclusion.tex
sections/appendix.tex
figures/<repository-generated-figures>
```

The file `main.tex` must be the only top-level LaTeX driver. Every manuscript section must live in a separate `.tex` file under `sections/`. The `main.tex` file must unify the paper using `\input{sections/<name>.tex}`.

## Default paper format

Use a Physical Review D / APS REVTeX layout by default:

```latex
\documentclass[aps,prd,amsmath,floats,floatfix,onecolumn,compact,superscriptaddress,nofootinbib]{revtex4-2}
```

The manuscript must be one-column and compact. The `compact` option is included in the class declaration, and compactness must also be implemented by reduced display, float, and paragraph spacing in `main.tex`, not by merging sections or omitting necessary explanations. If a local REVTeX installation treats `compact` as an unused option, the explicit spacing controls in `main.tex` still enforce the compact layout.

The style should follow the attached example structurally: `\pdfoutput=1` in the first lines, REVTeX class declaration, package preamble, macros, `\begin{document}`, title block, abstract, `\maketitle`, labeled sections, bibliography, and optional appendix.

## Repository-reading requirements

Before writing the paper, the agent must inspect the repository and extract:

1. The scientific or technical problem being solved.
2. The main method, algorithm, model, theorem, system, or experimental pipeline.
3. The dataset, simulation, benchmark, or physical setup.
4. The generated figures and what each figure demonstrates.
5. Tables, metrics, ablations, logs, parameter sweeps, or configuration files.
6. Limitations, failure cases, assumptions, and reproducibility details.
7. Existing citations from README files, comments, notebooks, papers, or metadata.

The agent must not fabricate numerical claims. Any result stated in the paper must be traceable to a repository file, generated figure, table, log, or explicit user-provided instruction. If a claim is plausible but not directly supported, mark it as `\TODO{verify}` rather than presenting it as fact.

## Introduction constraints

`sections/introduction.tex` has a hard structure:

1. Paragraph 1: broad motivation and context.
2. Paragraph 2: concrete gap, challenge, or unresolved problem.
3. Paragraph 3: what this paper does, the key contribution, and what each section covers.

The introduction must contain exactly these three paragraphs. Do not use subsections, itemized lists, tables, or figures in the introduction unless explicitly requested. Keep the introduction concise.

## Section requirements

Use the following default section order unless the repository clearly requires a different scholarly organization:

```latex
\input{sections/introduction.tex}
\input{sections/related_work.tex}
\input{sections/method.tex}
\input{sections/experiments.tex}
\input{sections/results.tex}
\input{sections/discussion.tex}
\input{sections/conclusion.tex}
```

Each section must begin with a section command and a stable label:

```latex
\section{Method}
\label{sec:method}
```

Recommended label names are:

```text
sec:introduction
sec:related_work
sec:method
sec:experiments
sec:results
sec:discussion
sec:conclusion
sec:appendix
```

## Figure policy

All generated figures must be placed under `figures/`. The default width for every figure is exactly `0.8\columnwidth`.

Use this macro unless there is a strong reason not to:

```latex
\paperfig{figure_file.pdf}{Caption text.}{fig:descriptive_label}
```

The macro expands to:

```latex
\includegraphics[width=0.8\columnwidth]{...}
```

Use a different width only when required by the figure geometry, and leave a LaTeX comment explaining why.

Every figure caption must answer three questions: what is plotted, how it was produced, and what conclusion the reader should draw. Do not write captions that merely restate the filename.

## Writing rules

Write in the style of a technical research paper. Use precise language, define notation before using it, and avoid unsupported superlatives. When using code-derived terminology, map repository names to publication-quality terms. For example, convert raw script names into method descriptions, but preserve exact names when needed for reproducibility.

The paper must include enough detail for a reader to reproduce the main results from the repository. Hyperparameters, simulation settings, benchmark versions, model sizes, numerical tolerances, random seeds, and hardware should appear in `sections/experiments.tex` or an appendix when available.

## Citation rules

Use BibTeX entries in `bibliography.bib`. Do not invent citations. If the repository suggests a source but lacks a full citation, add a placeholder entry with a clear key and mark the nearby claim with `\TODO{complete citation}`.

The bibliography style must remain PRD/APS-compatible by default:

```latex
\bibliographystyle{apsrev4-2}
\bibliography{bibliography}
```

## Abstract rules

`sections/abstract.tex` must be a single paragraph unless the target venue explicitly allows structured abstracts. It should state the problem, the method, the principal result, and the significance. Avoid citations in the abstract unless unavoidable.

## Result integration rules

For each generated figure, the agent must decide one of the following:

1. Include it in the main paper.
2. Include it in the appendix.
3. Exclude it and explain why in a generation note or TODO comment.

Main-paper figures must be referenced in the text before or near their appearance using `Fig.~\ref{fig:...}`. Tables must be referenced using `Table~\ref{tab:...}`.

## Final validation checklist

Before returning the paper, the agent must verify:

- `main.tex` compiles as the single driver.
- Every manuscript section is a separate `.tex` file in `sections/`.
- The introduction has exactly three paragraphs as specified.
- All figures use `0.8\columnwidth` by default.
- Every figure and table has a label and is referenced in text.
- Every citation key used in `.tex` exists in `bibliography.bib`.
- No unsupported numerical claim appears without a repository source.
- The paper uses PRD, one-column, compact defaults.

## Minimal agent prompt

When asking an agent to write the paper, use:

```text
Read PAPER_GENERATION_CONTRACT.md first. Then inspect the repository, figures, logs, and tables. Generate a complete PRD-style one-column compact LaTeX paper using main.tex as the driver and separate section files under sections/. Preserve the required introduction structure. Use 0.8\columnwidth as the default figure width. Do not fabricate results or citations; mark unsupported items with TODOs.
```
