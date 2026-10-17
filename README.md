# Ultimate LUFS Equalizer

Aplicación de escritorio para DJs: cargas la playlist de tu set y te devuelve todos los
tracks **al mismo volumen**, juntos en una carpeta y listos para pinchar en el club sin
pelearte con las ganancias de los canales. Los archivos originales no se tocan nunca.

## Cómo se usa

1. Exporta la playlist desde tu software y arrástrala a la ventana:
   - **Rekordbox**: clic derecho en la playlist → *Exportar playlist a un archivo* (M3U8),
     o *Archivo → Exportar colección en formato xml* y eliges la playlist dentro de la app.
   - **Engine DJ / Serato / VirtualDJ / Mixxx**: exportar como M3U o M3U8.
     Serato también vale directamente con el `.crate` de `_Serato_/Subcrates`.
   - **Traktor**: clic derecho en la playlist → *Export Playlist* (NML).
   - También puedes elegir una carpeta con los tracks.
2. Ajusta el volumen objetivo (por defecto **-9 LUFS**) y el pico máximo (por defecto **-1 dBTP**).
3. Pulsa **Normalizar set**.

Varios agentes trabajan en paralelo, cada uno con un track:

| Agente | Qué hace |
|---|---|
| Recolector | Encuentra el archivo aunque esté en otro disco o carpeta (busca por nombre en las carpetas que indiques) y, si quieres, copia el original. |
| Analizador | Mide sonoridad integrada (LUFS, EBU R128), true peak y rango dinámico. |
| Normalizador | Aplica la ganancia. Si el track no tiene margen de pico, usa un limitador true-peak sobremuestreado y compensa. Después vuelve a medir el resultado. |

En la carpeta de salida tendrás:

- `01 - <track>.<ext>`, `02 - …`: los tracks normalizados, numerados en el orden del set,
  con el **mismo formato y frecuencia de muestreo** que el original y sus etiquetas y carátula.
- `<playlist>.m3u8`: la playlist con los normalizados, para importarla de vuelta en tu software.
- `informe.html` e `informe.csv`: LUFS y picos antes y después de cada track, la ganancia aplicada
  y qué tracks han necesitado limitador.

> Los MP3 y AAC se recodifican al mismo bitrate (no se puede cambiar el volumen de un MP3 sin
> recodificarlo). Si un track necesita mucha limitación, el informe lo marca para que lo escuches.

## Descarga

Cada cambio en `main` compila la app para **Windows** y **macOS** en GitHub Actions
(pestaña *Actions* → último run → *Artifacts*). ffmpeg va incluido; no hay que instalar nada.

## Desarrollo

```bash
pip install -e ".[dev]"
python -m lufs_equalizer             # abre la interfaz
lufs-equalizer set.m3u8 -o salida    # línea de comandos (lufs-equalizer -h)
pytest                               # necesita ffmpeg en el PATH
pyinstaller packaging/lufs_equalizer.spec   # genera la app en dist/
```

Requiere Python 3.10+. El código está en `src/lufs_equalizer`:
`playlists.py` (lectores de playlists), `pipeline.py` (agentes), `audio.py` (medición y
normalización con ffmpeg), `report.py` (informes) y `gui/app.py` (interfaz PySide6).
