#!/usr/bin/env zsh

function gc() {
  git clone "ssh://git@github.com/alphagov/${1}.git" "${HOME}/govuk/${1}"
}