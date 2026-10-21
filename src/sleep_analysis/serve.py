"""Servidor local para abrir os relatórios de data/reports no navegador."""

import argparse
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

from sleep_analysis.paths import REPORTS_DIR

HOST = "127.0.0.1"
PORTS = range(8765, 8775)
PAGE = "comparativo.html"
# Marca que só a página comparativa tem; distingue o nosso servidor de outro na mesma porta
PAGE_MARKER = b'id="report-data"'
START_TIMEOUT_S = 5.0


def serves_report(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/{PAGE}", timeout=1) as response:
            return response.status == 200 and PAGE_MARKER in response.read()
    except OSError:
        return False


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # Como o http.server, aceita porta em TIME_WAIT de um servidor que acabou de sair
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def ensure_server() -> int:
    """Reaproveita um servidor que já serve a página ou sobe outro, solto do terminal."""
    for port in PORTS:
        if serves_report(port):
            return port
        if not port_is_free(port):
            continue
        subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", HOST, "--directory", str(REPORTS_DIR)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if serves_report(port):
                return port
            time.sleep(0.2)
        raise RuntimeError(f"O servidor não respondeu na porta {port}")
    raise RuntimeError(f"Nenhuma porta livre entre {PORTS.start} e {PORTS.stop - 1}")


def report_url(port: int) -> str:
    # O parâmetro muda a cada geração e evita que o navegador mostre a versão em cache
    return f"http://{HOST}:{port}/{PAGE}?v={datetime.now():%Y%m%d%H%M%S}"


def main() -> None:
    argparse.ArgumentParser(description="Sobe (ou reaproveita) o servidor local e imprime o link do relatório").parse_args()
    if not (REPORTS_DIR / PAGE).exists():
        sys.exit(f"{REPORTS_DIR / PAGE} não existe; rode uv run sleep-report antes.")
    print(f"Abrir no navegador: {report_url(ensure_server())}")


if __name__ == "__main__":
    main()
