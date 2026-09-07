#!/usr/bin/env python3
"""Read an OpenShift Route public hostname from the in-cluster API."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
API = "https://kubernetes.default.svc/apis/route.openshift.io/v1"


def route_host(name: str, timeout_sec: int = 120) -> str:
    namespace = open(f"{SA_DIR}/namespace", encoding="utf-8").read().strip()
    token = open(f"{SA_DIR}/token", encoding="utf-8").read().strip()
    url = f"{API}/namespaces/{namespace}/routes/{name}"
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"}
        )
        try:
            with urllib.request.urlopen(
                request, cafile=f"{SA_DIR}/ca.crt", timeout=5
            ) as response:
                data = json.load(response)
            ingress = data.get("status", {}).get("ingress") or []
            if ingress and ingress[0].get("host"):
                return ingress[0]["host"]
            spec_host = data.get("spec", {}).get("host")
            if spec_host:
                return spec_host
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                time.sleep(2)
                continue
            raise
        except OSError:
            time.sleep(2)

    return ""


def main() -> int:
    route_name = sys.argv[1] if len(sys.argv) > 1 else "agent-dashboard"
    host = route_host(route_name)
    if host:
        print(host, end="")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
