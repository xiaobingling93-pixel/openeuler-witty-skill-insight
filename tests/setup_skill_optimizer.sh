#!/bin/bash

# Setup script for skill-optimizer testing
# This script copies skill-optimizer to .opencode/skills directory

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SKILL_SOURCE="$PROJECT_ROOT/skills/skill-optimizer"
SKILL_TARGET="$PROJECT_ROOT/.opencode/skills/skill-optimizer"

echo "=========================================="
echo "  Skill Optimizer Setup Script"
echo "=========================================="
echo ""

# Check if source exists
if [ ! -d "$SKILL_SOURCE" ]; then
    echo "❌ Error: skill-optimizer source not found at:"
    echo "   $SKILL_SOURCE"
    exit 1
fi

if [ ! -f "$SKILL_SOURCE/SKILL.md" ]; then
    echo "❌ Error: SKILL.md not found in skill-optimizer"
    exit 1
fi

# Create target directory if not exists
mkdir -p "$PROJECT_ROOT/.opencode/skills"

# Remove old version if exists
if [ -d "$SKILL_TARGET" ]; then
    echo "🔄 Removing existing skill-optimizer..."
    rm -rf "$SKILL_TARGET"
fi

# Copy skill
echo "📦 Copying skill-optimizer to .opencode/skills/..."
cp -r "$SKILL_SOURCE" "$SKILL_TARGET"

# Verify
if [ -f "$SKILL_TARGET/SKILL.md" ]; then
    echo ""
    echo "✅ Setup complete!"
    echo ""
    echo "  Source: $SKILL_SOURCE"
    echo "  Target: $SKILL_TARGET"
    echo ""
    echo "=========================================="
    echo "  Next Steps"
    echo "=========================================="
    echo ""
    echo "  1. Restart opencode to load the skill:"
    echo "     Exit current session and run 'opencode' again"
    echo ""
    echo "  2. Test the skill:"
    echo "     opencode run '帮我优化 /path/to/your/skill'"
    echo ""
    echo "  3. Or test interactively in opencode session:"
    echo "     > 帮我优化这个 skill: /path/to/skill"
    echo ""
else
    echo "❌ Error: Failed to copy skill-optimizer"
    exit 1
fi
