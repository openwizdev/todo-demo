#!/bin/sh
set -eu
LC_ALL=C
export LC_ALL

usage() {
    printf '%s\n' 'Usage: launch/reset.sh [OWNER/]NAME' >&2
    exit 2
}

[ "$#" -eq 1 ] || usage
repo=$1
case "$repo" in
    ''|/*|*/|*/*/*|*[!A-Za-z0-9._/-]*) usage ;;
esac
case "${repo##*/}" in
    .|..|-*) usage ;;
esac
case "$repo" in
    */*)
        case "${repo%/*}" in
            -*|*[!A-Za-z0-9-]*) usage ;;
        esac
        ;;
esac

printf 'Create empty private GitHub repository %s using the current gh login.\n' "$repo"
printf '%s' 'Type yes to create it: '
if ! IFS= read -r answer || [ "$answer" != yes ]; then
    printf '\n%s\n' 'Canceled. No repository created.' >&2
    exit 1
fi

GH_HOST=github.com exec gh repo create "$repo" --private
