#!/bin/bash
# macOS: double-click to start OpenMC Studio. It opens in your browser.
# To stop Studio, press Ctrl+C in this window or close it.
cd "$(dirname "$0")" || exit 1
bash "./studio/start.sh"
status=$?
if [ $status -ne 0 ]; then
  echo
  read -r -p "Studio didn't start (see above). Press Return to close this window."
fi
