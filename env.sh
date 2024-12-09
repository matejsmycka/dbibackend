#!/bin/bash

PYTHON=""
function get_python {
    if [ -z "$PYTHON" ]; then
        PYTHON=$(which python3)
        if [ -z "$PYTHON" ]; then
            PYTHON=$(which python)
            if [ -z "$PYTHON" ]; then
                echo "Python or Python3 is required"
                exit 1
            fi
        fi
    fi
}

function check_venv {
    if [ ! -d "venv" ]; then
    echo "Creating virtual environment"
        $PYTHON -m venv venv
        source venv/bin/activate
        pip install .
        echo "Dependencies installed"
        deactivate
    fi
}


get_python
check_venv
source venv/bin/activate
python dbibackend/dbi.py --help

echo ""
echo "Now you can use the dbi command"

alias dbi="python $(pwd)/dbibackend/dbi.py"
