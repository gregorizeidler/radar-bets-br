#!/usr/bin/env bash
# Nada para instalar: só biblioteca padrão do Python 3.11+
set -e
python3 -c "import sys; assert sys.version_info >= (3, 11), 'use Python 3.11+'"
echo "pronto"
