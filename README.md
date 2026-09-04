# Monitor PLC via Modbus TCP + stream Siemens realtime

Programmino Python per **leggere e graficizzare segnali da un PLC** su TCP/IP.

Due modalità:

1. **Modbus TCP** (porta 502 di solito) — polling di holding/input register
2. **Stream TCP custom** — pacchetti binari multi-canale ad alta frequenza
   (es. Siemens **100 canali @ 1000 Hz**, un pacchetto ogni **100 ms** con timestamp)

## Due macchine diverse (leggi questo se il ping fallisce)

**Il Cloud Agent di Cursor e il tuo PC non sono lo stesso computer.**

| Macchina | Cosa è | Rete | Può raggiungere `192.168.2.100`? |
| --- | --- | --- | --- |
| **Cloud Agent** (questa VM remota) | server in cloud dove l'agente scrive codice | solo `172.30.x` (es. `enp0s2`) — **nessuna** scheda USB Ethernet | **No.** `ping 192.168.2.100` fallisce al 100%. Porte 102/502/2000 chiuse da qui. |
| **Il tuo PC / VM locale** (dove hai Cursor Desktop) | la macchina fisica con la scheda **USB Ethernet** (`usb_xhci`) | LAN verso il PLC Siemens | **Sì**, se `ping 192.168.2.100` funziona da quel PC |

Quindi:

1. Se vedi l'agente che “non pinga il PLC”, **non è un bug del codice**: quella VM non ha la scheda USB e non è in officina.
2. Per parlare col PLC reale (`192.168.2.100`), apri un terminale **sul PC che già riesce a fare ping**, clona/apri questo repo, attiva `.venv` ed esegui i comandi `stream` / `test` / `plot` **lì**.
3. Sul Cloud Agent puoi solo validare la pipeline in locale con `stream-demo` (simulatore su `127.0.0.1`), non connetterti al Siemens.

```bash
# SUL TUO PC (quello con USB Ethernet che pinga 192.168.2.100)
source .venv/bin/activate
python -m plc_monitor stream --host 192.168.2.100 --port 2000
# oppure, con i default di config.siemens.yaml:
python -m plc_monitor stream
```

```bash
# SUL CLOUD AGENT (nessun PLC reale raggiungibile) — finestra live matplotlib
source .venv/bin/activate
python -m plc_monitor stream-demo
# (opzionale, solo headless/CI: --seconds 3 --save /tmp/siemens_stream.png)
```

## Cosa fa

### Modbus TCP
- si collega al PLC (`host` + `port` in `config.yaml`)
- legge holding register, input register, coil e discrete input
- decodifica `uint16`, `int16`, `uint32`, `int32`, `float32`, `bool`
- gestisce i word order `abcd` / `cdab` / `badc` / `dcba` (utile su Siemens/Omron)
- applica `scala` e `offset`
- mostra un grafico live (una traccia per segnale)
- può salvare CSV e PNG
- include un **simulatore** per provarlo senza hardware

### Stream Siemens (100 ch @ 1000 Hz)
- riceve pacchetti TCP (`config.siemens.yaml`, default host `192.168.2.100:2000`)
- ogni pacchetto (≈100 ms) contiene **100 canali × 100 campioni** float32 + **timestamp ns** + sequence
- grafico realtime di alcuni canali + rate pacchetti / gap / timestamp
- **stream-demo** / **stream-sim** per provarlo in locale senza PLC

## Apri il progetto e crea l'ambiente

Dalla cartella del repository (in Cursor o nel terminale):

```bash
chmod +x scripts/setup_env.sh
./scripts/setup_env.sh
source .venv/bin/activate
```

Lo script crea le directory, il virtualenv `.venv`, scarica le librerie da `requirements.txt` e punta l'interprete Python del workspace a `.venv/bin/python` (vedi `.vscode/settings.json`).

Serve **Python 3.10+**. Se manca:

- macOS: `brew install python@3.12` oppure l'installer da https://www.python.org/downloads/
- Windows: stesso installer; poi `.venv\Scripts\activate` al posto di `source`

A mano, equivalente:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Stream Siemens realtime (100 ch @ 1000 Hz)

Formato pacchetto (little-endian): header 24 byte (`PLCP` + version + n_ch + n_samples + seq + `timestamp_ns`) + payload float32 canale-major. Con 100 ch × 100 campioni → ~40 KB + header ogni 100 ms.

### Demo locale (senza PLC) — funziona anche dal Cloud Agent

```bash
source .venv/bin/activate
# Apre la finestra matplotlib LIVE (~10 Hz / refresh 100 ms = packet_ms).
# Non usare --save/--seconds se vuoi il grafico realtime.
python -m plc_monitor stream-demo
# headless / CI (PNG statico, non live):
python -m plc_monitor stream-demo --seconds 3 --save /tmp/siemens_stream.png
```

Solo il simulatore TCP (poi in un altro terminale `stream --host 127.0.0.1`):

```bash
python -m plc_monitor stream-sim
```

### PLC reale — solo sul PC con USB Ethernet

1. Sul PLC: socket TCP server (es. TSEND_C / TRCV) sulla porta configurata (default **2000**) che emette il formato sopra.
2. Esegui sul **PC locale** dove `ping 192.168.2.100` già funziona (scheda USB Ethernet). **Non** dal Cloud Agent.
3. Config in `config.siemens.yaml` (host `192.168.2.100`, 100 ch, 100 samp/pkt, 1000 Hz).

```bash
# Sul PC locale (non sul Cloud Agent)
source .venv/bin/activate
python -m plc_monitor stream --host 192.168.2.100 --port 2000
# oppure usa i default di config.siemens.yaml:
python -m plc_monitor stream
```

## PLC reale Modbus (grafico in tempo reale)

1. Sul PLC deve essere attivo il server **Modbus TCP** (porta di solito **502**).
2. Esegui il programma sul **PC nella stessa rete** del PLC (dal Cloud Agent non raggiungi l'IP di officina).
3. In `config.yaml` metti IP e i registri che vuoi vedere.
4. Prova la connessione, poi apri il grafico:

```bash
source .venv/bin/activate
python -m plc_monitor test
python -m plc_monitor plot
```

Oppure senza toccare il file:

```bash
python -m plc_monitor test --host 192.168.1.10 --port 502
python -m plc_monitor plot --host 192.168.1.10 --port 502
```

Se `test` fallisce: PLC acceso, cavo/Wi-Fi, IP pingabile, Modbus TCP abilitato, porta e unit ID corretti.

## Demo Modbus senza hardware

```bash
python -m plc_monitor demo
```

## Configurazione

### Modbus — `config.yaml`

```yaml
plc:
  host: 192.168.1.10   # IP del PLC
  port: 502            # Modbus TCP
  unit_id: 1
  poll_ms: 200

signals:
  - name: Temperatura
    table: holding      # holding | input | coil | discrete
    address: 0          # 0-based (holding 0 = 40001 su molti PLC)
    dtype: float32      # uint16 int16 uint32 int32 float32 bool
    word_order: abcd    # prova cdab se i float sono a pezzi
    scale: 1.0
    offset: 0.0
    unit: "°C"
```

Sul PLC abilita il server **Modbus TCP**. Se i valori letti sono insensati, inverti `word_order` (`abcd` ↔ `cdab` è il caso più frequente).

### Stream Siemens — `config.siemens.yaml`

```yaml
stream:
  host: 192.168.2.100
  port: 2000
  channels: 100
  samples_per_packet: 100   # 1000 Hz × 0.1 s
  sample_hz: 1000
  packet_ms: 100
  plot_channels: [0, 1, 2, 3]
  window_packets: 50
```

## Test

```bash
python -m pytest
```
