# Integracion_Ahorro_Bateria

Repositorio de la integración custom de Home Assistant "Ahorro Batería" de
Maxi: cuánto ahorra la batería solar (descargas que evitan comprar menos
cargas que cuestan excedente o red). Sustituye al paquete YAML
`calculo_ahorro_bateria`. Es la **fuente de verdad** del código y la fuente
desde la que HACS la instala.

Es **público** a propósito, porque HACS no lee repos privados. Por eso:

- **Nunca** subir datos reales de casa: ni los totales acumulados, ni los
  precios de la factura. Las pruebas y la documentación usan valores
  inventados.
- Las comprobaciones con datos reales se hacen en el scratchpad de la sesión.

## Entorno

- Repo local: `~/Downloads/GitHub/Integracion_Ahorro_Bateria`
- HA real por Samba: `/Volumes/config` (si no está montado:
  `osascript -e 'mount volume "smb://192.168.1.9/config"'`).
- **GitHub CLI** (`gh`, cuenta MaxiBass): Claude Code puede hacer push
  **cuando Maxi lo pida**, sin tocar la configuración global de git:
  `git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push origin main`.
  Antes, revisar que el diff no lleve datos personales.
- **HACS sigue commits, no versiones** (no hay releases): para instalar sin
  la interfaz, `update.install` sobre la entidad `update.*` de la
  integración con `version` = hash **corto** del commit.

## Estructura

```
custom_components/ahorro_bateria/
  calculo.py      la fórmula y los acumulados (sin Home Assistant)
  contador.py     escucha las fuentes, va sumando, medianoche, disco
  __init__.py     alta y baja de la entrada
  sensor.py       los 13 sensores (entity_id fijos)
  entity.py       dispositivo de tipo servicio
  config_flow.py  alta en dos pasos y Configurar (entidades / totales)
  diagnostics.py  diagnóstico descargable
  strings.json, translations/, icons.json
  brand/          icono propio (HA lo lee de aquí al arrancar)
docs/DECISIONES.md  por qué es así; NO va en custom_components
docs/icono/generar.py  dibuja brand/icon.png e icon@2x.png
tests/test_ahorro_bateria.py
```

## Antes de tocar nada, lee `docs/DECISIONES.md`

En particular:

- No cambiar los `entity_id` ni los `unique_id` (§6): enlazan con el panel,
  el historial y las estadísticas que ya existen en casa.
- Lo acumulado vive en `.storage/ahorro_bateria` (§5); no hay offsets.

## Flujo para editar

1. Editar en el repo, dentro de `custom_components/ahorro_bateria/`.
2. Pasar las pruebas (abajo).
3. Commit. Push: Maxi, o Claude Code con `gh` si se lo pide.
4. Subir la `version` de `manifest.json` cuando esté listo para probar.
5. Actualizar desde HACS (o `update.install`) y reiniciar HA.

No copiar directamente en `/Volumes/config/custom_components/ahorro_bateria`
sin editar antes en el repo.

## Pruebas

```bash
python3 -m venv /tmp/hav
/tmp/hav/bin/pip install homeassistant==2026.10.1
/tmp/hav/bin/python tests/test_ahorro_bateria.py
```

El venv de `/tmp` lo borra a medias la limpieza de macOS; si `import
homeassistant` falla, recrearlo con `python3 -m venv --clear /tmp/hav`.
