#!/usr/bin/env bash
set -euo pipefail

# ── Prompt for Project ID ────────────────────────────────────────────────────
read -rp "Enter BaseSpace Project ID: " PROJECT_ID
if [[ -z "$PROJECT_ID" ]]; then
    echo "Error: Project ID cannot be empty." >&2
    exit 1
fi

OUTPUT_DIR="/mnt/data/$PROJECT_ID"   # per-project subdir → accurate size readings
mkdir -p "$OUTPUT_DIR"

# ── Confirm and run ──────────────────────────────────────────────────────────
echo ""
echo "  Project ID : $PROJECT_ID"
echo "  Output dir : $OUTPUT_DIR"
echo ""
read -rp "Start download? [y/N]: " CONFIRM
if [[ "${CONFIRM,,}" != "y" ]]; then
    echo "Aborting." >&2
    exit 1
fi

# ── Download in background, show live status ─────────────────────────────────
./bs download project -i "$PROJECT_ID" -o "$OUTPUT_DIR" > download.log 2>&1 &
BS_PID=$!

SPINNER=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
i=0
PREV=0
SECONDS=0

tput civis 2>/dev/null || true                 # hide cursor
trap 'tput cnorm 2>/dev/null || true' EXIT     # restore it on exit

while kill -0 "$BS_PID" 2>/dev/null; do
    SIZE=$(du -sb "$OUTPUT_DIR" 2>/dev/null | cut -f1); SIZE=${SIZE:-0}
    FILES=$(find "$OUTPUT_DIR" -type f 2>/dev/null | wc -l)
    RATE=$(( SIZE - PREV )); PREV=$SIZE
    LAST=$(tail -n 1 download.log 2>/dev/null)

    printf '\r\033[K %s %8s | %s files | %8s/s | %02d:%02d | %.45s' \
        "${SPINNER[i]}" \
        "$(numfmt --to=iec "$SIZE")" \
        "$FILES" \
        "$(numfmt --to=iec "$RATE")" \
        $((SECONDS / 60)) $((SECONDS % 60)) \
        "$LAST"

    i=$(( (i + 1) % ${#SPINNER[@]} ))
    sleep 1
done

if wait "$BS_PID"; then
    printf '\r\033[K✔ Done. Output written to %s\n' "$OUTPUT_DIR"
    rm -f download.log
else
    printf '\r\033[K✘ Download failed — see download.log\n' >&2
    exit 1
fi
