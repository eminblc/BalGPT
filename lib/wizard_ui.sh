#!/usr/bin/env bash
# lib/wizard_ui.sh — whiptail wrappers + text prompt primitives.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

_wt_available() {
  command -v whiptail &>/dev/null && [ -t 0 ] && [ -t 2 ]
}


_wt_radio() {
  local title="$1" msg="$2"; shift 2
  whiptail --title "$title" --radiolist "$msg" 20 70 10 "$@" 3>&1 1>&2 2>&3
}


_wt_input() {
  local title="$1" msg="$2" default="${3:-}"
  whiptail --title "$title" --inputbox "$msg" 10 70 "$default" 3>&1 1>&2 2>&3
}


_wt_password() {
  local title="$1" msg="$2"
  whiptail --title "$title" --inputbox "$msg" 10 70 3>&1 1>&2 2>&3
}


_wt_yesno() {
  local title="$1" msg="$2"
  whiptail --title "$title" --yesno "$msg" 10 70 3>&1 1>&2 2>&3
}


_wt_msg() {
  local title="$1" msg="$2"
  whiptail --title "$title" --msgbox "$msg" 20 70 3>&1 1>&2 2>&3
}


_ask_inline() {
  local _lbl="$1" _var="$2"
  printf "  %s " "$_lbl" > /dev/tty 2>/dev/null || { echo "  $_lbl"; }
  # _var holds the *name* of the destination variable — indirect assignment is
  # intentional. shellcheck flags this since it can't follow indirection.
  # shellcheck disable=SC2229
  IFS= read -r "$_var"
}


_ask_req() {
  local _lbl="$1" _var="$2"
  while true; do
    _ask_inline "$_lbl" "$_var"
    [[ -n "${!_var}" ]] && break
    warn "    $_S_REQUIRED"
  done
}


_ask_secret() {
  local _lbl="$1" _var="$2"
  while true; do
    printf "  %s " "$_lbl" > /dev/tty 2>/dev/null || printf "  %s " "$_lbl"
    # shellcheck disable=SC2229
    IFS= read -rs "$_var"
    echo
    [[ -n "${!_var}" ]] && break
    warn "    $_S_REQUIRED"
  done
}


_sep() { echo ""; echo "  ────────────────────────────────────────────────────"; }

