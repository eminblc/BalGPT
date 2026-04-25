#!/usr/bin/env bash
# lib/log.sh — Logging primitives — used by every other module.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

log()  { echo "[install] $*"; }

ok()   { echo "[✓] $*"; }

warn() { echo "[!] $*"; }

die()  { echo "[✗] $*" >&2; exit 1; }

