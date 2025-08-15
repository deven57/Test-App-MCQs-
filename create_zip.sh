#!/usr/bin/env bash
# Helper script: runs from project root and zips the project into quiz_store.zip
zip -r quiz_store.zip . -x "*.git/*" -x "venv/*"
echo "Created quiz_store.zip"
