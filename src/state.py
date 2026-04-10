import enum
import threading


class AppState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class StateManager:
    def __init__(self):
        self._state = AppState.IDLE
        self._lock = threading.Lock()
        self._observers = []

    @property
    def state(self):
        with self._lock:
            return self._state

    def set_state(self, new_state: AppState):
        with self._lock:
            old_state = self._state
            self._state = new_state
        if old_state != new_state:
            for callback in self._observers:
                try:
                    callback(new_state)
                except Exception:
                    pass

    def on_change(self, callback):
        self._observers.append(callback)
