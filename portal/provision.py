import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request

from kubernetes import client, config

NAMESPACE = os.environ.get("NAMESPACE", "default")
OCIS_IMAGE = os.environ.get("OCIS_IMAGE", "owncloud/ocis:8.0.1")
MANAGED_BY = "multiusers-portal"

try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

core = client.CoreV1Api()
apps = client.AppsV1Api()


def _app_name(name):
    return "ocis-" + name.lower()


def _labels(app_name):
    return {"app": app_name, "managed-by": MANAGED_BY}


def _env(app_name, port):
    return [
        {"name": "OCIS_URL", "value": f"https://localhost:{port}"},
        {"name": "OCIS_INSECURE", "value": "true"},
        {"name": "PROXY_HTTP_ADDR", "value": f"0.0.0.0:{port}"},
        {"name": "PROXY_ENABLE_BASIC_AUTH", "value": "true"},
        {"name": "OCIS_CONFIG_DIR", "value": "/etc/ocis"},
        {"name": "OCIS_BASE_DATA_PATH", "value": "/var/lib/ocis"},
        {
            "name": "IDM_ADMIN_PASSWORD",
            "valueFrom": {
                "secretKeyRef": {"name": app_name, "key": "IDM_ADMIN_PASSWORD"}
            },
        },
    ]


def _mounts():
    return [
        {"name": "config", "mountPath": "/etc/ocis"},
        {"name": "data", "mountPath": "/var/lib/ocis"},
    ]


def _pvc(pvc_name, app_name, size_gb):
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": pvc_name, "labels": _labels(app_name)},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": f"{size_gb}Gi"}},
        },
    }


def _deployment(name, app_name, port, storage):
    env = _env(app_name, port)
    mounts = _mounts()
    labels = _labels(app_name)

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": app_name,
            "labels": labels,
            "annotations": {
                "tenant-name": name,
                "tenant-storage": str(storage),
                "tenant-port": str(port),
            },
        },
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": app_name}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "securityContext": {"runAsUser": 0, "runAsGroup": 0},
                    "initContainers": [
                        {
                            "name": "init",
                            "image": OCIS_IMAGE,
                            "command": [
                                "sh", "-c",
                                "ocis init --insecure true || true",
                            ],
                            "env": env,
                            "volumeMounts": mounts,
                        }
                    ],
                    "containers": [
                        {
                            "name": "ocis",
                            "image": OCIS_IMAGE,
                            "args": ["server"],
                            "env": env,
                            "ports": [{"containerPort": port}],
                            "volumeMounts": mounts,
                        }
                    ],
                    "volumes": [
                        {
                            "name": "config",
                            "persistentVolumeClaim": {
                                "claimName": f"{app_name}-config"
                            },
                        },
                        {
                            "name": "data",
                            "persistentVolumeClaim": {
                                "claimName": f"{app_name}-data"
                            },
                        },
                    ],
                },
            },
        },
    }


def _service(app_name, port):
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": app_name, "labels": _labels(app_name)},
        "spec": {
            "selector": {"app": app_name},
            "ports": [{"port": port, "targetPort": port}],
        },
    }


def provision_tenant(name, port, password, storage):
    app_name = _app_name(name)

    core.create_namespaced_secret(
        NAMESPACE,
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": app_name, "labels": _labels(app_name)},
            "stringData": {"IDM_ADMIN_PASSWORD": password},
        },
    )

    core.create_namespaced_persistent_volume_claim(
        NAMESPACE, _pvc(f"{app_name}-config", app_name, 1))
    core.create_namespaced_persistent_volume_claim(
        NAMESPACE, _pvc(f"{app_name}-data", app_name, storage))

    apps.create_namespaced_deployment(
        NAMESPACE, _deployment(name, app_name, int(port), storage))
    core.create_namespaced_service(NAMESPACE, _service(app_name, int(port)))

    set_quota(name, port, password, storage)


def _api_request(name, port, password, method, path, body=None):
    host = f"{_app_name(name)}.{NAMESPACE}.svc.cluster.local"
    url = f"https://{host}:{port}{path}"
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


def set_quota(name, port, password, storage_gb):
    quota_bytes = int(storage_gb) * 1024 * 1024 * 1024

    for attempt in range(60):
        try:
            drives = _api_request(name, port, password, "GET",
                                  "/graph/v1.0/me/drives")
            break
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(2)
    else:
        return

    personal_id = None
    for drive in drives["value"]:
        if drive["driveType"] == "personal":
            personal_id = drive["id"]

    _api_request(
        name, port, password, "PATCH", f"/graph/v1.0/drives/{personal_id}",
        {"quota": {"total": quota_bytes}},
    )


def _delete(delete_call, *args):
    try:
        delete_call(*args, NAMESPACE)
    except client.ApiException as error:
        if error.status != 404:
            raise


def deprovision_tenant(name):
    app_name = _app_name(name)

    _delete(apps.delete_namespaced_deployment, app_name)
    _delete(core.delete_namespaced_service, app_name)
    _delete(core.delete_namespaced_secret, app_name)
    _delete(core.delete_namespaced_persistent_volume_claim,
            f"{app_name}-config")
    _delete(core.delete_namespaced_persistent_volume_claim,
            f"{app_name}-data")


def _get_password(name):
    secret = core.read_namespaced_secret(_app_name(name), NAMESPACE)
    return base64.b64decode(secret.data["IDM_ADMIN_PASSWORD"]).decode()


def update_storage(name, port, storage):
    password = _get_password(name)
    set_quota(name, port, password, storage)

    apps.patch_namespaced_deployment(
        _app_name(name), NAMESPACE,
        {"metadata": {"annotations": {"tenant-storage": str(storage)}}},
    )


def load_tenants():
    tenants = []
    deployments = apps.list_namespaced_deployment(
        NAMESPACE, label_selector=f"managed-by={MANAGED_BY}")

    for deployment in deployments.items:
        annotations = deployment.metadata.annotations or {}
        name = annotations.get("tenant-name")
        if not name:
            continue
        tenants.append((
            name,
            annotations.get("tenant-storage", ""),
            annotations.get("tenant-port", ""),
        ))

    tenants.sort()
    return tenants
