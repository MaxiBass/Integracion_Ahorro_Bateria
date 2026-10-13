# Integracion_Ahorro_Bateria

Integración custom de Home Assistant que calcula **cuánto ahorra la batería**
de una instalación solar: lo que te ahorras al descargarla en lugar de
comprar de la red, menos lo que cuesta cargarla (el excedente que dejas de
vender o la energía que compras para cargarla).

Pensada para la tarifa española 2.0TD (punta/llano/valle) con compensación
simplificada de excedentes, y probada con un inversor Deye (integración
Solarman), pero solo necesita cuatro sensores cualesquiera: potencia de la
batería, potencia de la red, precio de compra y precio de los excedentes.

Historial de decisiones: [`docs/DECISIONES.md`](docs/DECISIONES.md).

## Cómo calcula

Compara la red tal como ha sido con la que habría habido sin batería. Si la
batería entrega `b` W y la red marca `g` W, sin batería la red habría
marcado `g + b`. Con el precio de cada momento:

- **descarga hacia la casa** → ahorra el precio de compra;
- **descarga que acaba exportada** → vale el precio del excedente;
- **carga con sol** → cuesta el excedente que no se vende;
- **carga desde la red** → cuesta lo que se compra.

El excedente se valora con IVA e impuesto eléctrico, porque con la
compensación simplificada también se dejan de pagar sobre él. Detalle y
ejemplos en DECISIONES §2 y §3.

## Qué crea

Un dispositivo «Ahorro batería» con 13 sensores:

| Sensor | Qué es |
|---|---|
| `sensor.ahorro_bateria_hoy` | Ahorro neto de hoy (€, puede ser negativo) |
| `sensor.ahorro_bateria_total` | Ahorro neto acumulado (€); atributos con el bruto, el coste y los kWh de red |
| `sensor.bateria_ahorro_bruto_hoy` | Ahorro de las descargas de hoy (€) |
| `sensor.bateria_coste_oportunidad_hoy` | Coste de las cargas de hoy (€) |
| `sensor.bateria_descarga_{punta,llano,valle}_kwh_hoy` | kWh descargados hoy en cada periodo |
| `sensor.bateria_total_kwh_{punta,llano,valle}` | kWh descargados en cada periodo, acumulados |
| `sensor.bateria_total_kwh_carga` | kWh cargados, acumulados |
| `sensor.bateria_carga_kwh_hoy` | kWh cargados hoy |
| `sensor.bateria_carga_red_kwh_hoy` | De ellos, los que vinieron de la red |

Los `entity_id` son fijos: coinciden con los del paquete YAML al que
sustituye, para que los paneles y el historial sigan sin cambios. Los € son
`monetary` con estadísticas a largo plazo; los kWh, `total_increasing`. Lo
de «hoy» vuelve a 0 a medianoche.

## Instalación vía HACS

1. HACS → menú ⋮ → **Repositorios personalizados**.
2. URL: `https://github.com/MaxiBass/Integracion_Ahorro_Bateria`, categoría
   **Integración**.
3. Instalar **Ahorro Batería** desde HACS y reiniciar Home Assistant.
4. Ajustes → Dispositivos y servicios → Añadir integración → **Ahorro
   Batería**:
   - **Entidades de origen**: potencia de la batería y de la red (W o kW;
     se puede invertir el signo de cada una), precio de compra actual
     (€/kWh con impuestos), precio de los excedentes (€/kWh sin impuestos)
     y, opcionales, el IVA y el impuesto eléctrico (en %) y el periodo
     tarifario (Punta/Llano/Valle o P1/P2/P3, solo para repartir los kWh).
   - **Lo acumulado hasta hoy**: si vienes de otro sistema, sus totales.

En **Configurar** se pueden cambiar las entidades sin perder lo acumulado,
o corregir los totales. **Descargar diagnóstico** da las entradas actuales y
los acumulados.

Lo acumulado se guarda en `.storage/ahorro_bateria`. Si se borra la
integración, el fichero se queda, y el alta siguiente lo propone como punto
de partida.

## Instalación manual (sin HACS)

Copia `custom_components/ahorro_bateria` a
`/config/custom_components/ahorro_bateria` en tu HA y reinicia.

## Pruebas

```bash
python3 -m venv /tmp/hav
/tmp/hav/bin/pip install homeassistant==2026.10.1
/tmp/hav/bin/python tests/test_ahorro_bateria.py
```

Arrancan un Home Assistant real con las fuentes simuladas y un reloj que se
mueve desde la prueba.
