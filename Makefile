all:
	zip -j ./limit-new-by-young.ankiaddon ./src/*

check:
	ruff check src
	MYPYPATH=src mypy -p src

test:
	./test.py
