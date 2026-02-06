#!/bin/bash
#
# Deploy coach application to production environment
# Usage: ./bin/deploy-prod.sh /path/to/production/directory
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the script's directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check for production directory argument
if [ -z "$1" ]; then
    echo -e "${RED}Error: Production directory not specified${NC}"
    echo ""
    echo "Usage: $0 /path/to/production/directory"
    echo ""
    echo "Example:"
    echo "  $0 /home/user/coach-prod"
    echo "  $0 ~/production/coach"
    exit 1
fi

PROD_DIR="$1"

# Expand tilde if present
PROD_DIR="${PROD_DIR/#\~/$HOME}"

# Convert to absolute path
PROD_DIR="$(cd "$(dirname "$PROD_DIR")" 2>/dev/null && pwd)/$(basename "$PROD_DIR")" 2>/dev/null || PROD_DIR="$1"

# Safety check: don't deploy to the dev directory
if [ "$PROD_DIR" = "$PROJECT_ROOT" ]; then
    echo -e "${RED}Error: Production directory cannot be the same as development directory${NC}"
    exit 1
fi

# IMPORTANT: Never overwrite production database
# coach.db contains user data and must be preserved
PROTECTED_FILES="coach.db"

echo -e "${GREEN}Deploying coach to production...${NC}"
echo "  Source: $PROJECT_ROOT"
echo "  Target: $PROD_DIR"
echo ""

# Create production directory if it doesn't exist
if [ ! -d "$PROD_DIR" ]; then
    echo -e "${YELLOW}Creating production directory...${NC}"
    mkdir -p "$PROD_DIR"
fi

# Function to sync a directory
sync_dir() {
    local src="$1"
    local dest="$2"
    local name="$3"

    if [ -d "$src" ]; then
        echo "  Syncing $name..."
        mkdir -p "$dest"
        rsync -a --delete \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='*.pyo' \
            --exclude='coach.db' \
            --exclude='*.db' \
            "$src/" "$dest/"
    fi
}

# Function to copy a file (with database protection)
copy_file() {
    local src="$1"
    local dest="$2"
    local name="$3"

    # Never copy database files
    if [[ "$src" == *.db ]]; then
        echo -e "  ${RED}Skipping database file: $name (protected)${NC}"
        return 0
    fi

    if [ -f "$src" ]; then
        echo "  Copying $name..."
        cp "$src" "$dest"
    fi
}

echo -e "${GREEN}Copying production files...${NC}"
echo -e "${YELLOW}(Protecting production database - coach.db will NOT be overwritten)${NC}"
echo ""

# Copy source code
sync_dir "$PROJECT_ROOT/src" "$PROD_DIR/src" "src/"

# Copy public assets
sync_dir "$PROJECT_ROOT/public" "$PROD_DIR/public" "public/"

# Copy bin scripts (excluding this deploy script and dev-only scripts)
echo "  Syncing bin/..."
mkdir -p "$PROD_DIR/bin"
for script in "$PROJECT_ROOT/bin/"*; do
    script_name="$(basename "$script")"
    # Skip deploy script and ingestion script (dev-only)
    if [ "$script_name" != "deploy-prod.sh" ] && [ "$script_name" != "ingest_plans.py" ]; then
        cp "$script" "$PROD_DIR/bin/"
        chmod +x "$PROD_DIR/bin/$script_name"
    fi
done

# Copy requirements.txt
copy_file "$PROJECT_ROOT/requirements.txt" "$PROD_DIR/requirements.txt" "requirements.txt"

# Copy LLM exercise plan format (needed for plan generation in production)
copy_file "$PROJECT_ROOT/exercise_plan_format.md" "$PROD_DIR/exercise_plan_format.md" "exercise_plan_format.md"

# Create a minimal production requirements file (without test dependencies)
echo "  Creating production requirements..."
grep -v -E '^(pytest|httpx|pytest-cov|pytest-asyncio)' "$PROJECT_ROOT/requirements.txt" > "$PROD_DIR/requirements-prod.txt" 2>/dev/null || true

echo ""
echo -e "${GREEN}Deployment complete!${NC}"
echo ""
echo -e "${YELLOW}Next steps for production setup:${NC}"
echo ""
echo "  1. Create virtual environment:"
echo "     cd $PROD_DIR"
echo "     python3 -m venv venv"
echo "     source venv/bin/activate"
echo ""
echo "  2. Install dependencies:"
echo "     pip install -r requirements-prod.txt"
echo ""
echo "  3. Start the server:"
echo "     ./bin/server.sh start"
echo ""
echo "  4. (Optional) Set up as a systemd service for auto-restart"
echo ""
echo "  5. Configure MCP in Claude Desktop:"
echo "     Add to ~/.config/claude-desktop/claude_desktop_config.json:"
echo "     {"
echo "       \"mcpServers\": {"
echo "         \"coach\": {"
echo "           \"command\": \"$PROD_DIR/venv/bin/python\","
echo "           \"args\": [\"-m\", \"coach_mcp\"],"
echo "           \"env\": {\"COACH_DB_PATH\": \"$PROD_DIR/coach.db\"}"
echo "         }"
echo "       }"
echo "     }"
echo ""

# Check if database exists in production
if [ -f "$PROD_DIR/coach.db" ]; then
    echo -e "${YELLOW}Note: Existing coach.db found in production (preserved)${NC}"
else
    echo -e "${YELLOW}Note: No coach.db found - will be created on first run${NC}"
fi
