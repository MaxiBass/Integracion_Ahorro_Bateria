# Ahorro Batería — Registro de decisiones

Este documento no explica qué hace el código (para eso están los docstrings
de cada fichero). Recoge por qué se hizo así, qué se probó y qué queda
pendiente.

---

## 1. De dónde viene

Hasta octubre de 2026 el ahorro de la batería se calculaba con un paquete
YAML (`packages/energia/calculo_ahorro_bateria.yaml`) de 22 elementos:

- 4 `input_number` de «histórico» (offsets congelados a mano),
- 11 plantillas: potencia de descarga filtrada por periodo (3), totales en
  kWh (4) y euros (4),
- 3 sumas de Riemann (`integration`) y 3 `utility_meter` diarios,
- una automatización a las 23:59:30 que volcaba la carga del día al
  histórico.

Solo lo usaba la vista «Ahorro Batería» de un panel. Los precios
(`input_number.precio_*`), el periodo tarifario y los sensores del inversor
los usan otras cosas de la casa (plantilla del precio para el panel de
Energía, automatizaciones del termo y de la carga desde la red) y **no**
forman parte de esta integración: se leen, no se sustituyen.

## 2. Cómo se calcula: con y sin batería

El YAML hacía `descarga × precio del periodo − carga × precio del
excedente`. Eso supone que toda la descarga evita una compra y que toda la
carga viene del sol. La integración compara la red real con la que habría
habido sin la batería (`red + batería`), instante a instante, y valora la
diferencia con los precios de ese instante (fórmula en el docstring de
`calculo.py`). Coincide con el YAML en el caso normal (descarga hacia la
casa, carga con sol) y además acierta en dos que el YAML contaba mal:

| Caso (1 h) | Batería | Red | YAML | Integración |
|---|---|---|---|---|
| Descarga hacia la casa | +1000 W | +200 W | 1 kWh × compra | igual |
| Descarga que se exporta | +1000 W | −300 W | 1 kWh × compra | 0,7 × compra + 0,3 × excedente |
| Carga con sol | −2000 W | −500 W | 2 kWh × excedente | igual (con impuestos, §3) |
| Carga desde la red | −2000 W | +2300 W | 2 kWh × excedente | 2 kWh × compra |
| Carga mixta | −2000 W | +500 W | 2 kWh × excedente | 0,5 × compra + 1,5 × excedente |

Lo positivo (descargando) es el «ahorro bruto»; lo negativo (cargando), el
«coste de la carga». El neto es la resta y **puede ser negativo**: el YAML
lo recortaba a 0, y un día con más coste que ahorro se veía como 0,00 €.

Precio de compra: un sensor con el €/kWh del momento **con impuestos** (en
casa, la plantilla que también usa el panel de Energía). Así esta
integración no repite el cálculo de periodos ni de impuestos.

Matices conocidos, que el YAML tenía igual:

- La potencia de la batería es la del lado de continua y la de la red, la
  de alterna: las pérdidas del inversor (~5 %) no se separan.
- De noche en valle, con la batería reservada para punta, el inversor sigue
  tomando unos 50–60 W de ella. Cuenta como descarga en valle; es ahorro
  real (sin batería saldría de la red), pero explica por qué valle acumula
  bastante aunque la batería «no descargue».

## 3. Impuestos del excedente (decisión de Maxi, 13/10/2026)

Con la compensación simplificada, el excedente descuenta del término de
energía **antes** de impuestos, así que sobre él también se deja de pagar el
impuesto eléctrico y el IVA. Por eso el precio del excedente se multiplica
por `(1 + impuesto eléctrico) × (1 + IVA)`, igual que el de compra ya los
lleva. Con un 0,5 % y un 10 %, un excedente a 0,05 €/kWh vale 0,0553.

No se modela el tope de la compensación (no puede dejar el término de
energía del mes en negativo): en los meses en que se exporta más de lo que
se compra, el coste de cargar con sol queda algo sobrevalorado.

Al migrar, el neto total de partida se recalculó con esta misma regla a
partir de los kWh acumulados (ver §7), así que arranca algo por debajo de
lo que mostraba el YAML.

## 4. Cuándo se cuenta y cuándo no

Suma de Riemann por la izquierda (como `integration` con `method: left`):
cada intervalo se cuenta con los valores del principio. Cuando cambia una
fuente se cierra el intervalo con los valores viejos; además se cierra cada
60 s para que los sensores no se queden quietos. El intervalo que cruza la
medianoche se parte, y cada trozo va a su día.

No se cuenta:

- **mientras falta un dato**: batería o red `unavailable`/`unknown`. Los
  precios e impuestos siguen con su último valor bueno, porque cambian muy
  de vez en cuando y una recarga de plantillas los deja un momento sin
  valor;
- **el tiempo con HA parado**: tras arrancar, el primer intervalo empieza en
  el arranque;
- **un intervalo de más de 10 min** sin cierres (HA colgado, equipo
  suspendido).

No se detecta una fuente «congelada» (disponible pero sin actualizarse): el
inversor (Solarman) no vuelve a escribir un valor que no ha cambiado
(comprobado el 13/10: la red estuvo 15 min en 0 W sin un solo
`last_reported` nuevo), así que un valor quieto no se distingue de un
inversor colgado. Si se cuelga, la integración Solarman pone las entidades
como no disponibles, y entonces sí se para.

## 5. Persistencia

Lo acumulado está en `.storage/ahorro_bateria`, con el `entry_id` de la
entrada dueña. Sin offsets ni líneas base: el YAML sumaba
`input_number + Riemann − línea base escrita a mano`, y si un Riemann perdía
su estado el total se rompía (§8).

Un solo fichero, sin `entry_id` en el nombre, a propósito: si se borra la
integración por error, el fichero se queda, y el alta siguiente lo propone
en el paso «Lo acumulado hasta hoy». Al darla de alta, si el fichero es de
otra entrada se sustituye por lo que se indique en ese paso.

## 6. Identificadores que no se deben cambiar

- Los `entity_id` se fijan en `sensor.py` y son los de las plantillas que
  sustituyen (`sensor.ahorro_bateria_hoy`, `sensor.bateria_total_kwh_punta`,
  …). Así el panel, el historial y las estadísticas a largo plazo de los kWh
  siguen sin cortes.
- `unique_id` = `ahorro_bateria_<clave>`, sin el `entry_id` (solo hay una
  entrada por instalación): si se borra y se vuelve a dar de alta, las
  entidades recuperan su `entity_id` en vez de salir con `_2`.
- Si al dar de alta la integración siguen en el registro las entidades
  viejas con esos `entity_id`, las nuevas salen con `_2`. Hay que borrarlas
  antes (§7).

## 7. Migración desde el YAML (13/10/2026)

1. Anotar los totales del YAML justo antes del cambio.
2. Copia del paquete en la raíz de `config` (`backup_..._2026-10-13.yaml`)
   y quitarlo de `packages/`.
3. Instalar la integración por HACS y reiniciar.
4. Borrar del registro de entidades las 22 entidades viejas (se quedan
   huérfanas «no disponibles» tras el reinicio).
5. Dar de alta la integración con los totales anotados: kWh tal cual; neto
   recalculado con la regla de §3 (kWh por periodo × precio actual con
   impuestos − kWh cargados × excedente con impuestos).
6. Panel: «Coste oportunidad» pasa a llamarse «Coste de la carga», y la
   gráfica de 7 días toma el último valor de cada día en vez del máximo
   (con el neto que puede bajar durante el día, el máximo no es el cierre).

## 8. Fallos del YAML, reproducidos en un HA de pruebas

Con el paquete original cargado en un HA 2026.10.1 de pruebas:

1. **Riemann sin estado**: si una suma de Riemann arranca de 0 (estado no
   restaurado, entidad renombrada), el total de punta pasaba a ser
   negativo por la línea base fija.
2. **Neto recortado**: bruto 0 € y coste 0,276 € → neto 0,0 € en vez de
   −0,276 €.
3. **Doble conteo de la carga**: el Deye pone a 0 su contador diario a las
   00:03, y el volcado era a las 23:59:30. Entre las dos horas la carga del
   día contaba dos veces (+3,9 kWh en la prueba). Si HA estaba
   parado a las 23:59:30, la carga de ese día se perdía.
4. **Revalorización del histórico**: el total en € se recalculaba con los
   precios actuales sobre todos los kWh. Subir un 30 % el precio de llano
   subía un 19 % el ahorro acumulado de toda la vida. La integración
   acumula cada intervalo con el precio de ese momento (hay prueba).

## 9. Pruebas

`tests/test_ahorro_bateria.py`, sin pytest, contra un HA real del venv:
casos del cálculo hechos a mano y un recorrido completo (alta, carga y
descarga en cada caso de §2, cambio de periodo, fuente no disponible, hueco
largo, medianoche, recarga, HA parado, Configurar, diagnóstico, borrar y
volver a dar de alta). Para comprobar que las pruebas pillan fallos se
rompió a propósito el tope de §4 y los impuestos de §3: 9 comprobaciones
en rojo.
