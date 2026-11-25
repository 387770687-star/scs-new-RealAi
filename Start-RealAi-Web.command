#!/bin/zsh
set -e
repo_dir="${0:A:h}"
exec zsh "$repo_dir/Start-RealAi-Dev.command" --no-electron "$@"
