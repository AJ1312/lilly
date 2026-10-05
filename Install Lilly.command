#!/bin/bash
# Double-click this file on a Mac to install Lilly.
cd "$(dirname "$0")" || exit 1
./install.sh
status=$?
echo
read -r -p "Press Return to close this window. "
exit $status
