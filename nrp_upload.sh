#!/bin/bash
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Defaults
REPO_URL="https://workflow-repo.test.du.cesnet.cz/"
DEFAULT_REPO="wfrepo"
DEFAULT_COMMUNITY="generic"

usage() {
    echo "Usage: $0 [-r repository] [-c community] [-p] <title> <file_or_directory>"
    echo
    echo "Options:"
    echo "  -r    Repository alias (default: $DEFAULT_REPO)"
    echo "  -c    Community (default: $DEFAULT_COMMUNITY)"
    echo "  -p    Auto-publish after upload"
    echo "  -d    Description (optional)"
    echo
    echo "Example:"
    echo "  $0 -p 'My Dataset' ./path/to/your/dataset/file"
    echo "  $0 -r wfrepo -c generic -p 'My analysis' ./dataset_folder/"
    exit 1
}

# Parse args
PUBLISH=false
DESCRIPTION=""
REPO="$DEFAULT_REPO"
COMMUNITY="$DEFAULT_COMMUNITY"

while getopts "r:c:pd:h" opt; do
    case $opt in
        r) REPO="$OPTARG" ;;
        c) COMMUNITY="$OPTARG" ;;
        p) PUBLISH=true ;;
        d) DESCRIPTION="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done
shift $((OPTIND-1))

# Validate inputs
if [ $# -lt 2 ]; then
    echo -e "${RED}Error: Title and path required${NC}"
    usage
fi

TITLE="$1"
INPUT_PATH="$2"

if [ ! -e "$INPUT_PATH" ]; then
    echo -e "${RED}Error: Path does not exist: $INPUT_PATH${NC}"
    exit 1
fi

# Check dependencies
if ! command -v nrp-cmd &> /dev/null; then
    echo -e "${RED}Error: nrp-cmd not found${NC}"
    echo "Install: curl -O https://raw.githubusercontent.com/NRP-CZ/nrp-cmd/main/nrp-cmd && chmod +x nrp-cmd && sudo mv nrp-cmd /usr/local/bin/"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 required for safe JSON encoding${NC}"
    exit 1
fi

echo -e "${BLUE}=== NRP Dataset Upload ===${NC}"
echo "Repository: $REPO"
echo "Community: $COMMUNITY"
echo "Title: $TITLE"
echo

# Check/configure repository
if [ -f ~/.nrp/invenio-config.json ] && grep -q "\"$REPO\"" ~/.nrp/invenio-config.json 2>/dev/null; then
    echo -e "${GREEN}✓ Repository '$REPO' configured${NC}"
else
    echo -e "${YELLOW}→ Adding repository '$REPO'...${NC}"
    nrp-cmd add repository "$REPO_URL" "$REPO"
    echo -e "${GREEN}✓ Repository added${NC}"
fi

# Build JSON metadata safely
if [ -n "$DESCRIPTION" ]; then
    JSON=$(python3 -c "import json,sys; print(json.dumps({'title': sys.argv[1], 'description': sys.argv[2]}))" "$TITLE" "$DESCRIPTION")
else
    JSON=$(python3 -c "import json,sys; print(json.dumps({'title': sys.argv[1]}))" "$TITLE")
fi

echo -e "${BLUE}→ Creating record...${NC}"
if ! nrp-cmd create record "$JSON" --repository "$REPO" --community "$COMMUNITY" --set r; then
    echo -e "${RED}✗ Failed to create record${NC}"
    echo "Common fixes:"
    echo "  1. Check you're logged in with your NRP account"
    echo "  2. Remove ~/.nrp/ and re-run to re-authenticate"
    exit 1
fi

echo -e "${GREEN}✓ Record created (stored as @r)${NC}"
echo

# Upload function
upload_item() {
    local file="$1"
    local basename=$(basename "$file")
    local size=$(du -h "$file" 2>/dev/null | cut -f1 || echo "unknown")
    
    echo -e "${BLUE}→ Uploading: $basename (${size})${NC}"
    if nrp-cmd upload file @r "$file" --repository "$REPO"; then
        echo -e "${GREEN}  ✓ Complete${NC}"
    else
        echo -e "${RED}  ✗ Failed${NC}"
        return 1
    fi
}

# Handle file or directory
if [ -f "$INPUT_PATH" ]; then
    upload_item "$INPUT_PATH"
elif [ -d "$INPUT_PATH" ]; then
    echo -e "${BLUE}→ Scanning directory: $INPUT_PATH${NC}"
    find "$INPUT_PATH" -type f | while read -r file; do
        upload_item "$file" || true  # Continue on individual file errors
    done
else
    echo -e "${RED}Error: Not a file or directory${NC}"
    exit 1
fi

echo

# Publish if requested
if [ "$PUBLISH" = true ]; then
    echo -e "${BLUE}→ Publishing record...${NC}"
    if nrp-cmd publish record @r --repository "$REPO"; then
        echo -e "${GREEN}✓ Published successfully${NC}"
    else
        echo -e "${YELLOW}⚠ Publish failed (record remains as draft)${NC}"
        echo "To retry: nrp-cmd publish record @r --repository $REPO"
    fi
else
    echo -e "${YELLOW}→ Record remains as DRAFT${NC}"
    echo "To publish: nrp-cmd publish record @r --repository $REPO"
    echo "View at: $(nrp-cmd get record @r --repository $REPO -f json 2>/dev/null | grep -o 'https://[^\"]*' | head -1 || echo 'URL available via: nrp-cmd get record @r')"
fi

echo
echo -e "${GREEN}Done! Record reference: @r${NC}"
