MAIN = main

all:
	latexmk -pdf $(MAIN).tex

clean:
	latexmk -C $(MAIN).tex
	rm -f *.bbl *.blg *.log *.aux *.out *.toc *.fls *.fdb_latexmk *.synctex.gz
