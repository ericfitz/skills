# tests/test_depscan_k8s.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.report import build_scan
from repobuilder import build_repo

MANIFEST = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  template:
    spec:
      containers:
        - name: server
          image: x:1
          ports:
            - containerPort: 8080
          env:
            - name: DB_PASS
              valueFrom:
                secretKeyRef: { name: db, key: pass }
            - name: API_KEY
              valueFrom:
                secretKeyRef:
                  name: api
                  key: token
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits: { cpu: 2000m, memory: 1Gi }
---
apiVersion: v1
kind: Service
metadata:
  name: web-svc
spec:
  ports:
    - port: 80
      targetPort: 8080
"""

GO = 'type C struct {\n\tA string `yaml:"a" env:"APP_A,required"`\n\tB int `envconfig:"APP_B"`\n}\n'


class K8sScanTest(unittest.TestCase):
    def scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"k8s/web.yml": MANIFEST, "cfg/c.go": GO})
            return build_scan(root)["findings"]

    def test_limits_carry_bound_and_component(self):
        got = {(r["kind"], r["bound"], r["component"], r["raw"])
               for r in self.scan()["resource_limits"]}
        self.assertEqual(got, {("cpu", "request", "server", "100m"),
                               ("memory", "request", "server", "128Mi"),
                               ("cpu", "limit", "server", "2000m"),
                               ("memory", "limit", "server", "1Gi")})

    def test_network_objects_and_container_ports(self):
        net = [(r["kind"], r["name"], r["ports"]) for r in self.scan()["k8s_network"]]
        self.assertIn(("Service", "web-svc", ["80", "8080"]), net)
        self.assertIn(("containerPort", "server", ["8080"]), net)

    def test_secret_refs_flow_and_block(self):
        refs = {(r["env"], r["secret"], r["key"]) for r in self.scan()["secret_refs"]}
        self.assertEqual(refs, {("DB_PASS", "db", "pass"), ("API_KEY", "api", "token")})

    def test_go_env_tags(self):
        tags = {r["name"]: r["mechanism"] for r in self.scan()["env_refs"]}
        self.assertEqual(tags, {"APP_A": "go-struct-tag:env",
                                "APP_B": "go-struct-tag:envconfig"})


if __name__ == "__main__":
    unittest.main()
