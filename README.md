# Monitor PLC via Modbus TCP

Programmino Python per **leggere e graficizzare segnali da un PLC** su TCP/IP.

Usa **Modbus TCP** (porta 502 di solito): è il protocollo Ethernet più diffuso su PLC Siemens (con gateway), Schneider, Omron, Codesys, Wago, ecc. Non serve un runtime del costruttore.

## Cosa fa

- si collega al PLC (`host` + `port` in `config.yaml`)
- legge holding register, input register, coil e discrete input
- decodifica `uint16`, `int16`, `uint32`, `int32`, `float32`, `bool`
- gestisce i word order `abcd` / `cdab` / `badc` / `dcba` (utile su Siemens/Omron)
- applica `scala` e `offset`
- mostra un grafico live (una traccia per segnale)
- può salvare CSV e PNG
- include un **simulatore** per provarlo senza hardware

## Installazione

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

Grafico live verso un PLC reale (modifica prima `config.yaml`):

```bash
python -m plc_monitor plot
```

PLC finto in locale (porta 5020, vedi config di default):

```bash
python -m plc_monitor simulate
```

In un altro terminale:

```bash
python -m plc_monitor plot
```

Tutto insieme, senza hardware:

```bash
python -m plc_monitor demo
```

Cattura di 10 secondi in PNG e CSV (anche senza schermo):

```bash
python -m plc_monitor demo --seconds 10 --save grafico.png --csv segnali.csv
```

## Configurazione

In `config.yaml`:

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

## Test

```bash
python -m pytest
```
