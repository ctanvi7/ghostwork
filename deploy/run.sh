#!/bin/bash
# Lambda entry: the Lambda Web Adapter layer (/opt/bootstrap) forwards each
# Function URL request to this waitress server on $PORT.
export PYTHONPATH="/var/task:${PYTHONPATH}"
exec python3 -m waitress --listen="127.0.0.1:${PORT:-8080}" --threads=4 api.index:app
