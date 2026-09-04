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

## PLC reale (grafico in tempo reale)

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

## Demo senza hardware

```bash
python -m plc_monitor demo
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
