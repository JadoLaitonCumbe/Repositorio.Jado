"""Basic concurrent health-endpoint smoke test; not a full business/load certification."""
import argparse
import concurrent.futures
import time
import urllib.error
import urllib.request


def check(url, timeout):
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read()
            return response.status, time.perf_counter() - start, len(body)
    except Exception:
        return 0, time.perf_counter() - start, 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1: raise SystemExit("requests e concurrency devem ser positivos")
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda _: check(args.url, args.timeout), range(args.requests)))
    elapsed = time.perf_counter() - start
    ok = [r for r in results if r[0] == 200]
    latencies = sorted(r[1] for r in results)
    p95 = latencies[min(len(latencies)-1, int(len(latencies)*0.95))]
    print(f"Pedidos: {args.requests}; concorrência: {args.concurrency}; HTTP 200: {len(ok)}; erros: {len(results)-len(ok)}")
    print(f"Duração: {elapsed:.2f}s; throughput: {len(results)/elapsed:.2f} req/s; latência p95: {p95*1000:.1f} ms")
    if len(ok) != len(results): raise SystemExit(1)
    print("NOTA: teste limitado ao endpoint /health; não substitui testes de carga de login, sincronização, BD e fluxos financeiros.")

if __name__ == "__main__": main()
