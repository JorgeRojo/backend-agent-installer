#!/usr/bin/env bash
# ui.sh — Colors and feedback helpers.
# Sourced by install.sh. No side effects on source.
# shellcheck disable=SC2059  # printf format strings are intentional.

red() { printf '\033[1;91m✗ %s\033[0m\n' "$*"; }
green() { printf '\033[0;92m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;93m%s\033[0m\n' "$*"; }
cyan() { printf '\033[0;96m%s\033[0m\n' "$*"; }
dim() { printf '\033[2;37m%s\033[0m\n' "$*"; }
bold() { printf '\033[1m%s\033[0m\n' "$*"; }

# Section header — bold magenta with a marker.
step() { printf '\n\033[1;95m▶ %s\033[0m\n' "$*"; }
