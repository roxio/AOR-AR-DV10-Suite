[English](README.md) | [Polski](README.pl.md)

# AOR AR-DV10 control suite

Oprogramowanie sterujące do odbiornika cyfrowego AOR AR-DV10 po USB:
wspólna biblioteka protokołu, interaktywna linia poleceń, aplikacja
graficzna (GUI) oraz panel webowy, który sam jest „graficzną linią
poleceń" w przeglądarce. Wszystkie cztery opierają się na jednym API
`DV10Device`, więc poprawki protokołu i nowe polecenia wystarczy zrobić
raz.

<img width="1120" height="847" alt="wersja01" src="https://github.com/user-attachments/assets/3fb20cf1-e728-4a88-b51b-e93cfcdebfc0" />

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│   CLI       │   │   GUI       │   │  Web panel  │
│ (dv10-cli)  │   │ (PySide6)   │   │ (FastAPI)   │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └─────────────────┼─────────────────┘
                    DV10Device               (aor_dv10/device.py)
                          │
                    CommandChannel           (aor_dv10/protocol/)
                          │
                     Transport                (aor_dv10/transport/)
                    /            \
            SerialTransport   SimulatorTransport
             (real USB)      (fake device, no hardware needed)
```

<img width="885" height="338" alt="DV10-clipanel" src="https://github.com/user-attachments/assets/529fa03c-b2b1-4f0a-9f92-369ae52b63ed" />

`dv10-cli --web` uruchamia CLI *oraz* panel webowy razem, jednym
poleceniem, współdzieląc jeden `DV10Device` / jedno połączenie szeregowe -
patrz „Jedno polecenie, oba interfejsy" poniżej.

## Status

Rdzeń biblioteki USB/protokołu, konsolowe CLI, aplikacja graficzna i panel
webowy są funkcjonalne i przetestowane na wbudowanym symulatorze (patrz
niżej). Panel webowy i GUI sięgają do każdej rodziny poleceń, jaką ma CLI
- w tym kanałów/banków pamięci na żywo, banków wyszukiwania, grup
skanowania, częstotliwości pomijanych, nagrywania VFO/harmonogramu,
obsługi karty SD, analizatora widma i listy select-scan.

Większość szczegółów protokołu przewodowego została zweryfikowana z
dokumentacją poleceń AOR i, tam gdzie to możliwe, sprawdzona na prawdziwym
sprzęcie (patrz „Uwagi o protokole" poniżej); mniejsza część wartości
wciąż pochodzi ze specyfikacji pokrewnego urządzenia przez podobieństwo
rodziny i nie została niezależnie potwierdzona.

Kod źródłowy jest celowo pozbawiony komentarzy: stawia na opisowe nazwy,
małe moduły o jednym zadaniu oraz ten README i wbudowane `help` zamiast
komentarzy w kodzie (patrz „Konwencje" poniżej).

## Najważniejsze cechy

- **Jedno API urządzenia, trzy interfejsy.** CLI, GUI i panel webowy
  sterują tym samym obiektem `DV10Device`, złożonym z miksów `device_*`,
  przez jeden zablokowany `CommandChannel` - bez kodu protokołu
  powielanego per interfejs.
- **Działa bez sprzętu.** Pełny, działający w procesie
  `SimulatorTransport` odpowiada prawdziwym protokołem przewodowym, więc
  cały pakiet (i jego 577 testów) działa przed podłączeniem odbiornika.
- **~120 udokumentowanych kodów poleceń** w samodzielnym rejestrze
  (`protocol/commands.py`), każdy z trybem dostępu i notatką o pewności
  (potwierdzone na sprzęcie / ze specyfikacji / niepotwierdzone).
- **Śledzenie protokołu bajt w bajt** zawsze aktywne, w buforze
  pierścieniowym, widoczne zarówno w CLI (`debug on|off|last|save`), jak i
  po HTTP (`/api/debug/trace`).
- **Wymiana pamięci w pięciu formatach** - backupowy CSV „AR-DV10
  Connect", migawka JSON, CSV CHIRP, ogólny CSV częstotliwości i ADIF
  3.1.4 - plus import bezpośrednio z adresu URL.
- **Prawdziwy edytor banków pamięci na żywo** (MA/MX) z zapisem wiersza i
  całego banku, obsługą zabezpieczenia przed zapisem oraz porównaniem
  różnic względem zaimportowanego CSV.
- **Automatyzacja po stronie serwera**: zadania cykliczne (okresowe
  kopie pamięci i wyszukiwania programowe), które działają bez otwartej
  przeglądarki.
- **Dziennik sygnałów, migawki, telemetria i select-scan** - panele
  zbudowane z danych już odpytywanych lub z jawnych poleceń urządzenia.
- **Interfejs dwujęzyczny** (angielski/polski) i README w obu językach.

## Instalacja

```bash
pip install -e ".[dev]"        # rdzeń + CLI + testy
pip install -e ".[gui]"        # + GUI (PySide6)
pip install -e ".[web]"        # + panel webowy (FastAPI/uvicorn)
```

Wymaga Pythona 3.10+.

Zależności podstawowe to `pyserial`, `prompt_toolkit` i `rich`; opcjonalne
dodatki wprowadzają `PySide6` (GUI) oraz `fastapi` / `uvicorn[standard]` /
`websockets` / `zeroconf` (panel webowy). Instalowane są dwa skrypty
konsolowe: `dv10-cli` i `dv10-web`.

## Wypróbuj bez sprzętu

Wszystko działa na symulowanym DV10 w procesie, więc cały pakiet można
poznać przed podłączeniem prawdziwego sprzętu:

```bash
dv10-cli --simulator
dv10-cli --simulator --web                  # ...oraz panel webowy, jeden proces, jedno wspólne urządzenie
python -m aor_dv10.gui.app --simulator      # wymaga dodatku [gui]
dv10-web --simulator                        # wymaga dodatku [web], następnie otwórz http://127.0.0.1:8000/
```

## Użycie z prawdziwym DV10

```bash
dv10-cli                      # automatyczne wykrycie DV10 po VID/PID USB
dv10-cli --port COM7          # ...lub jawnie wskaż port (Windows)
dv10-cli --port /dev/ttyACM0  # ...(Linux)
```

Odbiornik jest wykrywany po identyfikatorach USB (`0x08D0` / `0x0101`);
podaj `--port` (CLI) lub `--serial-port` (`dv10-web`), aby to
nadpisać, oraz `--baud`, jeśli wartość różni się od domyślnych 115200.

## Jedno polecenie, oba interfejsy

`dv10-cli --web` uruchamia interaktywny terminal *oraz* panel webowy
jednym poleceniem, współdzieląc jeden `DV10Device` / jedno połączenie
szeregowe - zamiast uruchamiać `dv10-cli` i `dv10-web` jako dwa osobne
procesy, które próbowałyby otworzyć ten sam port COM (co zwykle nawet się
nie udaje - większość systemów pozwala tylko jednemu procesowi trzymać
otwarty port szeregowy):

```bash
dv10-cli --web                       # CLI + panel webowy pod http://127.0.0.1:8000/
dv10-cli --web --web-port 9000       # ...na innym porcie
dv10-cli --mdns                      # implikuje --web, dodatkowo http://aordv10.local:8000/ w LAN
dv10-cli --simulator --web           # wypróbuj zestaw bez sprzętu
```

Wymaga dodatku `[web]` (`pip install -e ".[web]"`) - jeśli go brak,
`--web`/`--mdns` wypiszą czytelny komunikat i zakończą pracę, zamiast
po cichu uruchomić sam CLI. Polecenie wpisane w terminalu i polecenie
wysłane z karty przeglądarki trafiają do dokładnie tego samego połączenia
z odbiornikiem, więc każdy interfejs natychmiast widzi zmiany drugiego
(chronione blokadą wokół cyklu żądanie/odpowiedź każdego polecenia - patrz
`CommandChannel` w `protocol/codec.py`), aby oba interfejsy nie mogły
uszkodzić swoich poleceń nawet przy dosłownie jednoczesnym użyciu.

## Debugowanie na prawdziwym sprzęcie

Każde polecenie wysłane do odbiornika (i każda linia z niego odczytana)
jest zawsze zapisywane, bajt w bajt, w buforze pierścieniowym w pamięci -
niezależnie od tego, czy czegokolwiek o to poproszono - więc na pytanie
„co dokładnie powiedziało radio?" można odpowiedzieć po fakcie, a nie
tylko gdy śledzenie było już włączone.

```bash
dv10-cli --port COM7 --debug session.log   # śledzenie od startu, wypisywane na
                                            # konsolę ORAZ dopisywane do session.log
```

Można też włączyć je w trakcie sesji (tak samo w CLI i w surowej konsoli
panelu webowego):

```
DV10> debug on              # linie TX/RX na żywo od tego momentu, przygaszone w konsoli
DV10> debug on session.log  # ...i dodatkowo dopisywane do pliku na bieżąco
DV10> raw MA 0000           # wypróbuj to, co badasz
DV10> debug last 20         # pokaż ostatnie 20 linii śledzenia - działa też bez "debug on"
DV10> debug save session.log
DV10> debug off
```

Każda linia wygląda tak: `[14:32:07.118] TX b'RF0145.50000\r'` /
`[14:32:07.121] RX b'?'` - czyli `repr()` *dokładnych* bajtów, dzięki
czemu zbłąkana spacja, nieoczekiwany CR/LF albo nie-ASCII bajt wysłany
przez prawdziwe urządzenie jest widoczny, a nie po cichu usunięty lub
zdekodowany. Ta precyzja ma znaczenie przy porównywaniu tego, co
rzeczywiście wysyła odbiornik, z tym, co zakłada ten projekt.

Panel webowy ma tę samą historię przez `GET /api/debug/trace?n=50` oraz
polecenia `debug last [N]` / `debug save <path>` w surowej konsoli (bez
przełącznika na żywo - transmisja na żywo z `debug on` na razie tylko w
CLI).

## Interfejs linii poleceń (`dv10-cli`)

### Przełączniki

| Przełącznik | Domyślnie | Znaczenie |
|---|---|---|
| `--port PORT` | auto po VID/PID | Port szeregowy, np. `COM7` / `/dev/ttyACM0`. |
| `--baud N` | `115200` | Prędkość transmisji. |
| `--simulator` | wył. | Użyj symulowanego odbiornika w procesie. |
| `--run CMD` | - | Wykonaj jedno polecenie nieinteraktywnie i zakończ; można powtarzać. |
| `--debug [LOGFILE]` | - | Śledź surowe TX/RX od startu; opcjonalnie dopisuj też do pliku. |
| `--web` | wył. | Uruchom też panel webowy w tym procesie (wspólne urządzenie). |
| `--web-host HOST` | `127.0.0.1` (lub `0.0.0.0` z `--mdns`) | Adres nasłuchu panelu webowego. |
| `--web-port PORT` | `8000` | Port HTTP panelu webowego. |
| `--mdns` | wył. | Rozgłoś panel webowy przez mDNS; implikuje `--web`. |
| `--mdns-name NAME` | `aordv10` | Etykieta nazwy mDNS (`NAME.local`). |
| `--export-commands {json,csv}` | - | Zrzuć pełny rejestr poleceń na stdout i zakończ (bez urządzenia). |

Nieinteraktywne użycie jednorazowe wykonuje kilka poleceń po kolei i
wypisuje każdy wynik:

```bash
dv10-cli --simulator --run "f 145.5" --run status
```

Zrzut pełnego rejestru mnemotechnik poleceń (każdy kod znany projektowi,
nie tylko te z typowanym pomocnikiem w `device.py`) jako czytelny dla
maszyn JSON lub CSV, bez połączenia z urządzeniem:

```bash
dv10-cli --export-commands json > commands.json
```

### `dv10-web` (samodzielny)

`dv10-web` serwuje sam panel webowy (`--host`, `--port`, `--serial-port`,
`--baud`, `--simulator`, `--mdns`, `--mdns-name`). Użyj go, gdy nie
potrzebujesz terminala; użyj `dv10-cli --web`, gdy chcesz oba interfejsy
na jednym połączeniu.

### Polecenia interaktywne

Krótkie czasowniki, w duchu wpisywania poleceń do terminala Yaesu CAT.
Wpisz `help` (lub `?`) w REPL, aby zobaczyć pełną, zawsze aktualną listę -
dopełnianie tabulatorem korzysta z tego samego wspólnego rejestru
(`verb_registry.py`), z którego korzysta `help` panelu webowego.

**Status / tożsamość**

```
s, status              pokaż panel (częstotliwość/mode/squelch/volume/S-metr/AGC/ATT)
id                     model + firmware + znormalizowana rodzina urządzenia
serial                 RN: numer seryjny odbiornika
sn                     SN: tylko do odczytu „numer seryjny wyjścia" (inny niż RN)
zi [TEXT]              ZI: pokaż/ustaw tekst identyfikatora odbiornika
clock [YYMMDDHHmm]     DT: pokaż/ustaw zegar systemowy
vi                     VI: zrzut wszystkich trzech VFO (częstotliwość/krok/korekta/mode)
rx                     RX: odczytaj status odbiornika
```

**Strojenie**

```
f [MHZ]                pokaż lub ustaw częstotliwość, np. "f 145.500000" (wymaga trybu VFO)
m [MODE]               pokaż lub ustaw surowy kod mode, np. "m F0" (FM, cyfrowe wył.)
step [HZ]              pokaż lub ustaw krok strojenia
stepadj [HZ]           SH: pokaż/ustaw korektę kroku częstotliwości
movenext / moveprev    odpowiednik przycisku w górę / w dół na przednim panelu
bw [HZ]                szerokość pasma IF w Hz (bez argumentu wypisze dostępne)
ifbw [VALUE]           IF: szerokość pasma IF surową cyfrą
delay [DECISECONDS]    DL: opóźnienie samodzielne (000-099, 100 = bez limitu)
freetime [SECONDS]     FR: czas wolny samodzielny (00-60 s; 0 = WYŁ.)
```

**Mode / ustawienia odbiornika**

```
vfo [A|B|Z] [MHZ] [MODE]   wybierz/ustaw VFO (sposób wejścia w tryb VFO)
agc on|off             starsze AGC wł./wył. (mapuje na Mid/Fast) - patrz agcspd
agcspd [0-3]           prędkość AGC (0=Fast, 1=Mid, 2=Slow, 3=RF-G)
att on|off             starszy tłumik wł./wył. - patrz attst
attst [0-2]            stan tłumika (0=WYŁ., 1=WŁ., 2=10 dB)
re on|off              przełącz prefiksowanie kodu wyniku
backlight [0|1|2]      LB: podświetlenie LCD (0=WYŁ., 1=CIĄGŁE, 2=AUTO)
klcolor [0-7]          KL: kolor podświetlenia klawiszy
contrast [00-63]       LN: kontrast LCD
mgain [000-110]        RG: wzmocnienie ręczne (poza AGC)
digain [01.00-15.94]   DA: wzmocnienie audio w trybie cyfrowym
vollimit [00-15]       AV: górny limit głośności
writeprotect on|off    PT: znacznik zabezpieczenia przed zapisem
power on|off           ZP (połącz) / QP (rozłącz)
reset [full]           RS: DESTRUKCYJNY reset systemowy / pełny fabryczny
```

**Squelch / poziomy**

```
sq [0|1|2]             TRYB squelch (0=Auto, 1=Szum, 2=Poziom) - nie poziom
lq [LEVEL]             próg squelch poziomu 00-99 (gdy sq=2)
nq [LEVEL]             próg squelch szumu 00-39 (gdy sq=1)
vol [LEVEL]            wzmocnienie audio (błąd 60 na niektórych - użyj vollimit)
beep on|off            dźwięk klawiszy
beeplvl [0-7]          BP: głośność dźwięku klawiszy
tone on|off            wł./wył. squelch tonu CTCSS
tonefreq [VALUE]       ton CTCSS
dcs on|off             wł./wył. squelch DCS
dcscode [VALUE]        kod DCS
sqltype [0-2]          CI: typ squelch tonu (0=WYŁ., 1=CTCSS, 2=Odwrócony)
```

**Pamięć**

```
mem load <path>        wczytaj backupowy CSV banków pamięci „AR-DV10 Connect"
mem find <text>        przeszukaj nazwy wczytanych kanałów
mem list [bank]        wylistuj zaprogramowane kanały, opcjonalnie jeden bank
mem goto <bank>-<ch>   dostrój do wczytanego kanału (przez f/m/step - nie odczyt na żywo)
mem export <path>      zapisz wczytaną (być może edytowaną) bazę z powrotem do CSV
rmem read <bank> <ch>  MA: odczytaj jeden kanał pamięci na żywo z odbiornika
rmem readbank <bank>   MA: odczytaj cały bank na żywo (50 slotów)
rmem write <bank> <ch> <MHZ> [mode] [tag]   MX: zapisz kanał na żywo
rmem tune <bank> <ch>  MR: dostrój odbiornik do kanału pamięci na żywo
rmem delete <bank> <ch>    MQ: usuń kanał na żywo
rmem bank <bank>       MW odczyt: tag / ochrona / liczba kanałów banku
rmem bankset <bank> [count] [protect 0|1] [tag]   MW: ustaw metadane banku
rmem bankdel <bank>    MB: usuń cały bank
rmem find <text> [bank]    przeszukaj kanały na żywo po nazwie
regchan                MM: zarejestruj bieżący kanał jako pamięć ostatniego kanału
```

**Wyszukiwanie / skanowanie / pomijanie / select**

```
search write|read|run|delete <bank>       SE/SR/SS/SX banki wyszukiwania programowego
search lolimit|hilimit [MHZ]              SL/SU limity sesji wyszukiwania
scan sread|swrite|mread|mwrite <group> ...    SG/MG grupy skanowania
scan autostore [on|off]                   AS: auto-zapis przy trafieniach
scan banklink [bank...|clear]             BK: banki powiązane ze skanem
pass mark [MHZ] | pass mark bank <bank> [MHZ] | pass mark allbanks <MHZ>
                                          PW: oznacz częstotliwość pomijaną
pass list [bank]                          PR: wylistuj częstotliwości pomijane
pass delete ...                           PD: usuń częstotliwości pomijane
select add|remove <bank> <ch> | select list | select clear
select run [cycles] [dwell_s]             lista select-scan po stronie hosta + runner
```

**Analizator / nagrywanie / karta SD**

```
scope fast | scope normal                  jednorazowy skan analizatora FD/GL (sparkline tekstowy)
sd dir | sd info | sd status              katalog / info / status karty SD
sd rec start|stop                         SD REC: nagrywanie (stop tylko z panelu na DV10)
sd play <name> | sd play stop             SD PLY: odtwarzanie
sd rsq [on|off]                           SD RSQ: pomijanie squelch
sd backup <kind> | sd restore <name>      SD MMW/MMR (tylko DV1/DV3 - odrzucane na DV10)
timer / timer show|status / timer off
timer set <target> <once|weekly> <start> <end> [alarm|recording] [days] [volume]
                                          TR: harmonogram nagrywania / alarmu
```

**Priorytet / kody cyfrowe / offset**

```
prio on|off            monitorowanie kanału priorytetowego (PO)
priochan [BANK CH]     PP: kanał priorytetowy
priointerval [1-99]    TI: interwał sprawdzania priorytetu (sekundy)
dmrcc [00-16]          CC: kod koloru DMR
dmrcm on|off           CM: wyciszanie po kodzie koloru DMR
dmrslot [VALUE]        OT: wybór slotu DMR
p25nac [000-FFF]       PC: kod NAC P25
p25pm on|off           PM: wyciszanie po NAC P25
nxdnran [00-63]        NC: kod RAN NXDN
nxdnnm on|off          NM: wyciszanie po RAN NXDN
dcrcode [00000-32767]  DC: kod rozszyfrowania DCR
descr on|off           SI: analogowy deszyfrator mowy (V.SCR)
offset [SLOT [+/-]]    OF: slot offsetu + kierunek (00=wył., 01-19=użytk., 20-39=preset)
offsetfreq [SLOT [MHZ]]    OL: częstotliwość offsetu dla slotu (bez znaku)
```

**Surowe / eksperymentalne**

```
raw CODE [VALUE]       wyślij dowolne z ~120 udokumentowanych poleceń, np. "raw LM"
describe CODE          wyjaśnij kod polecenia i oczekiwaną wartość
an, ct, dj, dk, lc, lt, ox, ts, vq, zs, zt, rt, sb, sp
                       cienkie typowane nakładki na kody dostępne tylko surowo
debug on [logfile] | debug off | debug last [N] | debug save <path>
help, ?                wypisz pełną listę poleceń
quit, exit             rozłącz i wyjdź
```

## GUI (PySide6)

`python -m aor_dv10.gui.app --simulator` (lub `--port COM7` dla prawdziwego
sprzętu) otwiera dashboard złożony z kart, zbudowany w tym samym języku
wizualnym co panel webowy: ta sama zaokrąglona „obudowa", ekran LCD w
ramce z wyrównaną do prawej częstotliwością monospace, metalowe pokrętło
strojenia, pigułkowe przełączniki typu rocker dla opcji wł./wył., małe
przyciski funkcyjne monospace oraz te same palety
(ciemna/jasna/bursztynowa/nocna). Dołącza te same kroje **Inter** i
**JetBrains Mono**, które ładuje panel webowy, więc typografia też się
zgadza. Działa na tym samym API `DV10Device`,
więc jest zsynchronizowany z CLI i panelem webowym.

```
python -m aor_dv10.gui.app --simulator
python -m aor_dv10.gui.app --port COM7
python -m aor_dv10.gui.app --simulator --theme amber
```

Przełączniki: `--simulator`, `--port`, `--baud` (domyślnie 115200) oraz
`--theme` (`dark`, `light`, `amber`, `green`). Motyw zmienia się też z
listy w nagłówku.

Podobnie jak panel webowy, GUI jest **dwujęzyczne**: lista wyboru języka
w nagłówku przełącza każdą etykietę, przycisk, nagłówek i tytuł karty
między angielskim i polskim (wartości pochodzące z urządzenia, np. nazwy
trybów czy surowe odczyty, pozostają takie, jak raportuje odbiornik).

Okno to przewijany dashboard odzwierciedlający panel webowy od góry:
najpierw górny pasek, potem pojedynczy **ekran LCD** i panel **Tune**
obok siebie (dokładnie jak `console-top-row` w panelu webowym,
LCD ~58% / Tune ~42%), a następnie pozostałe panele pogrupowane w te same
rozwijane
grupy co w panelu webowym (*Więcej: Squelch / Poziomy / Kody / Offset ·
Priorytet*, *Kanały pamięci i pamięć na żywo*, *VFO · Wyszukiwanie ·
Nagrywanie · Karta SD*, *Banki wyszukiwania · Grupy skanowania ·
Pomijane*, *Analizator widma · Select-Scan · Ustawienia dodatkowe*,
*Ulubione · Dziennik sygnałów · Alerty · Migawki · Automatyzacja ·
Presety*, *Surowa konsola i kolejka poleceń*). W szczegółach:

- **Górny pasek** - tabliczka (dioda połączenia + „AOR AR-DV10" + firmware),
  rząd kontrolek inline (dźwięk klawiszy, RE, suwaki poziomu dźwięku i
  kontrastu z chipami odczytu, wybór podświetlenia, zasilanie WŁ./WYŁ.)
  oraz przełączniki języka / motywu, synchronizacja zegara i ponowne
  połączenie.
- **Ekran LCD** - jeden ekran w ramce, dokładnie jak w panelu webowym:
  blok VFO z tagiem trybu, duża częstotliwość wyrównana do prawej z
  jednostką MHz, częstotliwości dwóch pozostałych VFO po prawej, chipy
  trybu (odbiór/cyfrowy/analogowy), segmentowy S-metr ze znacznikami
  `S1 … +60 dB` i pigułką SQL oraz klikalne chipy statusu (tłumik,
  prędkość AGC, typ squelch, pasmo IF), które przełączają się po kliknięciu.
- **Matryca trybów** - siatki przycisków cyfrowych
  (D-STAR/YAESU/ALINCO/D-CR/P25/dPMR/DMR/TETRA) i analogowych
  (FM/AM/SAH/SAL/USB/LSB/CW) wewnątrz LCD, z *Digital off* i *Set Mode*.
- **Tune** - metalowe pokrętło (przeciąganie lub kółko), pole
  częstotliwości, klawiatura `CE`/`ENT`, przyciski kroków
  (±1 MHz / ±25 kHz / ±5 kHz), wybór VFO A/B/Z, ruch prev/next z przedniego
  panelu i wyszukiwanie VFO (`VS`).
- **Squelch** - przyciski trybu `SQ`, suwaki `LQ`/`NQ`, przełączniki
  CTCSS (`CI`/`CN`) i DCS (`DI`/`DS`) z pełnymi listami tonów (54 CTCSS)
  i kodów (106 DCS), w tym `OFF`/`SRCH`.
- **Poziomy** - prędkość AGC (`AC`), stan tłumika (`AT`), suwaki limitu
  głośności (`AV`), wzmocnienia cyfrowego (`DA`) i ręcznego (`RG`).
- **Opcje i zasilanie** - poziom dźwięku (`BP`), kontrast LCD (`LN`),
  podświetlenie (`LB`), prefiksowanie kodów wyniku (`RE`), write-protect
  (`PT`), ID odbiornika (`ZI`), zasilanie (`ZP`/`QP`) i uzbrajany
  dwuklikiem reset fabryczny (`RS`).
- **Kody cyfrowe / offset / priorytet** - DMR (`CC`/`CM`/`OT`), P25
  (`PC`/`PM`), NXDN (`NC`/`NM`), rozszyfrowanie D-CR (`DC`), deszyfrator
  mowy (`SI`), slot/częstotliwość offsetu (`OF`/`OL`) i priorytet
  (`PO`/`PP`/`TI`).
- **Kanały pamięci i pamięć na żywo** - import backupowego CSV „AR-DV10
  Connect", migawki JSON, CSV CHIRP lub pliku ADIF, filtrowanie/przegląd
  kanałów, dostrojenie kliknięciem i eksport z powrotem do tych formatów.
- **Edytor banków pamięci na żywo** - wczytanie banku prosto z odbiornika
  (`MA`) do edytowalnej tabeli i zapis wierszy lub całego banku (`MX`).
- **Banki wyszukiwania / grupy skanowania / pomijane** - odczyt/zapis
  banków (`SE`/`SR`/`SS`/`SX`), grup (`SG`/`MG`), częstotliwości
  pomijanych (`PW`/`PR`/`PD`) i auto-zapisu (`AS`).
- **Wyszukiwanie VFO / nagrywanie / karta SD** - katalog/info/status SD,
  nagrywanie/odtwarzanie, pomijanie squelch i ustawienia wyszukiwania VFO
  (`VE`).
- **Select-scan** - lista po stronie hosta z nieblokującym runnerem
  interwałowym.
- **Analizator widma** - odczyty `FD`/`GL` rysowane jako wypełniony
  sparkline.
- **Migawki i automatyzacja** - migawki JSON z sygnaturą czasu w
  `dv10_backups/` (twórz/przywróć/usuń) oraz zadania cykliczne (backup lub
  wyszukiwanie programowe) napędzane lokalnym timerem.
- **Dziennik sygnałów** - zdarzenia otwarcia squelch / wykrycia cyfrowego
  z częstotliwością, poziomem i trybem, przechwytywane po stronie klienta.
- **Telemetria** - odczyty statusu urządzenia tylko do odczytu (`AN`/`VQ`/
  `CT`/`DJ`/`DK`/`LC`/`LT`/`OX`/`TS`/`RT`/`RX`/`ZI`/`RN`, ...).
- **Porównanie VFO i szablony** - odczyt wszystkich trzech VFO (`VI`) do
  tabeli obok siebie oraz zapis/zastosowanie/usunięcie nazwanych szablonów
  VFO (przechowywanych w `QSettings`).
- **Ustawienia dodatkowe** - pozycje pasma IF dla bieżącego trybu,
  opóźnienie (`DL`) / czas wolny (`FR`), kolor podświetlenia klawiszy
  (`KL`), ustawienie zegara (`DT`, „na teraz"), timer uśpienia (`SP`),
  prędkość transmisji (`SB`, uzbrajana) oraz ruch poprzedni/następny
  (`ZJ`/`ZK`).
- **Timer nagrywania (TR)** - odczyt i zapis harmonogramu alarmu/nagrywania
  (akcja, raz/co tydzień, start/koniec, dni tygodnia, głośność alarmu).
- **Dziennik błędów** - każde błędne zdarzenie urządzenia/protokołu z GUI,
  z sygnaturą czasu.
- **Surowa konsola** - `raw CODE [VALUE]`, `describe CODE`, `debug last N`
  z historią poleceń, plus **kolejka poleceń** (dodaj kilka poleceń,
  uruchom po kolei, status per polecenie) i widok **śladu protokołu**
  (przełącznik na żywo, pokaż ostatnie 50, zapis do pliku).

GUI ma test dymny (`tests/test_gui_smoke.py`), który buduje całe okno na
symulatorze, stosuje każdy motyw i odświeża każdy panel; jest pomijany
automatycznie, gdy PySide6 nie jest zainstalowane.

## Panel webowy

Otwórz go przez `dv10-cli --web`, `dv10-cli --mdns` lub samodzielny
`dv10-web` - to ten sam serwer FastAPI (`web/server.py`) serwujący
`web/static/index.html`. To nie tylko linia poleceń w przeglądarce: to
pełny pulpit klikany, rozmawiający z tymi samymi czasownikami WebSocket
co surowa konsola pod spodem, więc w protokole przewodowym nic się nie
zmieniło - jedynie to, z czym wchodzisz w interakcję.

### Panele

- **Częstotliwość / strojenie** - duży odczyt tabular-mono, klawiatura
  numeryczna i *Set*, przyciski kroku (±1 MHz / ±25 kHz / ±5 kHz),
  pokrętło strojenia przewijane kółkiem myszy lub strzałkami oraz wybór
  VFO A/B/Z.
- **S-metr** - pasek dB na żywo plus pigułka SQL otwarty/zamknięty,
  odpytywane z `/api/status`, ze sparkline ostatnich odczytów.
- **Mode / squelch / poziomy** - rzędy przycisków dla cyfrowej i
  analogowej połowy `MD`, tryb squelch plus suwaki `LQ`/`NQ`, prędkość
  AGC, tłumik oraz *faktycznie* działająca regulacja głośności (**limit
  głośności**, `AV`), ponieważ `AG` (wzmocnienie audio) jest potwierdzone
  jako niedziałające na prawdziwym sprzęcie, a prawdziwe pokrętło
  głośności jest analogowe.
- **Więcej: Squelch / Poziomy / Kody / Offset · Priorytet** - CTCSS/DCS,
  kody cyfrowe DMR/P25/NXDN/DCR (każdy kod ma własny tooltip z kropką
  pewności), deszyfrator, odbiór z offsetem i odbiór priorytetowy.
- **Ulubione · Dziennik sygnałów · Alerty · Migawki · Automatyzacja ·
  Presety** - nazwane cele VFO, dziennik sygnałów z alertami progowymi,
  migawki pamięci, cykliczne zadania automatyzacji i szybkie presety.
- **Kanały pamięci i pamięć na żywo** - przeszukiwalny widok
  zaimportowanego backupu (dostrojenie do kanału), edytor **banków
  pamięci na żywo** oraz pomocnik mapowania kolumn CSV.
- **VFO · Wyszukiwanie · Nagrywanie · Karta SD** - ustawienia
  wyszukiwania VFO, banki wyszukiwania programowego, grupy skanowania,
  częstotliwości pomijane, harmonogramy nagrywania i obsługa karty SD.
- **Banki wyszukiwania · Grupy skanowania · Częstotliwości pomijane** -
  dedykowane edytory tych trzech struktur po stronie wyszukiwania.
- **Analizator widma · Select-Scan · Ustawienia dodatkowe** - widoki
  analizatora FD/GL, lista select-scan po stronie hosta oraz różne
  dodatki.
- **Surowa konsola i kolejka poleceń** - pierwotne wejście w stylu
  terminala (`raw`, `describe`, `help`, ...) plus kolejka oczekujących
  poleceń z limitami czasu; polecenia destrukcyjne nigdy nie odpalają się
  same.
- **Telemetria** - odczyty statusu tylko do odczytu
  (`AN/VQ/CT/DJ/DK/LD/LU/LC/LT/NR/LS/TS/RT/RX/MDB/ZI/RN`) jako klikalne
  wiersze `[KOD] wartość`.

Strona odpytuje `/api/status` mniej więcej co 1,5 s i pomija aktualizację
kontrolki, która ma obecnie fokus, więc nie wyrwie ci suwaka w trakcie
przeciągania. Długie, głębokie panele (ulubione, dziennik, presety, kody)
są ułożone jako responsywne bloki wielokolumnowe, dzięki czemu strona
pozostaje zwarta, a nie jednym długim przewijaniem.

### Wymiana pamięci

Importowana/eksportowana baza pamięci jest niezależna od formatu:

| Format | Import | Eksport |
|---|---|---|
| Backupowy CSV „AR-DV10 Connect" | tak | tak |
| Migawka JSON (`aor-dv10-suite.memory`) | tak | tak |
| CSV CHIRP | tak | tak |
| Ogólny CSV częstotliwości | tak | - |
| ADIF 3.1.4 | tak | tak |
| Ogólny CSV częstotliwości z URL | tak | - |

Import zastępuje bazę w pamięci używaną przez przeglądarkę/edytor.
Parser/zapis backupowego CSV odtwarza prawdziwy eksport o 2041 liniach
bajt w bajt.

### Edytor banków pamięci na żywo

Odczytuje bank prosto z odbiornika (`MA`) do edytowalnej tabeli i zapisuje
zmiany złożonymi zapisami `MX`. Możesz zapisać pojedynczy wiersz albo
wypchnąć cały wczytany bank przez „Overwrite Bank" / „Overwrite All
Loaded Banks". Wiersze zabezpieczone przed zapisem są pomijane, chyba że
zaznaczysz „Include write-protected rows", a pominięte pola są
uzupełniane z bieżącego kanału, więc częściowa edycja zachowuje resztę.
Widok **diff** porównuje zaimportowany CSV z bankiem na żywo pole po polu,
a jednorazowy eksport CSV na żywo zrzuca bank w postaci odczytanej ze
sprzętu.

### Migawki

Migawki JSON z sygnaturą czasu importowanej bazy są przechowywane po
stronie serwera w `dv10_backups/` i można je tworzyć, wylistować,
przywracać i usuwać. Nazwy plików są sanityzowane (bez przechodzenia
ścieżek).

### Automatyzacja

Zadania cykliczne działają **po stronie serwera**, więc okresowe kopie
pamięci i okresowe wyszukiwania programowe trwają nawet bez otwartej
przeglądarki. Każde zadanie ma akcję „Uruchom teraz". Istnieją tylko akcje
`backup` i `scan`.

### Dziennik sygnałów i alerty

Rejestruje każde zdarzenie otwarcia squelch / wykrycia cyfrowego z
częstotliwością, poziomem i trybem. Alerty progowe to odbite
(debounce) alerty przejść stanu i respektują zgodę na powiadomienia
przeglądarki.

### Select-Scan

Lista kanałów pamięci po stronie hosta (nigdy nie zapisywana do
odbiornika). Runner blokuje połączenie tej karty przeglądarki na cały czas
skanu; opcjonalny harmonogram cykliczny działa po stronie klienta i
zatrzymuje się przy przeładowaniu.

### Język

Przełącznik EN/PL znajduje się w prawym górnym rogu. Tłumaczy po stronie
klienta każdą etykietę, przycisk, nagłówek i dynamicznie wyliczany odczyt
(tryb, stan squelch, powiadomienia), zapamiętuje wybór w `localStorage` i
domyślnie wybiera polski, jeśli język przeglądarki to polski, w
przeciwnym razie angielski. Jedyna rzecz, która pozostaje po angielsku,
to tekst poleceń/odpowiedzi surowej konsoli - to własny format
przewodowy urządzenia.

### Dostęp do panelu po nazwie w LAN (mDNS)

Podaj `--mdns` (do `dv10-cli` lub `dv10-web`), aby rozgłosić panel w
LAN, tak jak drukarka pojawia się jako `printer.local`, dzięki czemu
każde urządzenie w sieci może się do niego dostać po nazwie:

```bash
dv10-cli --mdns                              # -> http://aordv10.local:8000/, plus CLI
dv10-web --mdns                              # -> http://aordv10.local:8000/, sam panel webowy
dv10-web --mdns --mdns-name myshack          # -> http://myshack.local:8000/
dv10-web --simulator --mdns                  # wypróbuj bez sprzętu
```

Wymaga pakietu `zeroconf` (w dodatku `[web]`) i po podaniu `--mdns`
domyślnie wiąże się z `0.0.0.0` zamiast `127.0.0.1` (nadpisz przez
`--host` / `--web-host`).

> **Uwaga o bezpieczeństwie:** panel webowy nie ma uwierzytelniania -
> każdy, kto otworzy adres, może wysłać dowolne polecenie, w tym
> włączyć/wyłączyć odbiornik (`ZP`/`QP`). `--mdns` czyni go osiągalnym
> po nazwie z dowolnego miejsca w twoim LAN, więc używaj tego tylko w
> zaufanej sieci.
>
> Nazwy `.local` są rozwiązywane przez mDNS, który Windows, macOS i Linux
> (z Avahi) obsługują od razu przy *przeglądaniu* adresu `.local`. Jeśli
> `http://aordv10.local:8000/` nie rozwiązuje się z innego urządzenia,
> spróbuj `http://<adres IP komputera w LAN>:8000/` (wypisywany przy
> starcie), diagnozując mDNS/zaporę sieciową.

## API HTTP

Wszystkie trasy należą do serwera panelu webowego; interfejs jest tylko
jednym z konsumentów.

| Metoda | Ścieżka | Przeznaczenie |
|---|---|---|
| GET | `/` | Serwuj interfejs panelu (`static/index.html`). |
| GET | `/api/status` | Pełna migawka telemetrii urządzenia (JSON). |
| POST | `/api/reconnect` | Ponowne połączenie transportu szeregowego. |
| POST | `/api/memory/import` | Import backupowego CSV „AR-DV10 Connect". |
| POST | `/api/memory/autolabel` | Auto-nazwy pustych kanałów `"<mode> <freq>"`. |
| GET | `/api/memory` | Odpytaj zaimportowaną bazę (`q`, `bank`, `include_empty`, `limit`). |
| GET | `/api/memory/banks` | Wylistuj zaimportowane banki (`index`, `protect`, `title`). |
| POST | `/api/memory/tune/{bank}/{channel}` | Dostrój odbiornik do zaimportowanego kanału. |
| GET | `/api/memory/export` | Pobierz bazę jako backupowy CSV. |
| GET | `/api/memory/export_json` | Pobierz bazę jako migawkę JSON. |
| POST | `/api/memory/import_json` | Import migawki JSON. |
| GET | `/api/memory/export_chirp` | Pobierz bazę jako CSV CHIRP. |
| POST | `/api/memory/import_chirp` | Import CSV CHIRP. |
| POST | `/api/memory/import_freqs` | Import ogólnego CSV częstotliwości. |
| POST | `/api/import/url` | Pobierz i zaimportuj CSV częstotliwości z URL. |
| GET | `/api/adif/export` | Pobierz bazę jako ADIF. |
| POST | `/api/adif/import` | Import tekstu ADIF. |
| GET | `/api/memory/backups` | Wylistuj migawki JSON po stronie serwera. |
| POST | `/api/memory/backups` | Utwórz migawkę z sygnaturą czasu. |
| POST | `/api/memory/backups/{name}/restore` | Przywróć migawkę. |
| DELETE | `/api/memory/backups/{name}` | Usuń migawkę. |
| GET | `/api/memory/live_export/{bank}` | Odczytaj bank na żywo ze sprzętu jako CSV. |
| GET | `/api/memory/diff/{bank}` | Porównaj bazę z bankiem na żywo. |
| GET | `/api/memory/live_bank/{bank}` | Odczytaj bank na żywo dla edytora. |
| POST | `/api/memory/live_bank/{bank}/batch` | Zapis wsadowy na żywo (MX); wyniki per pozycja. |
| POST | `/api/memory/live_bank/{bank}/{channel}` | Pojedynczy zapis na żywo (MX); 409 gdy chroniony. |
| DELETE | `/api/memory/live_bank/{bank}/{channel}` | Usuń kanał na żywo. |
| POST | `/api/hits` | Dodaj zdarzenie dziennika sygnałów. |
| GET | `/api/hits` | Odczytaj ostatnie zdarzenia dziennika. |
| DELETE | `/api/hits` | Wyczyść dziennik sygnałów. |
| GET | `/api/scheduler/jobs` | Wylistuj zadania automatyzacji. |
| POST | `/api/scheduler/jobs` | Utwórz zadanie (`backup` / `scan`). |
| DELETE | `/api/scheduler/jobs/{job_id}` | Usuń zadanie. |
| POST | `/api/scheduler/jobs/{job_id}/run` | Uruchom zadanie natychmiast. |
| GET | `/api/debug/trace` | Ostatnie surowe linie śledzenia TX/RX. |

## Protokół WebSocket

Terminal panelu mówi **czysto tekstowym protokołem, jedno polecenie na
ramkę**, pod `/ws` - bez koperty JSON. Wyślij `f 145.500`,
`rmem read 00 05`, `help`, ... a otrzymasz dokładnie jedną ramkę tekstową
na każdą wysłaną (odpowiedzi wielolinijkowe, np. `rmem dump`, przychodzą
jako jedna ramka zawierająca `\n`; błędy wracają jako `error: ...`).
Czasowniki to te same rodziny co w CLI (`f`, `m`, `sq`, `rmem`, `search`,
`scan`, `pass`, `timer`, `sd`, `scope`, `select`, `debug`, `raw`, ...),
obsługiwane przez `_dispatch_plain`.

## Uwagi i zastrzeżenia panelu webowego

Panel webowy trzyma podpowiedzi w jednej krótkiej linii; pełniejsze
uzasadnienie - i każde zastrzeżenie „niepotwierdzone na sprzęcie" -
znajduje się tutaj.

- **Analizator widma (FD/GL).** Oba zwracają dane tylko wtedy, gdy
  odbiornik jest już w „trybie analizatora". Żadne polecenie ani procedura
  z przedniego panelu nie opisuje wejścia w ten tryb w materiałach
  AR-DV10/AR-DV1 (instrukcja nie wspomina funkcji bandscope). Na
  prawdziwym sprzęcie te przyciski najprawdopodobniej zwrócą błąd 30
  („Not in scope mode"), a nie dane - ustalone z dokumentacji, nie
  testowane na żywo.
- **Reset fabryczny (RS).** Reset systemowy zachowuje dane pamięci; pełny
  reset usuwa wszystko (instrukcja 11.2 poz. 4/5). Kodowanie argumentu
  0/1 jest niepotwierdzonym domysłem, więc przycisk może zachować się
  nieoczekiwanie na prawdziwym urządzeniu. Używaj tylko na sprzęcie, na
  którym nie zależy ci na ustawieniach/pamięciach. Oba są uzbrajane
  pierwszym kliknięciem i wysyłane drugim w ciągu 3 sekund.
- **Edytor banków pamięci (MA/MX na żywo).** Wczytuje bank(i) pamięci z
  odbiornika do edytowalnej tabeli. Możesz zapisać pojedynczy wiersz albo
  wypchnąć cały bank (MX) przez „Overwrite Bank" / „Overwrite All Loaded
  Banks". Każda akcja nadpisania jest destrukcyjna w tym samym sensie co
  każdy zapis MX: zastępuje to, co było w slocie, edytowane czy nie.
  Wiersze chronione przed zapisem są pomijane, chyba że zaznaczysz
  „Include write-protected rows".
- **Pamięć na żywo / mostek CSV.** Odczyty MA na żywo mają inny
  (mniejszy) potwierdzony zestaw pól niż format CSV „AR-DV10 Connect":
  po stronie na żywo nie ma offsetu ani korekty kroku, a dokładny kształt
  kodu mode nie jest potwierdzony jako zgodny - traktuj zgłoszoną różnicę
  trybu z ostrożnością. Różnice częstotliwości / ochrony / nazwy /
  znacznika pominięcia są solidne.
- **Karta SD (AR-DV10).** Rec Stop / Backup / Restore są wyłączone w
  panelu. Prawdziwy AR-DV10 podobno zawiesza się, jeśli wyśle się je
  zdalnie (zgodnie z konwencją zatrzymania `/` ze specyfikacji AR-DV1).
  Zatrzymaj nagrywanie klawiszem ● na przednim panelu.
- **Automatyzacja.** Zadania cykliczne działają po stronie serwera -
  okresowe kopie pamięci i okresowe wyszukiwania programowe, nawet bez
  otwartej przeglądarki. Każde zadanie ma akcję „Uruchom teraz".
- **Prędkość transmisji (SB).** Zmiana tego zdalnie może przerwać samo
  połączenie szeregowe używane do wysłania polecenia. Przycisk Set jest
  uzbrajany pierwszym kliknięciem i wysyła drugim w ciągu 3 sekund.
- **Kody cyfrowe (CC/CM/OT/PC/PM/NC/NM/DC).** Polecenia wyboru (CI/DI) są
  potwierdzone na prawdziwym sprzęcie; tabele tonów i kodów CN/DS pochodzą
  z instrukcji i nie są potwierdzone przewodowo. Każdy kod w panelu
  „Digital Codes" ma własny tooltip z kropką pewności.
- **Polecenia eksperymentalne / nieużywane.** Dla tych w rejestrze
  poleceń istnieje tylko jednoliniowy opis - nie było pełniejszej
  specyfikacji do potwierdzenia formatów pól, więc każda kontrolka jest
  dosłownym surowym przekazem. Traktuj wartości jako niepotwierdzone.
- **Wizualizacje.** Sparkline / historia squelch / dziennik błędów są
  budowane wyłącznie z danych odpytywanych co ~1,5 s. Bez nowych poleceń;
  historia resetuje się przy przeładowaniu strony.
- **Select-Scan.** Lista jest tylko po stronie klienta (nigdy nie
  zapisywana do odbiornika). „select run" blokuje połączenie tej karty
  przeglądarki na cały skan; opcjonalny harmonogram cykliczny działa po
  stronie klienta i zatrzymuje się przy przeładowaniu.
- **Częstotliwości pomijane (PW/PR/PD).** Lista pominięć dla wyszukiwania
  programowego, per bank lub dla wszystkich banków, oddzielna od kanałów
  pamięci.
- **Dziennik sygnałów i alerty.** Rejestruje każde zdarzenie otwarcia
  squelch / wykrycia cyfrowego z częstotliwością, poziomem i trybem,
  trzymane w `localStorage` tej przeglądarki. Alerty progowe to odbite
  alerty przejść stanu i respektują zgodę na powiadomienia.
- **Numer seryjny (SN vs RN).** SN to osobne polecenie od RN - nie
  duplikat. W odróżnieniu od RN nie ma dedykowanej sekcji specyfikacji w
  żadnym dostępnym dokumencie; może to być osierocony placeholder w
  tabeli poleceń bez niczego potwierdzonego.
- **Szafka telemetrii.** Polecenia telemetrii tylko do odczytu
  (`AN/VQ/CT/DJ/DK/LD/LU/LC/LT/NR/LS/TS/RT/RX/MDB/ZI/RN`) - wyłącznie
  zapytania o status urządzenia, bez kontrolek zapisu.
- **Kolejka poleceń.** Pokazuje oczekujące polecenia z ich limitami
  czasu. Polecenia destrukcyjne nigdy nie odpalają się same - wymagają
  jawnego potwierdzenia.
- **Rejestracja ostatniego kanału (MM).** Rejestruje kanał, na który
  odbiornik jest aktualnie nastrojony, jako własną „pamięć ostatniego
  kanału" (na którym się włącza). Realny efekt na urządzeniu; nie da się
  cofnąć; nieprawidłowe gdy włączone jest zabezpieczenie przed zapisem
  (PT).
- **Banki wyszukiwania (SE/SR).** Zapisany zakres częstotliwości z
  własnym krokiem/trybem dla wyszukiwania programowego, oddzielny od
  kanałów pamięci.
- **Panel VFO / szablony.** „Set VFO" zapisuje częstotliwość/tryb jako
  osobne polecenia RF/MD po wybraniu VFO - pola osadzone w VF są
  potwierdzone jako cicho ignorowane na prawdziwym DV10. Nazwane cele VFO
  są przechowywane w `localStorage` przeglądarki, nie są automatycznie
  zapisywane do urządzenia.
- **Grupy skanowania (SG/MG).** Grupy po stronie wyszukiwania (SG) i
  pamięci (MG) łączą kilka banków w jeden przebieg skanu. SG ma własne
  pole auto-zapisu per grupa; MG nie ma - realna asymetria protokołu.
- **Timer uśpienia (SP).** Oznaczony jako „No function" dla DV10 w
  oficjalnej tabeli poleceń - zachowany dla kompletności; prawdopodobnie
  no-op.

## Uwagi o protokole

Kilka zachowań prawdziwego sprzętu, które warto znać przed podłączeniem
prawdziwego DV10:

- **Polecenia nie mają spacji między kodem a wartością** -
  `RF0145.50000`, nie `RF 0145.50000`.
- **Zapisy parametrów strojenia (`RF`, `AC`, `SQ`, `AT`, ...) udają się
  tylko, gdy odbiornik jest w trybie VFO**, a nie podczas przeglądania
  kanału pamięci - przełącz na VFO z przedniego panelu albo najpierw
  wyślij `vfo [A|B|Z]`, jeśli zapis wróci z błędem `?`. `enter_vfo_mode()`
  opakowuje prawdziwe polecenie (`VF <litera>`).
- **`MD` (tryb), `LM` (S-metr), `AT`/`AC` (tłumik/prędkość AGC) i `SQ`
  (squelch)** dekodują się do bardziej strukturalnych wartości, niż
  sugeruje pierwszy rzut oka na tabelę poleceń DV10/DV1: `MD` dzieli się
  na osobne wybory trybu cyfrowego/analogowego, `LM` dekoduje się do
  `-dB` plus stan otwarcia/zamknięcia squelch, a nie zwykłego liniowego
  paska, `AT`/`AC` to selektory wielostanowe, a nie boole wł./wył., a
  `SQ` wybiera *tryb* squelch, a nie poziom (`LQ`/`NQ` niosą faktyczne
  progi). Część tych dekodowań pochodzi ze specyfikacji pokrewnego
  urządzenia przez podobieństwo rodziny, a nie niezależnego potwierdzenia
  dla DV10 - zwłaszcza `AG` (starsze wzmocnienie audio) jest potwierdzone
  jako niedziałające; używaj `AV` (limit głośności).
- **`RE` (prefiksowanie kodem wyniku) to stan po stronie urządzenia,
  który przetrwa cykl zasilania i restart klienta.** Po włączeniu każda
  odpowiedź - nie tylko błędy - jest poprzedzona 2-cyfrowym kodem wyniku
  (np. `20RF0145.50000` dla udanego odczytu). Warstwa protokołu zawsze
  rozpoznaje i usuwa ten prefiks niezależnie od tego, czy „sądzi", że
  `RE` jest włączone, więc nie wymaga to specjalnej obsługi po stronie
  wywołującego; `raw RE 0` wyłącza prefiksowanie, jeśli chcesz czystsze
  surowe zapisy.
- **Limity czasu i resynchronizacja.** Przy braku odpowiedzi
  `CommandChannel.send` wysyła samotny `\r`, aby się zsynchronizować, i
  odrzuca jedną linię. Polecenia tylko do odczytu (`value is None`) są
  ponawiane raz; zapisy zgłaszają `DV10ResyncNeeded` zamiast być cicho
  wysyłane ponownie, więc polecenie z efektem ubocznym nigdy nie zostaje
  zduplikowane.

Jeśli odpowiedź prawdziwego odbiornika nie zgadza się z założeniami
projektu, włączenie śledzenia (patrz „Debugowanie na prawdziwym
sprzęcie") i porównanie dokładnych bajtów to najszybszy sposób znalezienia
rozbieżności.

## Testy

```bash
pytest                # 577 testów, w całości na symulatorze
pytest --cov          # z pokryciem (próg 70%)
```

Zestaw działa bez sprzętu: `SimulatorTransport` implementuje protokół
przewodowy i zmienny stan urządzenia. Moduły testów obejmują kodek
protokołu i ponawianie/resynchronizację, narzędzia poleceń, rejestr
poleceń, wykrywanie rodziny urządzeń, modele pamięci i interoperacyjność
między formatami, ADIF i formaty zapisu, timer nagrywania, analizator i
select-scan, CLI (smoke, czasowniki, eksport, SD, timer, VFO) oraz
warstwę webową (integracja, parytet dyspozycji, edytor banków na żywo,
pamięć, strażnicy front-endu). Testy pełnią też rolę wykonywalnej
specyfikacji opisanych wyżej zachowań przewodowych.

## Konwencje

- **Brak komentarzy w kodzie.** Baza kodu jest celowo pozbawiona
  komentarzy (patrz „Status"); opieraj się na opisowych nazwach, małych
  modułach, wskazówkach typów oraz tym README / wbudowanym `help`. Kilka
  wymaganych dyrektyw narzędzi (`# noqa`, `# type: ignore`,
  `# pragma: no cover`) to jedyne wyjątki, bo są funkcjonalne.
- **Lintowanie.** `ruff` z regułami `E`, `F`, `W`, `I`, `UP`, `B`,
  długość linii 120 (`pyproject.toml`).
- **Współdzielone, nie powielane, tam gdzie to ważne.** API urządzenia,
  rejestr poleceń, parsery odpowiedzi, pomocniki tokenów i lista
  czasowników to wspólne moduły. Dyspozytory CLI i web to wciąż ręcznie
  przenoszone kopie siebie nawzajem (patrz „Kolejne kroki").

## Układ projektu

```
src/aor_dv10/
  device.py         DV10Device - API, na którym opiera się reszta
  device_types.py   tabele wartości, enumy i dataklasy (Status, MemoryChannelInfo, ...)
  device_tuning.py        krok strojenia / korekta kroku (ST/SH)
  device_memory.py        kanały i banki pamięci, banki wyszukiwania, grupy skanowania, pomijane
  device_signals.py       squelch, S-metr, AGC, tłumik, CTCSS/DCS, kody cyfrowe
  device_settings.py      głośność/wzmocnienie, kontrast/podświetlenie, zegar, timery, write-protect
  device_scope.py         analizator widma (FD/GL)
  device_sd.py            katalog/info/nagrywanie/odtwarzanie/backup karty SD
  device_priority.py      odbiór priorytetowy (PO/PP/TI)
  device_system.py        zasilanie, status(), prefiksowanie kodów wyniku, pasmo IF, śledzenie
  device_extra.py         kody eksperymentalne / tylko surowe (AN, CT, DJ, OX, VQ, SB, ...)
  memory.py         model pamięci offline + interoperacyjność CSV/JSON/CHIRP
  adif.py           import/eksport ADIF 3.1.4
  record_format.py  czytelne dla człowieka formatery rekordów (banki, grupy, pomijane)
  timer.py          model timera nagrywania/alarmu + kodek przewodowy
  selectscan.py     lista select-scan po stronie hosta + runner
  verb_registry.py  wspólna tabela (czasownik, użycie) dla dopełniania CLI + help web
  command_utils.py  wspólne pomocniki tokenów (on_off, split_command, cyfry zegara, ...)
  constants.py      stałe banków/kanałów/tagów
  transport/        SerialTransport (prawdziwy USB) + SimulatorTransport (fałszywy)
  protocol/         rejestr poleceń (commands.py), ramkowanie/kodek (codec.py),
                    parsowanie odpowiedzi (parsing.py)
  cli/              interaktywny REPL + runner nieinteraktywny (dv10-cli)
  gui/              dashboard PySide6: tokeny motywów + karty w stylu panelu webowego
  web/              panel FastAPI: API statusu, endpointy REST, konsola
                    WebSocket, static/index.html
tests/              zestaw pytest, działa w całości na symulatorze
docs/               PROTOCOL.md / ROADMAP.md (trzymane lokalnie, niepublikowane)
```

## Kolejne kroki

1. Uruchom `dv10-cli --port <twój-port>` na prawdziwym odbiorniku i
   porównaj odpowiedzi z symulatorem; popraw kodowania w `device.py` /
   `serial_transport.py` dla wszystkiego, co się nie zgadza.
2. Utrzymuj zestaw kart GUI w kroku z panelem webowym - oba pokrywają już
   te same rodziny poleceń, ale kilka udogodnień tylko webowych (trwałość
   migawek i zadań po stronie serwera, bogatsze podpowiedzi) mogłoby
   jeszcze przejść do GUI.
3. Wydziel dyspozytor poleceń CLI i panelu webowego do jednego wspólnego,
   niezależnego od formatowania modułu - oba to wciąż ręcznie przenoszone
   kopie siebie nawzajem (`dispatch()` w `cli/repl.py` vs
   `_dispatch_plain()` w `web/server.py`), co już raz spowodowało błąd
   kolizji nazw między dwoma podobnie nazwanymi czasownikami.
4. Spakuj aplikacje desktopowe (PyInstaller) do łatwej dystrybucji, gdy
   protokół zostanie zweryfikowany.

## Licencja

MIT - patrz [LICENSE](LICENSE).
