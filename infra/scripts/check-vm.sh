#!/usr/bin/env bash
# Rode logo que entrar na VM: mostra o que existe e o que falta.
echo "== Sistema =="
lsb_release -ds 2>/dev/null || head -1 /etc/os-release
echo "== Recursos =="
echo "CPUs: $(nproc)"; free -h | sed -n 2p; df -h / | tail -1
echo "== Docker =="
docker --version 2>&1
docker compose version 2>&1
if id -nG | tr ' ' '\n' | grep -qx docker; then
  echo "usuário no grupo docker: sim"
else
  echo "usuário no grupo docker: NÃO (use sudo, ou: sudo usermod -aG docker \$USER e relogue)"
fi
echo "== Portas internas (8080 = proxy/front, 8028 = API) =="
if command -v ss >/dev/null 2>&1; then
  for p in 8080 8028; do
    if ss -ltn | grep -q ":$p "; then echo "$p: EM USO"; else echo "$p: livre"; fi
  done
else
  echo "comando ss não encontrado: não deu para checar as portas"
fi
echo "== Git =="
git --version
echo "== IPs da máquina =="
hostname -I
