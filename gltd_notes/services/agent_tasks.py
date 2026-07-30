"""Agent tasks: describe work for grok / gemini / opencode-deepseek4."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from gltd_notes.services.app_context import AppContext
from gltd_notes.services.notes import NotesService
from gltd_notes.utils.hashing import new_entity_id

AGENTS = ("grok", "gemini", "opencode-deepseek4")
STATUSES = ("pending", "running", "done", "failed", "skipped")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def empty_agent_body(
    description: str = "",
    agent: str = "grok",
    parent_id: Optional[str] = None,
) -> str:
    data = {
        "version": 1,
        "description": description or "",
        "agent": agent if agent in AGENTS else "grok",
        "status": "pending",
        "output": "",
        "executed_at": None,
        "parent_id": parent_id,
        "related_ids": [],
        "subtasks": [],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def parse_agent_body(body: Optional[str]) -> Dict[str, Any]:
    if not body or not body.strip():
        return json.loads(empty_agent_body())
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            return json.loads(empty_agent_body(str(body)))
    except json.JSONDecodeError:
        return json.loads(empty_agent_body(body))
    data.setdefault("version", 1)
    data.setdefault("description", "")
    data.setdefault("agent", "grok")
    data.setdefault("status", "pending")
    data.setdefault("output", "")
    data.setdefault("executed_at", None)
    data.setdefault("parent_id", None)
    data.setdefault("related_ids", [])
    data.setdefault("subtasks", [])
    if data["agent"] not in AGENTS:
        data["agent"] = "grok"
    if data["status"] not in STATUSES:
        data["status"] = "pending"
    return data


def serialize_agent(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


_CLI_ARGS = {
    "grok": ["grok", "-p", "{prompt}", "--always-approve", "--output-format", "json"],
    "gemini": ["gemini", "-p", "{prompt}"],
    "opencode": ["opencode", "run", "--auto", "--pure", "{prompt}"],
}


def _find_cli(name: str) -> Optional[str]:
    """Find a CLI binary on PATH or in known fallback directories."""
    path = shutil.which(name)
    if path:
        return path
    home = os.path.expanduser("~")
    for d in os.environ.get("GLTD_AGENT_EXTRA_PATH", "").split(os.pathsep):
        d = d.strip()
        if d:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    candidates = [os.path.join(home, ".opencode", "bin")]
    nvm_base = os.path.join(home, ".nvm", "versions", "node")
    if os.path.isdir(nvm_base):
        try:
            for v in sorted(os.listdir(nvm_base), reverse=True):
                candidates.append(os.path.join(nvm_base, v, "bin"))
                break
        except OSError:
            pass
    for d in candidates:
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def resolve_agent_command(agent: str) -> Optional[List[str]]:
    """Return argv to run agent, or None if not available.

    Override with env (supports {prompt_file} and {prompt}):
      GLTD_AGENT_GROK='opencode run {prompt_file}'
      GLTD_AGENT_GEMINI='gemini -p {prompt}'
      GLTD_AGENT_OPENCODE='opencode run {prompt_file}'

    Without env overrides, the function auto-detects installed CLIs
    and uses sensible defaults for each agent type.
    """
    env_map = {
        "grok": "GLTD_AGENT_GROK",
        "gemini": "GLTD_AGENT_GEMINI",
        "opencode-deepseek4": "GLTD_AGENT_OPENCODE",
    }
    env = os.environ.get(env_map.get(agent, ""), "").strip()
    if env:
        return ["__shell__", env]

    for name, args in _CLI_ARGS.items():
        if agent.startswith(name):
            cli_path = _find_cli(name)
            if cli_path:
                resolved = list(args)
                resolved[0] = cli_path
                return resolved

    if shutil.which("ollama"):
        model = {
            "grok": os.environ.get("GLTD_OLLAMA_GROK_MODEL", "llama3.2"),
            "gemini": os.environ.get("GLTD_OLLAMA_GEMINI_MODEL", "llama3.2"),
            "opencode-deepseek4": os.environ.get("GLTD_OLLAMA_DEEPSEEK_MODEL", "deepseek-r1"),
        }.get(agent, "llama3.2")
        return ["ollama", "run", model]

    return None


class AgentTasksService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.notes = NotesService(ctx)
        self._lock = threading.Lock()
        self._current_proc: Optional[subprocess.Popen] = None
        self._cancelled: bool = False

    def create(
        self,
        user_hash: str,
        title: str,
        description: str = "",
        agent: str = "grok",
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body = empty_agent_body(description, agent=agent, parent_id=parent_id)
        note = self.notes.create_note(
            user_hash,
            title=title or "Agent task",
            body=body,
            categories=["AgentTasks"],
            tags=["agent_task", agent],
            kind="agent_task",
            extra_payload={
                "agent": agent,
                "agent_status": "pending",
                "parent_id": parent_id,
                "markers": ["#agent", f"#{agent.replace('-', '_')}"],
            },
        )
        if parent_id:
            self._link_related(user_hash, parent_id, note["entity_id"])
        return note

    def get_data(self, user_hash: str, note_id: str) -> Dict[str, Any]:
        note = self.notes.get_note(user_hash, note_id, include_body=True)
        data = parse_agent_body(note.get("body"))
        data["_note"] = note
        return data

    def save_data(
        self,
        user_hash: str,
        note_id: str,
        data: Dict[str, Any],
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        body = serialize_agent(data)
        return self.notes.update_note(
            user_hash,
            note_id,
            title=title,
            body=body,
            kind="agent_task",
            extra_payload={
                "agent": data.get("agent"),
                "agent_status": data.get("status"),
                "parent_id": data.get("parent_id"),
                "markers": normalize_safe(data),
            },
        )

    def set_status(self, user_hash: str, note_id: str, status: str) -> Dict[str, Any]:
        data = self.get_data(user_hash, note_id)
        data.pop("_note", None)
        data["status"] = status if status in STATUSES else data.get("status")
        if status == "done":
            data["executed_at"] = data.get("executed_at") or utc_now()
        return self.save_data(user_hash, note_id, data)

    def add_related(
        self,
        user_hash: str,
        parent_id: str,
        title: str,
        description: str = "",
        agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        parent = self.get_data(user_hash, parent_id)
        parent.pop("_note", None)
        child = self.create(
            user_hash,
            title=title,
            description=description or title,
            agent=agent or parent.get("agent") or "grok",
            parent_id=parent_id,
        )
        return child

    def _link_related(self, user_hash: str, parent_id: str, child_id: str) -> None:
        try:
            data = self.get_data(user_hash, parent_id)
            data.pop("_note", None)
            rel = list(data.get("related_ids") or [])
            if child_id not in rel:
                rel.append(child_id)
            data["related_ids"] = rel
            self.save_data(user_hash, parent_id, data)
        except KeyError:
            pass

    def cancel(self) -> None:
        """Kill the currently running agent process (if any)."""
        self._cancelled = True
        proc = self._current_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def run_agent(
        self,
        user_hash: str,
        note_id: str,
        timeout: int = 120,
        on_output: Optional[Callable[[str], None]] = None,
        subtask_id: str = "",
        prompt_override: str = "",
    ) -> Dict[str, Any]:
        """Try to execute agent locally; store output. Always updates status.

        If *subtask_id* is provided, execute that subtask within the note
        instead of the main task.  *on_output* receives chunks as they arrive.
        """
        data = self.get_data(user_hash, note_id)
        note = data.pop("_note")
        if subtask_id:
            subtasks = data.get("subtasks") or []
            sub = next((s for s in subtasks if s.get("id") == subtask_id), None)
            if sub is None:
                return {"ok": False, "reason": "subtask_not_found", "data": data}
            if prompt_override:
                prompt = prompt_override
            else:
                parent_desc = (data.get("description") or note.get("title") or "").strip()
                sub_desc = (sub.get("description") or "").strip()
                prompt = f"Contexto da tarefa principal:\n{parent_desc}\n\nTarefa específica:\n{sub_desc}"
            agent = sub.get("agent") or data.get("agent") or "grok"
            sub["status"] = "running"
            sub["output"] = ""
        else:
            prompt = prompt_override or (data.get("description") or note.get("title") or "").strip()
            agent = data.get("agent") or "grok"
            data["status"] = "running"
            data["output"] = ""
        self.save_data(user_hash, note_id, data)

        self._cancelled = False
        self._current_proc = None

        cmd = resolve_agent_command(agent)
        if not cmd:
            data["status"] = "pending"
            data["output"] = (
                data.get("output") or ""
            ) + (
                "\n[gltd] Nenhum executor local encontrado para o agente "
                f"'{agent}'. Defina GLTD_AGENT_* ou instale ollama. "
                "Marque o status manualmente e cole o output se preferir.\n"
            )
            self.save_data(user_hash, note_id, data)
            return {"ok": False, "reason": "no_runner", "data": data}

        output_chunks: List[str] = []

        def read_output(proc):
            try:
                for line in proc.stdout:
                    if self._cancelled:
                        break
                    output_chunks.append(line)
                    if on_output:
                        on_output(line)
            except Exception:
                pass

        try:
            if cmd[0] == "__shell__":
                import tempfile
                from pathlib import Path

                template = cmd[1]
                tf = Path(tempfile.mkstemp(suffix=".txt")[1])
                tf.write_text(prompt, encoding="utf-8")
                shell_cmd = template.replace("{prompt_file}", str(tf)).replace("{prompt}", prompt.replace("'", "'\\''"))
                proc = subprocess.Popen(
                    shell_cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            elif cmd[0] == "ollama":
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                proc.stdin.write(prompt)
                proc.stdin.close()
            else:
                env = os.environ.copy()
                extra_paths = [os.path.dirname(cmd[0])]
                old = env.get("PATH", "")
                env["PATH"] = os.pathsep.join(extra_paths + ([old] if old else []))
                proc = subprocess.Popen(
                    [a.replace("{prompt}", prompt) for a in cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )

            self._current_proc = proc

            reader = threading.Thread(target=read_output, args=(proc,), daemon=True)
            reader.start()

            proc.wait(timeout=timeout)
            reader.join(timeout=5)

            if self._cancelled:
                out = "".join(output_chunks) + "\n[gltd] cancelled by user\n"
                st_status = "failed"
            elif proc.returncode == 0:
                out = "".join(output_chunks)
                st_status = "done"
            else:
                out = "".join(output_chunks)
                st_status = "failed"
            out = out.strip() or f"[exit {proc.returncode}] (sem stdout)"

            if subtask_id:
                subtasks = data.get("subtasks") or []
                sub = next((s for s in subtasks if s.get("id") == subtask_id), None)
                if sub:
                    sub["output"] = out
                    sub["status"] = st_status
                    sub["executed_at"] = utc_now()
            else:
                data["output"] = out
                data["status"] = st_status
                data["executed_at"] = utc_now()

        except subprocess.TimeoutExpired:
            self.cancel()
            out = "".join(output_chunks) + f"\n[gltd] timeout after {timeout}s\n"
            if subtask_id:
                subtasks = data.get("subtasks") or []
                sub = next((s for s in subtasks if s.get("id") == subtask_id), None)
                if sub:
                    sub["output"] = out
                    sub["status"] = "failed"
                    sub["executed_at"] = utc_now()
            else:
                data["output"] = out
                data["status"] = "failed"
                data["executed_at"] = utc_now()
        except Exception as e:  # noqa: BLE001
            self.cancel()
            out = "".join(output_chunks) + f"\n[gltd] error: {e}\n"
            if subtask_id:
                subtasks = data.get("subtasks") or []
                sub = next((s for s in subtasks if s.get("id") == subtask_id), None)
                if sub:
                    sub["output"] = out
                    sub["status"] = "failed"
                    sub["executed_at"] = utc_now()
            else:
                data["output"] = out
                data["status"] = "failed"
                data["executed_at"] = utc_now()
        finally:
            self._current_proc = None

        self.save_data(user_hash, note_id, data)
        if subtask_id:
            subtasks = data.get("subtasks") or []
            sub = next((s for s in subtasks if s.get("id") == subtask_id), None)
            sub_ok = (sub.get("status") == "done") if sub else False
            return {"ok": sub_ok, "data": data, "runner": cmd}
        return {"ok": data["status"] == "done", "data": data, "runner": cmd}


def normalize_safe(data: Dict[str, Any]) -> List[str]:
    from gltd_notes.services.notes import normalize_markers

    agent = data.get("agent") or "grok"
    return normalize_markers(["#agent", f"#{str(agent).replace('-', '_')}"])
