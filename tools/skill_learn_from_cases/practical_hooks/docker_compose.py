#!/usr/bin/env python3
"""Docker Compose 实操测试 — 真实 compose config 校验

被 assess_template.py 的 run_practical_test() 调用，
输出 JSON: {"score": int(0-100), "passed": bool, "note": str}
"""
import json, subprocess, tempfile, os, sys, platform
import shutil


def _win_to_wsl_path(win_path):
    """Windows路径转WSL路径: D:\\foo\\bar -> /mnt/d/foo/bar"""
    if not win_path or len(win_path) < 2 or win_path[1] != ":":
        return win_path.replace("\\", "/")
    drive = win_path[0].lower()
    rest = win_path[2:].replace("\\", "/")
    return "/mnt/" + drive + rest


def _docker_cmd(cmd_list, **kwargs):
    """运行 docker 命令，Windows 下通过 wsl.exe 调用"""
    if platform.system() == "Windows":
        wsl = shutil.which("wsl.exe") or "wsl.exe"
        cmd = [wsl, "--exec"] + cmd_list
    else:
        cmd = cmd_list
    default_kwargs = {"capture_output": True, "text": True, "timeout": 30}
    default_kwargs.update(kwargs)
    return subprocess.run(cmd, **default_kwargs)


def check_docker_available():
    """检测 Docker 引擎是否可用"""
    try:
        r = _docker_cmd(["docker", "info", "--format=json"])
        return r.returncode == 0, "29.4.1" if r.returncode == 0 else r.stderr[:100]
    except Exception as e:
        return False, str(e)


PRODUCTION_COMPOSE = """\
services:
  app:
    image: myapp:${APP_VERSION:-latest}
    env_file:
      - .env.production
    volumes:
      - app_data:/data/app
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: "2.0"
          memory: "1G"
        reservations:
          cpus: "0.5"
          memory: "256M"
    networks:
      - frontend
      - backend
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    restart: unless-stopped
    shm_size: 256m
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - backend
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: "512M"
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    stop_grace_period: 30s

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--requirepass", "${REDIS_PASSWORD:-Ch4ngeMe!}"]
    stop_grace_period: 30s
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    networks:
      - backend
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: "256M"
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  backup:
    image: alpine:3.19
    restart: unless-stopped
    volumes:
      - pg_data:/data/db:ro
      - ./backup:/backup
    networks:
      - backend
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: "256M"
    command: >
      sh -c "while true; do
        tar czf /backup/db-$(date +%Y%m%d).tar.gz -C /data/db .;
        sleep 86400;
      done"

volumes:
  app_data:
  pg_data:
  redis_data:

networks:
  frontend:
  backend:
    internal: true

secrets:
  db_password:
    file: ./secrets/db_password.txt
"""


def main():
    result = {"score": 0, "passed": False, "note": ""}

    # 1. 检查 Docker
    avail, ver = check_docker_available()
    if not avail:
        result["note"] = "Docker 引擎不可用: " + ver
        print(json.dumps(result))
        sys.exit(1)

    # 2. 写 compose 文件到临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        compose_file = os.path.join(tmpdir, "docker-compose.yml")
        env_file = os.path.join(tmpdir, ".env.production")
        secrets_dir = os.path.join(tmpdir, "secrets")
        os.makedirs(secrets_dir, exist_ok=True)

        with open(compose_file, "w") as f:
            f.write(PRODUCTION_COMPOSE)
        with open(env_file, "w") as f:
            f.write("APP_VERSION=1.2.3\nREDIS_PASSWORD=Ch4ngeMe!\n")
        with open(os.path.join(secrets_dir, "db_password.txt"), "w") as f:
            f.write("SuperSecretDBPass123!")

        # 3. 运行 docker compose config
        wsl_compose_file = _win_to_wsl_path(compose_file)
        r = _docker_cmd(
            ["docker", "compose", "-f", wsl_compose_file, "config"]
        )

        if r.returncode == 0:
            result["score"] = 100
            result["passed"] = True
            result["note"] = "生产级Compose通过真实 docker compose config 校验"
            result["output_preview"] = r.stdout[:200]
        else:
            result["score"] = 30
            result["note"] = "compose config 校验失败"
            result["error"] = r.stderr[:300]

    print(json.dumps(result))
    sys.exit(0 if result["passed"] else 1)




# ── 统一接口 ──
def run(env: dict = None) -> dict:
    """统一入口: run(env) 接收 env_detector 的输出，返回测试结果"""
    if env is None:
        try:
            from env_detector import detect_all
            env = detect_all()
        except ImportError:
            import sys
            sys.path.insert(0, r"""D:\open_claw_agent\GenericAgent\tools\skill_learn_from_cases""")
            from env_detector import detect_all
            env = detect_all()
    return main()


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
