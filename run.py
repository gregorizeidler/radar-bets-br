import argparse
import json
import coletor

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=260, help="domínios verificados nesta execução")
    p.add_argument("--workers", type=int, default=14)
    a = p.parse_args()
    d = coletor.rodar(max_verificacoes=a.max, workers=a.workers)
    print(json.dumps(d["funil"], ensure_ascii=False))
