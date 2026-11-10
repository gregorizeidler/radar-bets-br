# Radar Bets BR

Monitoramento diário de domínios de apostas no Brasil, com cruzamento contra a
lista oficial de operadoras autorizadas pelo SPA/Ministério da Fazenda.

**Site:** https://gregorizeidler.github.io/radar-bets-br

## O que roda todo dia

O workflow `.github/workflows/diario.yml` executa às 06:00 (Brasília):

1. baixa a lista oficial de autorizadas da página do SPA/MF (85 empresas, 185 domínios);
2. baixa **três índices públicos de domínios vivos** — Tranco, Majestic Million e Cisco Umbrella (2,4 milhões de domínios) — e filtra por nome com cara de aposta;
3. consulta o Certificate Transparency (crt.sh) para domínios com certificado novo;
4. resolve DNS e faz **um** GET na página inicial de cada candidato — sem login, sem
   cadastro, sem acessar tela de depósito;
5. pontua sinais de casa de aposta no HTML, calcula a impressão digital do kit
   (hash dos arquivos estáticos + título), extrai IDs de Google Analytics/GTM e Pixel;
6. agrupa domínios em operações por IP dedicado, nameserver, kit e analytics;
7. mede meia-vida e rotação com o histórico acumulado;
8. grava `docs/dados/atual.json`, `docs/dados/dominios.csv` e o histórico do dia.

## Rodar localmente

```bash
python3 run.py --max 300 --workers 16
python3 -m http.server 8000 --directory docs   # abre http://localhost:8000
```

Cada execução verifica 2.500 domínios novos (8s por lote de 250, estado salvo a cada lote).
Só biblioteca padrão do Python 3.11+. Nenhuma chave de API.

## Rótulos

| rótulo | significado |
|---|---|
| `autorizada` | domínio listado na página oficial do SPA/MF |
| `clone_de_autorizada` | nome igual ou a 1 caractere de uma marca autorizada, em domínio que não é o oficial |
| `sem_registro` | tem cara de casa de aposta e não está na lista oficial |

**Candidato suspeito não é prova de ilegalidade.** Site internacional que não atua no
Brasil também cai em `sem_registro`. O que prova situação legal é a lista oficial de
autorizadas e a lista de bloqueio da Anatel — esta última não existe em arquivo aberto
até hoje, e por isso o projeto não a usa.

## Limites conhecidos

- Nenhuma fonte pública entrega "centenas de milhares de bets ilegais por dia". O que o
  radar entrega é um universo de candidatos que cresce a cada varredura.
- Só a home é lida; site que monta tudo em JavaScript rende menos sinais.
- O crt.sh devolve 502 com frequência; o coletor tenta de novo e usa a data do
  certificado mais recente como referência, não o relógio da máquina.
- IP de CDN (Cloudflare, CloudFront, AWS, GCP) não conta para agrupar operações.
- A meia-vida só fica confiável depois de algumas semanas de histórico.

## Estrutura

```
fontes.py    lista oficial, crt.sh, DNS-over-HTTPS, GET na home
analise.py   sinais de aposta, kit, analytics, parecido com marca, clusters
coletor.py   pipeline e saída do site
run.py       entrada
docs/        site estático (GitHub Pages)
data/        estado acumulado e histórico (versionado pelo próprio workflow)
tests/       testes da análise
```
