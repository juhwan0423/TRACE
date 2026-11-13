#!/usr/bin/env bash
# Password goes directly from the local dialog to OpenSSH; never stored.
exec /usr/bin/zenity --password --title="Spark SSH 로그인 · juhwan@100.73.59.16" --text="${1:-Spark SSH password}"
