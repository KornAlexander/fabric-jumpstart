# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# CELL ********************

"""Awesome Rayfin — Fabric Jumpstart wrapper.

One Fabric Jumpstart entry that fronts the *entire* Awesome Rayfin template
gallery. Instead of hard-coding an app list, this module reads the gallery's
own manifest (`rayfin-template.yml`) from GitHub **at run time**, so it always
reflects the latest templates — a new template merged into the gallery shows up
here with no wrapper release.

Two-plane design (a Fabric notebook cannot run the Node/Rayfin CLI):

  * Data plane  — done here, server-side: resolve/create the target workspace
                  context and (optionally) provision the app's declared Fabric
                  prerequisites.
  * App plane   — handed off: emit a ready-to-run, non-interactive deploy
                  command (workspace + tenant pre-filled) to copy and run in a
                  terminal with Node 18+, where the Rayfin CLI belongs.

Usage inside a Fabric notebook::

    %pip install fabric-jumpstart-rayfin --quiet
    import rayfin_jumpstart as rj
    rj.gallery()                       # interactive picker (ipywidgets)
    # or headless:
    print(rj.deploy_command("airport-iq"))
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field

__all__ = ["RayfinApp", "list_apps", "deploy_command", "gallery"]

# --- Source of truth (always the live gallery manifest) --------------------
_OWNER = "microsoft"
_REPO = "awesome-rayfin"
_DEFAULT_REF = "main"

_RAW = "https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
_MANIFEST_PATH = "rayfin-template.yml"
_SERVICE_FLAGS_PATH = "templates/{slug}/manifest.json"
_REPO_URL = f"https://github.com/{_OWNER}/{_REPO}"


@dataclass
class RayfinApp:
    """One template discovered from the live gallery manifest."""

    slug: str                       # folder under templates/ (e.g. "airport-iq")
    name: str
    description: str
    path: str                       # e.g. "templates/airport-iq"
    fabric_auth: bool = True
    fabric_data: bool = False
    stack: list[str] = field(default_factory=list)

    @property
    def template_url(self) -> str:
        return f"{_REPO_URL}/tree/main/{self.path}"


def _fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "rayfin-jumpstart"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
        return resp.read().decode("utf-8")


def _raw_url(path: str, ref: str) -> str:
    return _RAW.format(owner=_OWNER, repo=_REPO, ref=ref, path=path)


def _parse_manifest_entries(yaml_text: str) -> list[dict]:
    """Parse the root rayfin-template.yml `entries:` list.

    Uses PyYAML when available (present in Fabric runtimes); falls back to a
    tiny line parser so the wrapper still works in a bare kernel.
    """
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(yaml_text) or {}
        return list(doc.get("entries", []))
    except Exception:
        return _parse_entries_fallback(yaml_text)


def _parse_entries_fallback(yaml_text: str) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    in_entries = False
    for raw_line in yaml_text.splitlines():
        if raw_line.strip() == "entries:":
            in_entries = True
            continue
        if not in_entries:
            continue
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            if current:
                entries.append(current)
            current = {}
            stripped = stripped[2:]
        if current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            current[key.strip()] = value.strip().strip("'\"")
    if current:
        entries.append(current)
    return entries


def _load_service_flags(slug: str, ref: str) -> tuple[bool, bool]:
    """Read auth/data flags from a template's manifest.json (best-effort)."""
    try:
        text = _fetch_text(_raw_url(_SERVICE_FLAGS_PATH.format(slug=slug), ref))
        services = (json.loads(text) or {}).get("services", {})
        return bool(services.get("auth", True)), bool(services.get("data", False))
    except Exception:
        return True, False


def list_apps(ref: str = _DEFAULT_REF, *, with_flags: bool = True) -> list[RayfinApp]:
    """Return the CURRENT gallery templates, fetched live from the manifest.

    Because this reads `rayfin-template.yml` from the repo at call time, the
    Jumpstart always exposes the latest set of Awesome Rayfin templates.
    """
    manifest = _fetch_text(_raw_url(_MANIFEST_PATH, ref))
    apps: list[RayfinApp] = []
    for entry in _parse_manifest_entries(manifest):
        path = str(entry.get("path", "")).strip()
        slug = path.split("/")[-1] if path else str(entry.get("name", "")).strip()
        if not slug:
            continue
        auth, data = (_load_service_flags(slug, ref) if with_flags else (True, False))
        apps.append(
            RayfinApp(
                slug=slug,
                name=str(entry.get("name", slug)),
                description=str(entry.get("description", "")),
                path=path or f"templates/{slug}",
                fabric_auth=auth,
                fabric_data=data,
            )
        )
    return apps


def deploy_command(name: str, slug: str, workspace_id: str | None = None, tenant_id: str | None = None) -> str:
    """Build the non-interactive Rayfin CLI deploy commands for a template.

    Steps: scaffold into a named folder, cd into it, ensure dependencies are
    installed (the scaffolder auto-installs, but this is a self-healing retry in
    case that step failed), then deploy. `rayfin up` MUST run from inside the
    project folder — that is where the local `rayfin` bin lives (running it
    elsewhere, or before `npm install` succeeds, tries to fetch a non-existent
    `rayfin` npm package and 404s).
    """
    ws = workspace_id or _current_workspace_id() or "<your-workspace-id>"
    tenant = tenant_id or _current_tenant_id() or "<your-tenant-id>"
    return (
        f'npm create @microsoft/rayfin@latest -- {slug} --template {_REPO_URL} --template-name "{name}" --workspace-id {ws}\n'
        f"cd {slug}\n"
        "npm install                       # ensure deps (local rayfin bin) are present\n"
        f"npx rayfin up --workspace-id {ws} --tenant {tenant} -y"
    )


# --- Fabric context (best-effort; safe outside a notebook) ------------------
def _current_workspace_id() -> str | None:
    try:
        import notebookutils  # type: ignore

        return notebookutils.runtime.context.get("currentWorkspaceId")
    except Exception:
        return None


def _current_tenant_id() -> str | None:
    # 1. Notebook runtime context (key name varies across runtimes).
    try:
        import notebookutils  # type: ignore

        ctx = notebookutils.runtime.context
        for key in ("tenantId", "tenantObjectId", "currentTenantId"):
            val = ctx.get(key)
            if val:
                return val
    except Exception:
        pass
    # 2. Decode the `tid` claim from a Fabric access token.
    try:
        import base64
        import notebookutils  # type: ignore

        token = notebookutils.credentials.getToken("pbi")
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("tid")
    except Exception:
        return None


def _card_md(app: RayfinApp) -> str:
    tags = " · ".join(
        t for t in ["Auth" if app.fabric_auth else None, "Data" if app.fabric_data else None] if t
    )
    return (
        f"### {app.name}\n{app.description}\n\n"
        f"**Fabric:** {tags or '—'} · [Template]({app.template_url})\n\n"
        "**Deploy this app** — copy the commands (hover the box → copy icon) and run them\n"
        "in a terminal with Node 18+ (local, Azure Cloud Shell, or a Codespace):\n"
        f"```bash\n{deploy_command(app.name, app.slug)}\n```\n---"
    )


def gallery(ref: str = _DEFAULT_REF) -> None:
    """Render the WHOLE live gallery inside the notebook (one card per template).

    Falls back to a printed catalog when IPython is unavailable.
    """
    apps = list_apps(ref)
    try:
        from IPython.display import Markdown, display  # type: ignore
    except Exception:
        _print_catalog(apps)
        return

    ws = _current_workspace_id() or "<your-workspace-id>"
    tn = _current_tenant_id() or "<your-tenant-id>"
    header = (
        f"# Rayfin App Gallery\n"
        f"**{len(apps)} templates** · workspace `{ws}` · tenant `{tn}`\n\n---"
    )
    display(Markdown(header + "\n\n" + "\n\n".join(_card_md(a) for a in apps)))


def _print_catalog(apps: list[RayfinApp]) -> None:
    print(f"Awesome Rayfin gallery — {len(apps)} template(s):\n")
    for a in apps:
        print(f"• {a.name} ({a.slug})\n    {a.description}\n    {deploy_command(a.name, a.slug)}\n")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Rayfin App Gallery — lists every Awesome Rayfin template (live) with a
# ready-to-run deploy command; workspace + tenant are auto-filled.
gallery()

