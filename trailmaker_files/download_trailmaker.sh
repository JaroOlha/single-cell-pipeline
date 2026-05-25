#!/bin/bash
set -euo pipefail

CONFIG_FILE="${HOME}/single-cell-pipeline/trailmaker_files/trailmaker_config"
source "$CONFIG_FILE"

for var in COGNITO_CLIENT_ID COGNITO_REFRESH_TOKEN COGNITO_REGION; do
    if [ -z "${!var:-}" ]; then
        echo "Error: $var not set in $CONFIG_FILE" >&2
        exit 1
    fi
done

if ! command -v jq &> /dev/null; then
    echo "Error: jq is required." >&2
    exit 1
fi

# --- Get Fresh Token ---
echo "Refreshing Cognito token..."
AUTH_PAYLOAD=$(jq -n \
    --arg cid "$COGNITO_CLIENT_ID" \
    --arg ref "$COGNITO_REFRESH_TOKEN" \
    '{AuthFlow: "REFRESH_TOKEN_AUTH", ClientId: $cid, AuthParameters: {REFRESH_TOKEN: $ref}}')

AUTH_RESPONSE=$(curl -s -X POST "https://cognito-idp.${COGNITO_REGION}.amazonaws.com/" \
    -H "X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth" \
    -H "Content-Type: application/x-amz-json-1.1" \
    -d "$AUTH_PAYLOAD")

AUTH_TOKEN=$(echo "$AUTH_RESPONSE" | jq -r '.AuthenticationResult.IdToken // empty')
if [ -z "$AUTH_TOKEN" ] || [ "$AUTH_TOKEN" = "null" ]; then
    echo "❌ Refresh token expired or invalid." >&2
    echo "   Action required:" >&2
    echo "   1. Open TrailMaker in browser" >&2
    echo "   2. Click bookmarklet" >&2
    echo "   3. Paste output into: $CONFIG_FILE" >&2
    exit 1
fi

# --- List Samples Command ---
if [ "$1" = "list" ]; then
    EXP_ID="$2"
    [ -z "$EXP_ID" ] && echo "Usage: $0 list <experiment-id>" && exit 1
    
    echo "Samples for experiment $EXP_ID:"
    echo ""
    curl -s -H "Authorization: Bearer $AUTH_TOKEN" \
        "https://api.app.trailmaker.parsebiosciences.com/v2/experiments/${EXP_ID}/samples" \
        | jq -r '.[] | "\(.id)\t\(.name // "unnamed")"'
    
    exit 0
fi

# --- Download All Command ---
if [ "$1" = "download-all" ]; then
    EXP_ID="$2"
    OUTPUT_DIR="${3:-./trailmaker_downloads}"
    FORMAT="${4:-h5ad}"  # Default to h5ad, can be "seurat"
    
    [ -z "$EXP_ID" ] && echo "Usage: $0 download-all <experiment-id> [output-dir] [format]" && exit 1
    
    mkdir -p "$OUTPUT_DIR"
    SCRIPT_PATH="$(readlink -f "$0")"
    
    echo "=== Downloading all files for experiment $EXP_ID ===" >&2
    echo "Output directory: $OUTPUT_DIR" >&2
    echo "Format: $FORMAT" >&2
    echo "" >&2
    
    # Get list of samples
    echo "Fetching sample list..." >&2
    SAMPLES_RESPONSE=$(curl -s \
        -H "Authorization: Bearer $AUTH_TOKEN" \
        "https://api.app.trailmaker.parsebiosciences.com/v2/experiments/${EXP_ID}/samples")
    
    SAMPLE_IDS=$(echo "$SAMPLES_RESPONSE" | jq -r '.[].id')
    
    if [ -z "$SAMPLE_IDS" ]; then
        echo "Error: No samples found for experiment $EXP_ID" >&2
        exit 1
    fi
    
    echo "Found $(echo "$SAMPLE_IDS" | wc -l | tr -d ' ') sample(s)" >&2
    echo "" >&2
    
    # Download main object (h5ad or seurat)
    if [ "$FORMAT" = "seurat" ]; then
        echo "=== Downloading Seurat object (.rds) ===" >&2
        "$SCRIPT_PATH" "$EXP_ID" seurat "${OUTPUT_DIR}/${EXP_ID}_processed_seurat.rds"
    else
        echo "=== Downloading h5ad (processed matrix) ===" >&2
        # Try h5ad first, fallback to seurat if it fails
        if ! "$SCRIPT_PATH" "$EXP_ID" h5ad "${OUTPUT_DIR}/${EXP_ID}_processed_matrix.h5ad" 2>/dev/null; then
            echo "⚠️ h5ad not available, trying Seurat format..." >&2
            "$SCRIPT_PATH" "$EXP_ID" seurat "${OUTPUT_DIR}/${EXP_ID}_processed_seurat.rds"
        fi
    fi
    echo "" >&2
    
    # Download per-sample files
    for SAMPLE_ID in $SAMPLE_IDS; do
        echo "=== Sample: $SAMPLE_ID ===" >&2
        
        for FILE_TYPE in mtx meta genes; do
            case "$FILE_TYPE" in
                mtx)  EXT="mtx.gz" ;;
                meta) EXT="csv.gz" ;;
                genes) EXT="csv.gz" ;;
            esac
            
            OUTPUT_FILE="${OUTPUT_DIR}/${EXP_ID}_${SAMPLE_ID}_${FILE_TYPE}.${EXT}"
            echo "Downloading ${FILE_TYPE}..." >&2
            "$SCRIPT_PATH" "$EXP_ID" "$FILE_TYPE" "$OUTPUT_FILE" "$SAMPLE_ID"
        done
        
        echo "" >&2
    done
    
    echo "=== All downloads complete ===" >&2
    echo "Files saved to: $OUTPUT_DIR" >&2
    ls -lh "$OUTPUT_DIR" >&2
    exit 0
fi

# --- Download Command (individual file) ---
if [ "$#" -lt 2 ]; then
    echo "Usage:" >&2
    echo "  $0 <experiment-id> <file-type> [output-filename] [sample-id]" >&2
    echo "  $0 download-all <experiment-id> [output-dir] [format]" >&2
    echo "  $0 list <experiment-id>" >&2
    echo "" >&2
    echo "File types:" >&2
    echo "  h5ad   - Processed matrix (no sample-id needed)" >&2
    echo "  seurat - Seurat object .rds (no sample-id needed)" >&2
    echo "  mtx    - Count matrix (requires sample-id)" >&2
    echo "  meta   - Cell metadata (requires sample-id)" >&2
    echo "  genes  - All genes (requires sample-id)" >&2
    echo "" >&2
    echo "Formats: h5ad (default) or seurat" >&2
    exit 1
fi

EXPERIMENT_ID="$1"
FILE_TYPE="$2"
OUTPUT_FILE="${3:-}"
SAMPLE_ID="${4:-}"

WORKREQUEST_URL="https://api.app.trailmaker.parsebiosciences.com/v2/workRequest/${EXPERIMENT_ID}/check"

case "$FILE_TYPE" in
    h5ad)
        PAYLOAD_NAME="DownloadAnnotSeuratObject"
        DEFAULT_EXT="h5ad"
        API_TYPE="workRequest"
        FILE_PATH=""
        IS_SEURAT="false"
        MATRIX_TYPE="wt"
        ;;
    seurat)
        PAYLOAD_NAME="DownloadAnnotSeuratObject"
        DEFAULT_EXT="rds"
        API_TYPE="workRequest"
        FILE_PATH=""
        IS_SEURAT="true"
        MATRIX_TYPE="wt"
        ;;
    mtx)
        if [ -z "$SAMPLE_ID" ]; then
            echo "Error: 'mtx' requires sample-id as 4th argument" >&2
            exit 1
        fi
        DEFAULT_EXT="mtx.gz"
        API_TYPE="direct"
        FILE_PATH="matrixParse"
        ;;
    meta)
        if [ -z "$SAMPLE_ID" ]; then
            echo "Error: 'meta' requires sample-id as 4th argument" >&2
            exit 1
        fi
        DEFAULT_EXT="csv.gz"
        API_TYPE="direct"
        FILE_PATH="barcodesParse"
        ;;
    genes)
        if [ -z "$SAMPLE_ID" ]; then
            echo "Error: 'genes' requires sample-id as 4th argument" >&2
            exit 1
        fi
        DEFAULT_EXT="csv.gz"
        API_TYPE="direct"
        FILE_PATH="featuresParse"
        ;;
    *)
        echo "Error: Unknown file type '$FILE_TYPE'" >&2
        exit 1
        ;;
esac

if [ -z "$OUTPUT_FILE" ]; then
    if [ "$API_TYPE" = "direct" ]; then
        OUTPUT_FILE="${EXPERIMENT_ID}_${SAMPLE_ID}_${FILE_TYPE}.${DEFAULT_EXT}"
    else
        OUTPUT_FILE="${EXPERIMENT_ID}_processed_matrix.${DEFAULT_EXT}"
    fi
fi

# --- Get Download URL ---
SIGNED_URL=""

if [ "$API_TYPE" = "direct" ]; then
    # Direct GET for mtx, meta, genes
    FILE_URL="https://api.app.trailmaker.parsebiosciences.com/v2/experiments/${EXPERIMENT_ID}/samples/${SAMPLE_ID}/files/${FILE_PATH}/downloadUrl"
    
    echo "Fetching ${FILE_TYPE} download URL..."
    
    RAW_RESPONSE=$(curl -s \
	-H "Host: api.app.trailmaker.parsebiosciences.com" \
        -H "Authorization: Bearer $AUTH_TOKEN" \
        -H "Accept: application/json" \
        -H "Origin: https://app.trailmaker.parsebiosciences.com" \
        -H "Referer: https://app.trailmaker.parsebiosciences.com/" \
        "$FILE_URL")
    
    SIGNED_URL=$(echo "$RAW_RESPONSE" | jq -r '.')
    
    if [ -z "$SIGNED_URL" ] || [ "$SIGNED_URL" = "null" ] || [[ ! "$SIGNED_URL" =~ ^https:// ]]; then
        echo "Error: Invalid URL in response" >&2
        echo "Response: $RAW_RESPONSE" >&2
        exit 1
    fi
else
    # h5ad/seurat - direct URL response (no polling needed)
    PAYLOAD=$(jq -n \
        --arg exp "$EXPERIMENT_ID" \
        --arg name "$PAYLOAD_NAME" \
        --arg isSeurat "$IS_SEURAT" \
        --arg matrixType "$MATRIX_TYPE" \
        --arg fileName "${EXPERIMENT_ID}_processed_matrix.${DEFAULT_EXT}" \
        '{
          experimentId: $exp,
          body: {
            name: $name,
            embeddingMethod: "umap",
            isSeurat: ($isSeurat == "true"),
            matrixType: $matrixType
          },
          requestProps: {
            broadcast: false,
            cacheUniquenessKey: null
          },
          fileName: $fileName
        }')
    
    echo "Requesting download URL (${FILE_TYPE})..." >&2
    
    RESPONSE=$(curl -s \
        -X POST "$WORKREQUEST_URL" \
	-H "Host: api.app.trailmaker.parsebiosciences.com" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json" \
        -H "Origin: https://app.trailmaker.parsebiosciences.com" \
        -H "Referer: https://app.trailmaker.parsebiosciences.com/" \
        -H "Authorization: Bearer $AUTH_TOKEN" \
        -d "$PAYLOAD")
    
    SIGNED_URL=$(echo "$RESPONSE" | jq -r '.signedUrl // empty')
    
    if [ -z "$SIGNED_URL" ] || [ "$SIGNED_URL" = "null" ]; then
        echo "Error: No signedUrl in response for ${FILE_TYPE}" >&2
        echo "Response was: $RESPONSE" >&2
        exit 1
    fi
fi

# --- Download ---
echo "Downloading $OUTPUT_FILE ..."
curl -f -L --progress-bar -o "$OUTPUT_FILE" "$SIGNED_URL"

#if [[ "$OUTPUT_FILE" == *.gz ]]; then
#    echo "Decompressing..."
#    gunzip -k "$OUTPUT_FILE"
#    echo "Done: ${OUTPUT_FILE%.gz} (kept .gz as well)"
#else
#    echo "Done: $OUTPUT_FILE"
#fi
