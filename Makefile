.PHONY: ontology

# Regenerate src/plg/ontology/generated/ from ontology/ (fails on an invalid ontology or glossary).
ontology:
	uv run python scripts/build_ontology.py
