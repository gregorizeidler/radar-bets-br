import argparse
import json
import os
import sys
import coletor

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=2000, help="domínios verificados nesta execução")
    p.add_argument("--workers", type=int, default=24)
    a = p.parse_args()
    d = coletor.rodar(max_verificacoes=a.max, workers=a.workers)
    print(json.dumps(d["funil"], ensure_ascii=False))
    sys.stdout.flush()
    # thread presa em conexão não deve segurar o fim do job
    os._exit(0)
