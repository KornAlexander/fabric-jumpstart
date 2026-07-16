# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {}
# META }

# MARKDOWN ********************

# # 🚀 Rayfin App Gallery
# 
# **Deploy a full [Awesome Rayfin](https://github.com/microsoft/awesome-rayfin) app into your Fabric workspace — straight from this notebook.**
# 
# This gallery reads the Awesome Rayfin template manifest **live from GitHub every time you run it**, so it always shows the latest apps — no notebook update needed when a new template ships.
# 
# ## How it works
# 
# A Fabric notebook can't run the Node / Rayfin CLI itself, so deployment happens in two planes:
# 
# | Plane | Where | What happens |
# | --- | --- | --- |
# | 🗄️ **Data** | here, server-side | resolves your current workspace + tenant and pre-fills them into every command |
# | 🖥️ **App** | your terminal | the Rayfin CLI scaffolds the source, installs dependencies, builds and uploads the app to Fabric |
# 
# ## What you need
# 
# - **Node.js 18+** and **npm** on the machine where you run the commands — local, Azure Cloud Shell, or a Codespace
# - Access to the target Fabric workspace (this notebook fills in its id automatically)
# 
# ## How to use it
# 
# 1. Run the cell below — it renders one card per app.
# 2. Pick an app and copy its numbered commands (hover a code box → click the copy icon).
# 3. Paste them into a terminal and run them **one at a time**, or use the single chained command for a one-shot paste.

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
    rj.gallery()                       # render every app as a card
    # or headless (four commands, run one at a time):
    print(rj.deploy_command("Airport IQ", "airport-iq"))
    # or as a single chained one-liner:
    print(rj.deploy_command_chained("Airport IQ", "airport-iq"))
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field

__all__ = ["RayfinApp", "list_apps", "deploy_command", "deploy_command_chained", "gallery"]

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
    fabric_storage: bool = False
    fabric_static: bool = True
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


def _load_service_flags(slug: str, ref: str) -> dict[str, bool]:
    """Read the Fabric services a template declares from its manifest.json.

    Best-effort: returns the declared `services` block (auth / data / storage /
    static hosting). These describe what the Rayfin CLI provisions into the
    workspace when the app is deployed, so the gallery can show it per app.
    """
    default = {"auth": True, "data": False, "storage": False, "static": True}
    try:
        text = _fetch_text(_raw_url(_SERVICE_FLAGS_PATH.format(slug=slug), ref))
        services = (json.loads(text) or {}).get("services", {})
        return {
            "auth": bool(services.get("auth", True)),
            "data": bool(services.get("data", False)),
            "storage": bool(services.get("storage", False)),
            "static": bool(services.get("staticHosting", True)),
        }
    except Exception:
        return default


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
        svc = (
            _load_service_flags(slug, ref)
            if with_flags
            else {"auth": True, "data": False, "storage": False, "static": True}
        )
        apps.append(
            RayfinApp(
                slug=slug,
                name=str(entry.get("name", slug)),
                description=str(entry.get("description", "")),
                path=path or f"templates/{slug}",
                fabric_auth=svc["auth"],
                fabric_data=svc["data"],
                fabric_storage=svc["storage"],
                fabric_static=svc["static"],
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


def _deploy_steps(name: str, slug: str, ws: str, tenant: str) -> list[tuple[str, str]]:
    """The four ordered commands to get one app into a workspace.

    Each is a standalone shell command meant to be run **one at a time** from a
    terminal with Node 18+. Scaffolding into the named `{slug}` folder makes the
    subsequent `cd` deterministic (no guessing the folder the CLI created).
    """
    return [
        (
            "Scaffold the app",
            f'npm create @microsoft/rayfin@latest -- {slug} --template {_REPO_URL} --template-name "{name}" --workspace-id {ws}',
        ),
        ("Enter the project folder", f"cd {slug}"),
        ("Install dependencies", "npm install"),
        ("Deploy to your Fabric workspace", f"npx rayfin up --workspace-id {ws} --tenant {tenant} -y"),
    ]


def deploy_command_chained(name: str, slug: str, workspace_id: str | None = None, tenant_id: str | None = None) -> str:
    """Same four steps as :func:`deploy_command`, chained into ONE line.

    Uses ``&&`` so the chain stops at the first failing step — a convenient
    single paste for when you don't want to run the commands individually.
    """
    ws = workspace_id or _current_workspace_id() or "<your-workspace-id>"
    tenant = tenant_id or _current_tenant_id() or "<your-tenant-id>"
    return " && ".join(cmd for _, cmd in _deploy_steps(name, slug, ws, tenant))


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


def _deploys(app: RayfinApp) -> str:
    """Human summary of the Fabric items this app adds to the workspace.

    Derived live from the app's declared services, so it reflects what the
    Rayfin CLI actually provisions on `rayfin up` (app-dependent).
    """
    parts: list[str] = []
    if app.fabric_static:
        parts.append("a static web app")
    if app.fabric_data:
        parts.append("a SQL data model")
    if app.fabric_storage:
        parts.append("Lakehouse file storage")
    if app.fabric_auth:
        parts.append("Entra SSO")
    return ", ".join(parts) if parts else "the app"


def _card_md(app: RayfinApp, ws: str, tenant: str) -> str:
    """Render one app as a styled card: badges, numbered steps, one-shot line."""
    auth = "`Fabric auth ✓`" if app.fabric_auth else "`Local auth`"
    data = "`SQL data model ✓`" if app.fabric_data else "`No data model`"
    badges = f"{auth} · {data}"

    steps = _deploy_steps(app.name, app.slug, ws, tenant)
    step_md = "\n".join(
        f"**{i} · {title}**\n```bash\n{cmd}\n```"
        for i, (title, cmd) in enumerate(steps, start=1)
    )
    chained = deploy_command_chained(app.name, app.slug, ws, tenant)

    return (
        f"### 📦 {app.name}\n"
        f"{app.description}\n\n"
        f"{badges} · 🔗 [View on GitHub]({app.template_url})\n\n"
        f"🧩 **Deploys to your workspace:** {_deploys(app)}.\n\n"
        "**Get this app into your workspace** — run these four commands **one at a time** "
        "in a terminal with Node.js 18+ (local, Azure Cloud Shell, or a Codespace). "
        "Hover a code box and click the copy icon.\n\n"
        f"{step_md}\n\n"
        "**Prefer a single paste?** Run all four chained — it stops if any step fails:\n"
        f"```bash\n{chained}\n```\n"
        "---"
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
        "# 🚀 Rayfin App Gallery\n"
        f"Deploy a full [Awesome Rayfin]({_REPO_URL}) app into your Fabric workspace. "
        "This list is generated **live** from the gallery manifest, so it always "
        "reflects the latest templates.\n\n"
        f"**{len(apps)} apps** · workspace `{ws}` · tenant `{tn}`\n\n"
        "> **How it works** — a Fabric notebook can't run the Node / Rayfin CLI, so each "
        "card hands you a ready-to-run deploy command (workspace + tenant pre-filled). "
        "Copy it, run it in a terminal with **Node.js 18+**, and the Rayfin CLI scaffolds, "
        "builds and uploads the app to your workspace.\n\n---"
    )
    display(Markdown(header + "\n\n" + "\n\n".join(_card_md(a, ws, tn) for a in apps)))


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

