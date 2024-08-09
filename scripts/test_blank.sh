#!/usr/bin/env bash
set -euo pipefail

# $JAILMAKER_DIR -> Jailmaker directory (also current working dir)
# $TEMPLATES -> path to project templates directory

# Side-effects are a problem. We can't sandbox network settings,
# etc. and we can only clean up ZFS if no jails are left running.


sudo -E ./jlmkr create blankjail

sudo -E ./jlmkr list

sudo -E ./jlmkr start blankjail

sudo -E ./jlmkr list

sudo -E ./jlmkr stop blankjail

echo blankjail | sudo -E ./jlmkr remove blankjail

sudo -E ./jlmkr list
