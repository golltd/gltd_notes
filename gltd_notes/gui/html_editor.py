"""HTML rich-text note editor (contenteditable via WebKit2)."""

from __future__ import annotations

import base64
import html as html_lib
import re
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Gdk  # noqa: E402

try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import WebKit2  # noqa: E402

_EDITOR_CSS_DARK = """
  html, body {
    margin: 0; padding: 0; height: 100%;
    background: #1a1b26; color: #c0caf5;
    font-family: system-ui, "Segoe UI", sans-serif;
    font-size: 15px; line-height: 1.55;
  }
  #ed {
    min-height: 100%; box-sizing: border-box;
    padding: 14px 16px 40px; outline: none;
  }
  #ed:empty:before {
    content: attr(data-placeholder);
    color: #565f89;
  }
  h1 { font-size: 1.55em; color: #7aa2f7; margin: 0.6em 0 0.35em; font-weight: 700; }
  h2 { font-size: 1.28em; color: #bb9af7; margin: 0.55em 0 0.3em; font-weight: 700; }
  h3 { font-size: 1.1em; color: #7dcfff; margin: 0.5em 0 0.25em; font-weight: 600; }
  p { margin: 0.35em 0; }
  ul, ol { margin: 0.4em 0 0.4em 1.4em; padding: 0; }
  li { margin: 0.2em 0; }
  b, strong { color: #e0af68; }
  i, em { color: #9ece6a; }
  u { text-decoration-color: #7aa2f7; }
  code, pre {
    font-family: ui-monospace, "DejaVu Sans Mono", monospace;
    background: #24283b; border-radius: 4px;
  }
  code { padding: 0.1em 0.35em; font-size: 0.92em; }
  pre { padding: 10px 12px; overflow-x: auto; }
  a { color: #7aa2f7; }
  .hashtag {
    color: #73daca; background: rgba(115, 218, 202, 0.12);
    border-radius: 4px; padding: 0 4px; font-weight: 600;
  }
  blockquote {
    margin: 0.5em 0; padding: 0.3em 0.8em;
    border-left: 3px solid #7aa2f7; color: #a9b1d6;
  }
"""

_EDITOR_CSS_LIGHT = """
  html, body {
    margin: 0; padding: 0; height: 100%;
    background: #ffffff; color: #1e1e2e;
    font-family: system-ui, "Segoe UI", sans-serif;
    font-size: 15px; line-height: 1.55;
  }
  #ed {
    min-height: 100%; box-sizing: border-box;
    padding: 14px 16px 40px; outline: none;
  }
  #ed:empty:before {
    content: attr(data-placeholder);
    color: #acb0b8;
  }
  h1 { font-size: 1.55em; color: #1e66f5; margin: 0.6em 0 0.35em; font-weight: 700; }
  h2 { font-size: 1.28em; color: #7c3aed; margin: 0.55em 0 0.3em; font-weight: 700; }
  h3 { font-size: 1.1em; color: #0891b2; margin: 0.5em 0 0.25em; font-weight: 600; }
  p { margin: 0.35em 0; }
  ul, ol { margin: 0.4em 0 0.4em 1.4em; padding: 0; }
  li { margin: 0.2em 0; }
  b, strong { color: #c96000; }
  i, em { color: #107a3e; }
  u { text-decoration-color: #1e66f5; }
  code, pre {
    font-family: ui-monospace, "DejaVu Sans Mono", monospace;
    background: #f0f0f5; border-radius: 4px;
  }
  code { padding: 0.1em 0.35em; font-size: 0.92em; }
  pre { padding: 10px 12px; overflow-x: auto; }
  a { color: #1e66f5; }
  .hashtag {
    color: #0d7377; background: rgba(13, 115, 119, 0.1);
    border-radius: 4px; padding: 0 4px; font-weight: 600;
  }
  blockquote {
    margin: 0.5em 0; padding: 0.3em 0.8em;
    border-left: 3px solid #1e66f5; color: #5c5f77;
  }
"""


def _editor_css(theme: str) -> str:
    if theme == "light":
        return _EDITOR_CSS_LIGHT
    return _EDITOR_CSS_DARK


def _build_editor_html(theme: str) -> str:
    css = _editor_css(theme)
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
""" + css + """</style>
</head>
<body>
<div id="ed" contenteditable="true" data-placeholder="Escreva a nota... (HTML: titulos, negrito, listas, #marcadores)"></div>
<script>
(function() {
  const ed = document.getElementById('ed');
  let notifyTimer = null;

  function notify() {
    try {
      if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.noteChanged) {
        window.webkit.messageHandlers.noteChanged.postMessage('1');
      }
    } catch (e) {}
  }
  function scheduleNotify() {
    if (notifyTimer) clearTimeout(notifyTimer);
    notifyTimer = setTimeout(notify, 500);
  }

  ed.addEventListener('keydown', function(e) {
    if (e.ctrlKey && !e.altKey && !e.metaKey && e.key === 'z' && !e.shiftKey) {
      e.preventDefault();
      try { document.execCommand('undo'); } catch (err) {}
      scheduleNotify();
      return;
    }
    if (
      (e.ctrlKey && !e.altKey && !e.metaKey && e.key === 'y') ||
      (e.ctrlKey && !e.altKey && !e.metaKey && e.shiftKey && e.key === 'z')
    ) {
      e.preventDefault();
      try { document.execCommand('redo'); } catch (err) {}
      scheduleNotify();
      return;
    }
  });
  ed.addEventListener('input', scheduleNotify);
  ed.addEventListener('keyup', scheduleNotify);
  ed.addEventListener('paste', function() { setTimeout(scheduleNotify, 50); });

  window.__setHtml = function(html) { ed.innerHTML = html || ''; };
  window.__setHtmlB64 = function(b64) {
    try {
      const bin = atob(b64 || '');
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      ed.innerHTML = new TextDecoder('utf-8').decode(bytes);
    } catch (e) { ed.innerHTML = ''; }
  };
  window.__getHtml = function() { return ed.innerHTML; };
  window.__getText = function() { return ed.innerText || ''; };
  window.__focus = function() { ed.focus(); };
  window.__exec = function(cmd, val) {
    ed.focus();
    try { document.execCommand(cmd, false, val || null); } catch (e) {}
    scheduleNotify();
  };
  window.__insertHtml = function(frag) {
    ed.focus();
    try { document.execCommand('insertHTML', false, frag); } catch (e) {
      ed.innerHTML += frag;
    }
    scheduleNotify();
  };
})();
</script>
</body>
</html>
"""


def plain_to_html(text: str) -> str:
    if not text:
        return ""
    # already html-ish?
    s = text.strip()
    if s.startswith("<") and (">" in s) and ("</" in s or "/>" in s or s.lower().startswith("<!doctype")):
        return text
    if re.search(r"<(p|div|h[1-6]|ul|ol|li|br|b|i|strong|em)\b", s, re.I):
        return text
    parts = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            parts.append("<p><br></p>")
        else:
            parts.append("<p>" + html_lib.escape(line) + "</p>")
    return "".join(parts) if parts else ""


def html_to_plain(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"(?i)<br\s*/?>", "\n", html)
    t = re.sub(r"(?i)</(p|div|h[1-6]|li|tr)>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html_lib.unescape(t).replace("\xa0", " ").strip()


class HtmlNoteEditor(Gtk.Box):
    """Toolbar + WebKit contenteditable HTML body."""

    def __init__(self, on_change: Optional[Callable[[], None]] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.on_change = on_change
        self._loading = False
        self._ready = False
        self._pending_html: Optional[str] = None
        self._change_guard = False
        self._editor_theme = "dark"

        # formatting toolbar
        tb = Gtk.Box(spacing=4)
        tb.set_margin_top(2)
        tb.set_margin_bottom(2)
        self.pack_start(tb, False, False, 0)

        def mk(label: str, tip: str, cb) -> Gtk.Button:
            b = Gtk.Button(label=label)
            b.set_tooltip_text(tip)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda *_: cb())
            tb.pack_start(b, False, False, 0)
            return b

        mk("B", "Negrito", lambda: self.exec_cmd("bold"))
        mk("I", "Itálico", lambda: self.exec_cmd("italic"))
        mk("U", "Sublinhado", lambda: self.exec_cmd("underline"))
        mk("S", "Riscado", lambda: self.exec_cmd("strikeThrough"))
        tb.pack_start(Gtk.Separator.new(Gtk.Orientation.VERTICAL), False, False, 4)
        mk("H1", "Título 1", lambda: self.exec_cmd("formatBlock", "h1"))
        mk("H2", "Título 2", lambda: self.exec_cmd("formatBlock", "h2"))
        mk("H3", "Título 3", lambda: self.exec_cmd("formatBlock", "h3"))
        mk("¶", "Parágrafo", lambda: self.exec_cmd("formatBlock", "p"))
        tb.pack_start(Gtk.Separator.new(Gtk.Orientation.VERTICAL), False, False, 4)
        mk("• Lista", "Lista com marcadores", lambda: self.exec_cmd("insertUnorderedList"))
        mk("1. Lista", "Lista numerada", lambda: self.exec_cmd("insertOrderedList"))
        mk("“ ”", "Citação", lambda: self.exec_cmd("formatBlock", "blockquote"))
        mk("</>", "Código", lambda: self.exec_cmd("formatBlock", "pre"))
        tb.pack_start(Gtk.Separator.new(Gtk.Orientation.VERTICAL), False, False, 4)
        mk("#tag", "Inserir #marcador", self._insert_hashtag)
        mk("⟲", "Limpar formatação", lambda: self.exec_cmd("removeFormat"))

        # WebView
        ucm = WebKit2.UserContentManager()
        try:
            ucm.register_script_message_handler("noteChanged")
            ucm.connect("script-message-received::noteChanged", self._on_js_change)
        except Exception:
            import logging
            _log = logging.getLogger("gltd_notes")
            _log.warning("Falha ao registrar script message handler — autosave desabilitado")

        settings = WebKit2.Settings()
        settings.set_enable_developer_extras(False)
        settings.set_javascript_can_access_clipboard(True)
        try:
            settings.set_enable_write_console_messages_to_stdout(False)
        except Exception:
            pass

        self.web = WebKit2.WebView.new_with_user_content_manager(ucm)
        self.web.set_settings(settings)
        self.web.connect("load-changed", self._on_load_changed)
        self.web.connect("decide-policy", self._on_decide_policy)
        self.web.set_hexpand(True)
        self.web.set_vexpand(True)
        self.pack_start(self.web, True, True, 0)

        self.web.load_html(_build_editor_html(self._editor_theme), "file:///")
        self.show_all()

    def _on_load_changed(self, _web, event) -> None:
        if event == WebKit2.LoadEvent.FINISHED:
            self._ready = True
            if self._pending_html is not None:
                html = self._pending_html
                self._pending_html = None
                self.set_html(html)

    def _on_decide_policy(self, _web, decision, decision_type) -> bool:
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        nav = decision.get_navigation_action()
        if nav.get_navigation_type() != WebKit2.NavigationType.LINK_CLICKED:
            return False
        uri = nav.get_request().get_uri()
        if not uri or uri.startswith("file://"):
            return False
        decision.ignore()
        toplevel = self.get_toplevel()
        dialog = Gtk.MessageDialog(
            transient_for=toplevel if isinstance(toplevel, Gtk.Window) else None,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Abrir link no navegador?",
        )
        dialog.format_secondary_text(uri)
        if dialog.run() == Gtk.ResponseType.OK:
            Gtk.show_uri_on_window(
                toplevel if isinstance(toplevel, Gtk.Window) else None,
                uri,
                Gdk.CURRENT_TIME,
            )
        dialog.destroy()
        return True

    def _on_js_change(self, _manager, _result) -> None:
        if self._loading or self._change_guard:
            return
        if self.on_change:
            self.on_change()

    def set_html(self, content: str) -> None:
        html = plain_to_html(content or "")
        if not self._ready:
            self._pending_html = html
            return
        self._loading = True
        b64 = base64.b64encode((html or "").encode("utf-8")).decode("ascii")
        self.web.run_javascript(f"window.__setHtmlB64('{b64}');", None, self._after_set, None)

    def _after_set(self, _web, result, _data) -> None:
        try:
            self.web.run_javascript_finish(result)
        except Exception:
            pass
        # release loading after a tick so input events from set don't fire save
        GLib.timeout_add(100, self._clear_loading)

    def _clear_loading(self) -> bool:
        self._loading = False
        return False

    def _apply_editor_theme(self, theme: str) -> None:
        if theme == self._editor_theme:
            return
        self._editor_theme = theme
        if self._ready:
            self.get_html_async(lambda html: self._reload_with_theme(html))

    def _reload_with_theme(self, html: str) -> None:
        self._ready = False
        self.web.load_html(_build_editor_html(self._editor_theme), "file:///")
        self._pending_html = html

    def get_html_async(self, callback: Callable[[str], None]) -> None:
        if not self._ready:
            callback(self._pending_html or "")
            return

        def on_js(web, result, _data):
            try:
                js_result = web.run_javascript_finish(result)
                val = js_result.get_js_value()
                text = val.to_string() if val else ""
            except Exception:
                text = ""
            callback(text or "")

        self.web.run_javascript("window.__getHtml();", None, on_js, None)

    def get_html_sync(self, timeout_ms: int = 1500) -> str:
        """Best-effort sync get (uses a nested main loop)."""
        if not self._ready:
            return self._pending_html or ""
        box: dict = {"html": None, "done": False}

        def cb(html: str) -> None:
            box["html"] = html
            box["done"] = True

        self.get_html_async(cb)
        # wait with nested loop
        deadline = GLib.get_monotonic_time() + timeout_ms * 1000
        ctx = GLib.MainContext.default()
        while not box["done"] and GLib.get_monotonic_time() < deadline:
            ctx.iteration(True)
        return box["html"] if box["html"] is not None else ""

    def exec_cmd(self, cmd: str, value: Optional[str] = None) -> None:
        if not self._ready:
            return
        if value is None:
            js = f"window.__exec({cmd!r});"
        else:
            js = f"window.__exec({cmd!r}, {value!r});"
        self.web.run_javascript(js, None, None, None)
        if self.on_change and not self._loading:
            self.on_change()

    def _insert_hashtag(self) -> None:
        frag = '<span class="hashtag">#marcador</span>&nbsp;'
        js_frag = frag.replace("\\", "\\\\").replace("'", "\\'")
        self.web.run_javascript(f"window.__insertHtml('{js_frag}');", None, None, None)
        if self.on_change and not self._loading:
            self.on_change()

    def clear(self) -> None:
        self.set_html("")

    def set_sensitive(self, sensitive: bool) -> None:  # noqa: A003
        super().set_sensitive(sensitive)
        self.web.set_sensitive(sensitive)
