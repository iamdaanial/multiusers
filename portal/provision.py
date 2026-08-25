import base64
import json
import os
import shutil
import ssl
import stat
import subprocess
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(__file__)
TENANTS_DIR = os.environ.get(
    "TENANTS_DIR", os.path.join(BASE_DIR, "..", "tenants"))
TEMPLATE_FILE = os.path.join(
    TENANTS_DIR, "_template", "docker-compose.yml.tmpl")


def provision_tenant(name, port, password, storage):
    tenant_dir = os.path.join(TENANTS_DIR, name)
    os.makedirs(os.path.join(tenant_dir, "config"), exist_ok=True)
    os.makedirs(os.path.join(tenant_dir, "data"), exist_ok=True)

    with open(os.path.join(tenant_dir, ".env"), "w") as f:
        f.write(f"IDM_ADMIN_PASSWORD={password}\n")

    with open(os.path.join(tenant_dir, "info.txt"), "w") as f:
        f.write(f"{storage}\n{port}\n")

    with open(TEMPLATE_FILE) as f:
        content = f.read()

    content = content.replace("__TENANT__", name)
    content = content.replace("__PORT__", str(port))

    with open(os.path.join(tenant_dir, "docker-compose.yml"), "w") as f:
        f.write(content)

    subprocess.run(
        ["docker", "compose", "run", "--rm", "--entrypoint",
            "ocis", "ocis", "init", "--insecure", "true"],
        cwd=tenant_dir,
    )
    subprocess.run(["docker", "compose", "up", "-d"], cwd=tenant_dir)

    set_quota(port, password, storage)


def _api_request(port, password, method, path, body=None):
    url = f"https://localhost:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None

    request = urllib.request.Request(url, data=data, method=method)
    creds = base64.b64encode(f"admin:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {creds}")
    if body is not None:
        request.add_header("Content-Type", "application/json")

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(request, context=context) as response:
        return json.loads(response.read())


def set_quota(port, password, storage_gb):
    quota_bytes = int(storage_gb) * 1024 * 1024 * 1024

    for attempt in range(15):
        try:
            drives = _api_request(port, password, "GET",
                                  "/graph/v1.0/me/drives")
            break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(2)
    else:
        return

    personal_id = None
    for drive in drives["value"]:
        if drive["driveType"] == "personal":
            personal_id = drive["id"]

    _api_request(
        port, password, "PATCH", f"/graph/v1.0/drives/{personal_id}",
        {"quota": {"total": quota_bytes}},
    )


def _remove_readonly(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def deprovision_tenant(name):
    tenant_dir = os.path.join(TENANTS_DIR, name)
    subprocess.run(["docker", "compose", "down", "-v"], cwd=tenant_dir)

    for attempt in range(5):
        try:
            shutil.rmtree(tenant_dir, onerror=_remove_readonly)
            return
        except OSError:
            time.sleep(1)

    shutil.rmtree(tenant_dir, ignore_errors=True)


def _get_password(name):
    env_path = os.path.join(TENANTS_DIR, name, ".env")
    with open(env_path) as f:
        line = f.readline().strip()
    return line.split("=", 1)[1]


def update_storage(name, port, storage):
    password = _get_password(name)
    set_quota(port, password, storage)

    tenant_dir = os.path.join(TENANTS_DIR, name)
    with open(os.path.join(tenant_dir, "info.txt"), "w") as f:
        f.write(f"{storage}\n{port}\n")


def load_tenants():
    tenants = []
    for name in os.listdir(TENANTS_DIR):
        if name == "_template":
            continue
        info_path = os.path.join(TENANTS_DIR, name, "info.txt")
        if not os.path.exists(info_path):
            continue
        with open(info_path) as f:
            storage = f.readline().strip()
            port = f.readline().strip()
        tenants.append((name, storage, port))
    return tenants
