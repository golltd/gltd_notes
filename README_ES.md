# GLTD Notes — Bloc de Notas Personal con Sincronización Multi-Equipo

## ¿Qué es GLTD Notes?

Una aplicación de notas **privada y de código abierto** para Linux, creada como alternativa a GNote. Ofrece interfaz gráfica de escritorio (GTK 3), servidor web local y API REST — todo ejecutándose en tu máquina, sin dependencia de nube ni servidor externo.

### ¿Por qué existe?

- **Privacidad real**: todos los datos permanecen en tu computadora, en tu carpeta.
- **Sincronización entre equipos**: usa **Syncthing** para mantener tus notas sincronizadas entre varios equipos sin servidor central. El formato de almacenamiento evita conflictos cuando dos personas editan al mismo tiempo.
- **Historial completo**: cada cambio queda registrado. Puedes volver a cualquier versión anterior de una nota.
- **Agentes de IA integrados**: describe tareas en lenguaje natural y pide a DeepSeek (vía opencode), Grok o Gemini que las ejecuten automáticamente.

> **Esta aplicación fue desarrollada con asistencia de inteligencia artificial usando Grok (xAI) y DeepSeek V4 (vía opencode).**

---

## Cómo Instalar

### 1. Dependencias del Sistema

Ejecuta el siguiente comando en la terminal (Linux Mint / Ubuntu / Debian):

```bash
sudo apt install python3 python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-notify-0.7 \
  gir1.2-ayatanaappindicator3-0.1 libnotify-bin
```

### 2. Ubicación de Archivos

El programa está instalado en:

```
/var/PROGRAMAS/gltd_notes/          ← código de la aplicación
~/gltd_notes_data/                ← tus datos (notas, adjuntos, historial)
~/.config/gltd_notes/config.json    ← configuración local y contraseñas
~/.local/share/gltd_notes/session/  ← control de sesión bloqueada
```

### 3. Configuración Inicial (primer uso)

Antes de abrir el programa, crea tu usuario y define la contraseña:

```bash
/var/PROGRAMAS/gltd_notes/bin/gltd-notes init \
  --data-root ~/gltd_notes_data \
  --username TU_USUARIO --password 'TU_CONTRASEÑA'
```

### 4. Crear Accesos Directos en el Menú (opcional)

```bash
/var/PROGRAMAS/gltd_notes/scripts/install_desktop.sh
```

Esto añade entradas en el menú del sistema y enlaces en `~/.local/bin/` para los comandos `gltd-notes`, `gltd-notes-api` y `gltd-notes-web`.

---

## Cómo Usar

### Interfaz Gráfica (modo normal)

```bash
gltd-notes gui
```

- Crea, edita y elimina notas con formato de texto enriquecido.
- Adjunta archivos (imágenes, PDFs, lo que sea) — cada archivo se almacena por contenido, evitando duplicados.
- Consulta el **historial** de cambios y restaura versiones anteriores.
- Crea **eventos/recordatorios** que disparan notificaciones en el escritorio.
- Usa el **ícono en la bandeja del sistema** (tray) para acceso rápido: nueva nota, nuevo evento, mostrar ventana, salir.
- **Bloquea la sesión** con contraseña — mientras esté bloqueada, nadie accede a las notas.

### Interfaz Web

```bash
gltd-notes web
```

Abre el navegador en `http://127.0.0.1:8765` para acceder a las notas por web.

### API REST

```bash
gltd-notes api
```

La API REST está disponible en `http://127.0.0.1:8765` (solo localhost). Todas las solicitudes requieren el encabezado:

```
X-API-Key: <clave en ~/.config/gltd_notes/config.json>
```

Ejemplos:

```bash
# Obtener la clave de la API
KEY=$(python3 -c "import json;print(json.load(open('$HOME/.config/gltd_notes/config.json'))['api']['api_key'])")

# Verificar funcionamiento
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8765/api/v1/health

# Crear una nota
curl -s -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"title":"Mi nota","body":"Contenido de la nota vía API"}' \
  http://127.0.0.1:8765/api/v1/notes

# Listar todas las notas
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8765/api/v1/notes
```

---

## Tareas con Agentes de IA

GLTD Notes permite delegar tareas a agentes de IA. Escribe lo que necesitas hacer y el agente lo ejecuta en la terminal.

### Agentes Disponibles

| Nombre en Interfaz | Herramienta CLI | Descripción |
|--------------------|-----------------|-------------|
| `opencode-deepseek4` | `opencode run` | Ejecuta tareas usando DeepSeek V4 |
| `grok` | `grok` | Ejecuta tareas usando Grok |
| `gemini` | `gemini` | Ejecuta tareas usando Gemini |

### Cómo Usar

1. En el menú, ve a **Tareas → Nueva tarea para agente**.
2. Elige el agente (recomendado: `opencode-deepseek4`).
3. Describe la tarea en lenguaje natural. Sé específico.
4. Haz clic en **▶ Ejecutar** y espera el resultado en el campo de salida.

### Ejemplo de Tarea

```
Configurar el servidor 192.0.2.1:
1. Acceder vía SSH como root
2. Instalar y configurar MariaDB
3. Crear base de datos "app_produccion"
4. Crear usuario "app_user" con contraseña segura
5. Configurar respaldo diario con cron
```

Para más detalles sobre agentes, consulta [README_AGENT.md](README_AGENT.md).

---

## Sincronización entre Equipos con Syncthing

1. Instala [Syncthing](https://syncthing.net/) en todos los equipos.
2. En cada equipo, comparte la carpeta de datos de GLTD Notes (`~/gltd_notes_data`).
3. Listo. Las notas se sincronizan automáticamente.

**¿Por qué no hay conflictos?** El programa usa un formato especial llamado "blockchain de notas": cada cambio es un nuevo bloque añadido al final del archivo, con identificación de máquina y usuario. Cuando dos personas editan la misma nota al mismo tiempo, ambas versiones se preservan y pueden verse en el historial.

---

## Compartir Notas

En GLTD Notes puedes compartir notas con otros usuarios:

- Notas privadas: visibles solo para ti.
- Notas compartidas: copiadas al área `shared/` y visibles para todos los usuarios listados.
- El historial muestra qué usuario y qué máquina produjo cada cambio.

---

## Documentación

| Archivo | Contenido |
|---------|-----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Almacenamiento, blockchain y sincronización multi-equipo |
| [docs/API.md](docs/API.md) | Referencia completa de la API REST |
| [docs/SECURITY.md](docs/SECURITY.md) | Modelo de autenticación y seguridad |
| [docs/PACKAGING.md](docs/PACKAGING.md) | Planes futuros (.deb, AppImage, etc.) |
| [README_AGENT.md](README_AGENT.md) | Guía detallada de tareas con agentes de IA |

---

## Versionado

El numero de version sigue el formato `MAJOR.MINOR.PATCH` (versionado semantico):

- **MAJOR**: cambios incompatibles de API o reescrituras completas (actualmente `0` — pre-estable)
- **MINOR**: nuevas funcionalidades, nuevos subcomandos, nuevas paginas de interfaz (`1`)
- **PATCH**: correcciones de errores, pequenas mejoras, actualizaciones de documentacion — **incrementado automaticamente con cada commit**

El numero de patch es gestionado automaticamente por `.githooks/pre-commit`, que ejecuta `scripts/bump_version.sh` antes de cada commit. La fuente canonica de la version es `gltd_notes/_version.py` — todas las demas referencias (`pyproject.toml`, endpoints health de la API, `__init__.py`) derivan de ella.

---

## Donaciones

Si GLTD Notes te resulta util, considera apoyar su desarrollo:

- **PIX (Brasil)**: `1f57a276-dc0e-44a0-a4e0-4a2349833958`
- **Monero (XMR)**: `84pnTEwRrFLPUqSNQdCLFw6X6gjQeQtdNNVxkYAfvgd229DHgNYzzQ9VgpquUG8RfAJJ5Py556KrAiG47PqKYxPM1mzpAtb`

---

## Sobre el Desarrollo

Esta aplicación fue desarrollada con asistencia de **inteligencia artificial** utilizando:

- **Grok** (xAI) — prototipado e iteraciones iniciales
- **DeepSeek V4** vía opencode — arquitectura final, refinamiento y completitud

El código es 100% abierto (licencia MIT). Consulta el archivo [LICENSE](LICENSE).
