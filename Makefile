all:
	zip -j ./limit-new-by-young.ankiaddon ./src/*

check:
	ruff check
