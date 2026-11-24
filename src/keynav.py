"""Tastaturbedienung fuer das Einstellungsfenster.

customtkinter zeichnet Buttons, Schalter und Menues auf Canvas-Flaechen, die
weder in der Tab-Reihenfolge stehen noch auf Leertaste/Enter reagieren —
ohne Maus war das Fenster nicht bedienbar. KeyNav haengt sich nachtraeglich
an die fertigen Widgets:

- Tab / Umschalt+Tab erreichen jedes Bedienelement,
- Leertaste oder Enter loest es aus (Menues auch mit Pfeil-ab),
- der Fokus ist sichtbar (Akzentfarbe an Rahmen, Text oder Pfeilflaeche),
- ein fokussiertes Element im Scrollbereich wird ins Bild geholt.

Greift auf CTk-Interna zu (_canvas, _label, _buttons_dict) — bei einem
CTk-Update zuerst hier nachsehen. Jeder Zugriff ist abgesichert: schlaegt
er fehl, bleibt das Widget wie bisher nur per Maus bedienbar.
"""

import logging

import customtkinter as ctk

log = logging.getLogger(__name__)

_FLAG = "_vozii_keynav"


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


class KeyNav:
    def __init__(self, accent: str, scroll_frame=None):
        self.accent = accent
        self.scroll_frame = scroll_frame

    def attach(self, root):
        """Alle Bedienelemente unterhalb von root anschliessen. Mehrfach
        aufrufbar (z. B. nachdem ein Abschnitt neu aufgebaut wurde)."""
        for w in list(_walk(root)):
            if getattr(w, _FLAG, False):
                continue
            try:
                if isinstance(w, ctk.CTkButton):
                    # auch die Teil-Buttons eines CTkSegmentedButton
                    self._wire(w, w._canvas, w.invoke, self._ring(w))
                elif isinstance(w, ctk.CTkSwitch):
                    self._wire(w, w._canvas, w.toggle, self._swap(w, "text_color"))
                elif isinstance(w, ctk.CTkOptionMenu):
                    self._wire(w, w._canvas, self._opener(w), self._swap(w, "button_color"),
                               extra_keys=("<Down>",))
            except Exception:
                log.debug("KeyNav: %r nicht anschliessbar", w, exc_info=True)

    def label(self, label, action):
        """Klickbares CTkLabel (Abschnittskopf, Link) per Tastatur erreichbar machen."""
        try:
            self._wire(label, label._label, action, self._swap(label, "text_color"))
        except Exception:
            log.debug("KeyNav: Label nicht anschliessbar", exc_info=True)

    # --- intern ---

    def _wire(self, widget, target, action, focus_style, extra_keys=()):
        on_focus, on_blur = focus_style

        def fire(_e=None):
            action()
            return "break"  # sonst loest Enter zusaetzlich "Speichern" am Fenster aus

        def focus_in(_e=None):
            on_focus()
            self._reveal(widget)

        target.configure(takefocus=1)
        for key in ("<space>", "<Return>", "<KP_Enter>", *extra_keys):
            target.bind(key, fire, add="+")
        target.bind("<FocusIn>", focus_in, add="+")
        target.bind("<FocusOut>", lambda _e: on_blur(), add="+")
        setattr(widget, _FLAG, True)

    def _ring(self, button):
        """Fokus als Rahmen in Akzentfarbe; beim Verlassen der alte Rahmen."""
        saved = {}

        def on():
            saved.update(border_width=button.cget("border_width"),
                         border_color=button.cget("border_color"))
            button.configure(border_width=2, border_color=self.accent)

        def off():
            if saved:
                button.configure(**saved)
        return on, off

    def _swap(self, widget, option):
        """Fokus ueber eine Farboption (Text bzw. Pfeilflaeche) zeigen."""
        saved = {}

        def on():
            saved[option] = widget.cget(option)
            widget.configure(**{option: self.accent})

        def off():
            if saved:
                widget.configure(**saved)
        return on, off

    @staticmethod
    def _opener(menu):
        def open_menu():
            if menu.cget("state") != "disabled":
                menu._open_dropdown_menu()
        return open_menu

    def _reveal(self, widget):
        """Fokussiertes Widget im Scrollbereich sichtbar machen."""
        frame = self.scroll_frame
        if frame is None or not str(widget).startswith(str(frame)):
            return
        try:
            canvas = frame._parent_canvas
            inner_h = frame.winfo_height()
            view_h = canvas.winfo_height()
            if inner_h <= view_h:
                return
            top = widget.winfo_rooty() - frame.winfo_rooty()
            bottom = top + widget.winfo_height()
            first = canvas.yview()[0] * inner_h
            pad = 12
            if top - pad < first:
                canvas.yview_moveto(max(0.0, (top - pad) / inner_h))
            elif bottom + pad > first + view_h:
                canvas.yview_moveto(min(1.0, (bottom + pad - view_h) / inner_h))
        except Exception:
            log.debug("KeyNav: Scrollen zum Fokus fehlgeschlagen", exc_info=True)
