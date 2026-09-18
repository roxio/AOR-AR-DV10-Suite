
from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QWidget

LANGUAGES = (("en", "English"), ("pl", "Polski"))

_PL = {
    "control suite": "pakiet sterujący",
    "CONNECTED": "POŁĄCZONO",
    "DISCONNECTED": "ROZŁĄCZONO",
    "Reconnect": "Połącz ponownie",
    "Dark": "Ciemny",
    "Light": "Jasny",
    "Amber": "Bursztynowy",
    "Green": "Zielony",
    "Night vision": "Nocny",
    "Tuning": "Strojenie",
    "Tune": "Strojenie",
    "S-meter": "S-metr",
    "Mode": "Tryb",
    "Squelch": "Squelch",
    "Levels": "Poziomy",
    "Options & power": "Opcje i zasilanie",
    "Digital codes / offset / priority": "Kody cyfrowe / offset / priorytet",
    "Telemetry": "Telemetria",
    "Raw console": "Surowa konsola",
    "Memory channels & live memory": "Kanały pamięci i pamięć na żywo",
    "Live memory bank editor": "Edytor banków pamięci na żywo",
    "Search banks / scan groups / pass": "Banki wyszukiwania / grupy / pomijane",
    "VFO search / recording / SD card": "Wyszukiwanie VFO / nagrywanie / karta SD",
    "Select-scan": "Select-scan",
    "Signal log": "Dziennik sygnałów",
    "Spectrum scope": "Analizator widma",
    "Snapshots & automation": "Migawki i automatyzacja",
    "Set": "Ustaw",
    "CLR": "CLR",
    "VFO search (VS)": "Wyszukiwanie VFO (VS)",
    "SQL": "SQL",
    "Analog": "Analogowy",
    "Digital": "Cyfrowy",
    "Mode (SQ)": "Tryb (SQ)",
    "Level (LQ 00-99)": "Poziom (LQ 00-99)",
    "Noise (NQ 00-39)": "Szum (NQ 00-39)",
    "CTCSS tone squelch (CI)": "Squelch tonu CTCSS (CI)",
    "OFF": "WYŁ.",
    "CTCSS": "CTCSS",
    "Reverse": "Odwrócony",
    "DCS squelch (DI)": "Squelch DCS (DI)",
    "AGC speed (AC)": "Prędkość AGC (AC)",
    "Attenuator (AT)": "Tłumik (AT)",
    "Volume limit (AV)": "Limit głośności (AV)",
    "Digital gain (DA x0.01)": "Wzmocnienie cyfrowe (DA x0.01)",
    "Manual gain (RG)": "Wzmocnienie ręczne (RG)",
    "Beep level (BP 0-7)": "Poziom dźwięku (BP 0-7)",
    "LCD contrast (LN 0-63)": "Kontrast LCD (LN 0-63)",
    "Backlight (LB)": "Podświetlenie (LB)",
    "Result-code prefixing (RE)": "Prefiksowanie kodów wyniku (RE)",
    "Write protect (PT)": "Zabezpieczenie zapisu (PT)",
    "Receiver ID (ZI)": "ID odbiornika (ZI)",
    "Power (ZP / QP)": "Zasilanie (ZP / QP)",
    "Power ON": "Włącz",
    "Power OFF": "Wyłącz",
    "Danger zone": "Strefa ryzyka",
    "Factory reset (RS)": "Reset fabryczny (RS)",
    "Click again to confirm reset": "Kliknij ponownie, aby potwierdzić reset",
    "DMR (CC / CM / OT)": "DMR (CC / CM / OT)",
    "P25 (PC / PM)": "P25 (PC / PM)",
    "NXDN (NC / NM)": "NXDN (NC / NM)",
    "D-CR descramble (DC)": "Rozszyfrowanie D-CR (DC)",
    "Offset (OF / OL)": "Offset (OF / OL)",
    "Priority (PO / PP / TI)": "Priorytet (PO / PP / TI)",
    "Color code": "Kod koloru",
    "Slot": "Slot",
    "NAC (hex)": "NAC (hex)",
    "RAN": "RAN",
    "MHz": "MHz",
    "Set freq": "Ustaw częst.",
    "Mute by color code (CM)": "Wyciszanie po kodzie koloru (CM)",
    "Mute by NAC (PM)": "Wyciszanie po NAC (PM)",
    "Mute by RAN (NM)": "Wyciszanie po RAN (NM)",
    "Analog voice descrambler (SI)": "Analogowy deszyfrator mowy (SI)",
    "Priority monitoring (PO)": "Monitorowanie priorytetu (PO)",
    "Set channel": "Ustaw kanał",
    "Interval s": "Interwał s",
    "Serial (SN)": "Numer seryjny (SN)",
    "Receiver ID": "ID odbiornika",
    "Clock": "Zegar",
    "IF bandwidth": "Pasmo IF",
    "Delay (ds)": "Opóźnienie (ds)",
    "Free time (s)": "Czas wolny (s)",
    "Earphone antenna": "Antena słuchawkowa",
    "Monitor offset": "Offset monitora",
    "Voice squelch": "Squelch głosowy",
    "Power save": "Oszczędzanie energii",
    "Power-save time": "Czas oszczędzania",
    "Freq data out": "Wyjście danych częst.",
    "S-meter data out": "Wyjście danych S-metra",
    "Receiver status": "Status odbiornika",
    "Send": "Wyślij",
    "Import CSV / JSON / CHIRP / ADIF": "Import CSV / JSON / CHIRP / ADIF",
    "Export...": "Eksport...",
    "Bank": "Bank",
    "all banks": "wszystkie banki",
    "Tune to selected": "Dostrój do wybranego",
    "no memory database loaded": "nie wczytano bazy pamięci",
    "Channel": "Kanał",
    "Name": "Nazwa",
    "Load bank": "Wczytaj bank",
    "Ch": "K",
    "Tag": "Tag",
    "PT": "PT",
    "Write selected row (MX)": "Zapisz wybrany wiersz (MX)",
    "Overwrite bank (MX)": "Nadpisz bank (MX)",
    "not loaded": "nie wczytano",
    "Search bank (SE / SR / SS / SX)": "Bank wyszukiwania (SE / SR / SS / SX)",
    "Scan groups (SG / MG)": "Grupy skanowania (SG / MG)",
    "Pass frequencies (PW / PR / PD)": "Częstotliwości pomijane (PW / PR / PD)",
    "Read": "Odczyt",
    "Write": "Zapis",
    "Run (SS)": "Uruchom (SS)",
    "Delete (SX)": "Usuń (SX)",
    "lower MHz": "dolna MHz",
    "upper MHz": "górna MHz",
    "step kHz": "krok kHz",
    "tag": "tag",
    "Search (SG)": "Wyszukiwanie (SG)",
    "Memory (MG)": "Pamięć (MG)",
    "Group": "Grupa",
    "Free s": "Czas wolny s",
    "Banks": "Banki",
    "Auto-store on hits (AS)": "Auto-zapis przy trafieniach (AS)",
    "List (PR)": "Lista (PR)",
    "Mark (PW)": "Oznacz (PW)",
    "Delete all (PD)": "Usuń wszystko (PD)",
    "Dir": "Katalog",
    "Info": "Info",
    "Status": "Status",
    "Rec start": "Nagrywanie",
    "Play": "Odtwarzanie",
    "SD squelch skip (SD RSQ)": "Pomijanie squelch SD (SD RSQ)",
    "VFO search settings (VE)": "Ustawienia wyszukiwania VFO (VE)",
    "Add": "Dodaj",
    "Remove": "Usuń",
    "Clear": "Wyczyść",
    "Dwell s": "Czas s",
    "Cycles": "Cykle",
    "Run": "Uruchom",
    "Stop": "Stop",
    "list: 0 entries": "lista: 0 pozycji",
    "Clear log": "Wyczyść dziennik",
    "Time": "Czas",
    "dB": "dB",
    "0 events": "0 zdarzeń",
    "Read fast (FD)": "Odczyt szybki (FD)",
    "Read normal (GL)": "Odczyt normalny (GL)",
    "not read": "nie odczytano",
    "Snapshots (dv10_backups)": "Migawki (dv10_backups)",
    "Create": "Utwórz",
    "Restore": "Przywróć",
    "Delete": "Usuń",
    "Interval jobs": "Zadania cykliczne",
    "Backup": "Kopia",
    "Scan": "Skan",
    "every s": "co s",
    "Start": "Start",
    "idle": "bezczynne",
    "Read VFOs (VI)": "Odczytaj VFO (VI)",
    "Step kHz": "Krok kHz",
    "Templates": "Szablony",
    "Save from selected VFO": "Zapisz z wybranego VFO",
    "Apply to its VFO": "Zastosuj do jego VFO",
    "Additional settings": "Ustawienia dodatkowe",
    "Move / clock": "Ruch / zegar",
    "Move prev (ZJ)": "Poprzedni (ZJ)",
    "Move next (ZK)": "Następny (ZK)",
    "Set clock to now": "Ustaw zegar na teraz",
    "Key backlight (KL)": "Podświetlenie klawiszy (KL)",
    "Delay / free time": "Opóźnienie / czas wolny",
    "Sleep timer (SP)": "Timer uśpienia (SP)",
    "Comm speed (SB)": "Prędkość transmisji (SB)",
    "Set (armed)": "Ustaw (uzbrojone)",
    "Click again to confirm": "Kliknij ponownie, aby potwierdzić",
    "Recording timer (TR)": "Timer nagrywania (TR)",
    "Off": "Wył.",
    "Alarm": "Alarm",
    "Recording": "Nagrywanie",
    "Once": "Raz",
    "Weekly": "Co tydzień",
    "End": "Koniec",
    "Receive": "Odbiór",
    "Alarm volume": "Głośność alarmu",
    "Mon": "Pon",
    "Tue": "Wt",
    "Wed": "Śr",
    "Thu": "Czw",
    "Fri": "Pt",
    "Sat": "Sob",
    "Sun": "Nd",
    "Error log": "Dziennik błędów",
    "Message": "Komunikat",
    "0 entries": "0 wpisów",
    "Add to queue": "Dodaj do kolejki",
    "Live protocol trace": "Ślad protokołu na żywo",
    "Show last 50": "Pokaż ostatnie 50",
    "Save trace...": "Zapisz ślad...",
    "Command queue": "Kolejka poleceń",
    "Command": "Polecenie",
    "Run queue": "Uruchom kolejkę",
    "Clear queue": "Wyczyść kolejkę",
    "Set tone": "Ustaw ton",
    "Set code": "Ustaw kod",
    "Auto-label blanks": "Auto-etykiety pustych",
    "Live receiver": "Odbiornik na żywo",
    "Export live bank CSV": "Eksport banku na żywo (CSV)",
    "Diff vs live": "Porównaj z live",
    "Threshold alerts": "Alerty progowe",
    "dBm >=": "dBm >=",
    "VFO compare & templates": "Porównanie VFO i szablony",
    "Frequency": "Częstotliwość",
    "More: Squelch / Levels / Codes / Offset · Priority":
        "Więcej: Squelch / Poziomy / Kody / Offset · Priorytet",
    "Memory Channels & Live Memory": "Kanały pamięci i pamięć na żywo",
    "VFO · Search · Recording · SD Card": "VFO · Wyszukiwanie · Nagrywanie · Karta SD",
    "Search Banks · Scan Groups · Pass Frequencies":
        "Banki wyszukiwania · Grupy skanowania · Pomijane",
    "Spectrum Scope · Select-Scan · Additional Settings":
        "Analizator widma · Select-Scan · Ustawienia dodatkowe",
    "Favorites · Signal log · Alerts · Snapshots · Automation · Presets":
        "Ulubione · Dziennik sygnałów · Alerty · Migawki · Automatyzacja · Presety",
    "Raw console & Command queue": "Surowa konsola i kolejka poleceń",
}

_LANG = "en"


def languages() -> tuple[tuple[str, str], ...]:
    return LANGUAGES


def set_language(code: str) -> None:
    global _LANG
    if code in dict(LANGUAGES):
        _LANG = code


def language() -> str:
    return _LANG


def t(text: str) -> str:
    if _LANG == "pl":
        return _PL.get(text, text)
    return text


def _apply(widget, attr_src: str, attr_out: str, get_text, set_text, upper: bool = False) -> None:
    src = getattr(widget, attr_src, None)
    out = getattr(widget, attr_out, None)
    current = get_text()
    if src is None:
        src = current
        setattr(widget, attr_src, src)
    if out is None or current == out:
        new = t(src)
        if upper:
            new = new.upper()
        if current != new:
            set_text(new)
        setattr(widget, attr_out, new)
    elif current != out:
        setattr(widget, attr_src, current)
        new = t(current)
        if upper:
            new = new.upper()
        if current != new:
            set_text(new)
        setattr(widget, attr_out, new)


def retranslate(root: QWidget) -> None:
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if isinstance(widget, QLineEdit):
            _apply(
                widget,
                "_i18n_ph_src",
                "_i18n_ph_out",
                widget.placeholderText,
                widget.setPlaceholderText,
            )
            continue
        if isinstance(widget, (QLabel, QAbstractButton)) and hasattr(widget, "setText"):
            upper = bool(widget.property("i18nUpper"))
            _apply(widget, "_i18n_src", "_i18n_out", widget.text, widget.setText, upper)
