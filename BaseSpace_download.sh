#!/usr/bin/env bash
set -euo pipefail

# ── Prompt for Project ID ────────────────────────────────────────────────────
read -rp "Enter BaseSpace Project ID: " PROJECT_ID
if [[ -z "$PROJECT_ID" ]]; then
    echo "Error: Project ID cannot be empty." >&2
    exit 1
fi

OUTPUT_DIR="/mnt/data"

# ── Confirm and run ──────────────────────────────────────────────────────────
echo ""
echo "  Project ID : $PROJECT_ID"
echo "  Output dir : $OUTPUT_DIR"
echo "  Log file   : download.log"
echo ""
read -rp "Start download? [y/N]: " CONFIRM
if [[ "${CONFIRM,,}" != "y" ]]; then
    echo "Aborting." >&2
    exit 1
fi

echo "Downloading... (see download.log for details)"
./bs download project -i "$PROJECT_ID" -o "$OUTPUT_DIR" > download.log 2>&1
echo "Done. Output written to '$OUTPUT_DIR'."
