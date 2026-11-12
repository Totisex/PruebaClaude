# Tutorial: cómo reservar un stand en ferialapantera.com

Video tutorial con voz en off de ElevenLabs del flujo de reserva de la **Feria
La Pantera Pulguera**, grabado sobre la web en producción
(<https://ferialapantera.com>) el 12 de noviembre de 2026, ya con las **reglas
de reserva actualizadas** y la fecha del **domingo 15 de noviembre**.

| Archivo | Qué es |
|---|---|
| `salida/como-reservar.mp4` | Video final, 1920×1080, 30 fps, **1:24 min**, ~9,5 MB (optimizado para web) |
| `salida/como-reservar-poster.jpg` | Portada (fotograma del título) |
| `salida/como-reservar.vtt` | Subtítulos en formato WebVTT |
| `guion/locucion-brian-v3.txt` | Texto de la locución, con pausas, tal como se pegó en ElevenLabs |
| `guion/guion.json` | Guion por escenas: texto narrado, capturas, clics, resaltados y rótulos |
| `guion/guion.md` | El texto de la locución, para leer |
| `audio/brian_v4_v3.mp3` | Locución completa: voz **Brian**, modelo **Eleven v4** |
| `audio/brian_v4_v3_stt.json` | Tiempos por palabra (speech-to-text de ElevenLabs) |
| `audio/<escena>.mp3/.json` | La locución cortada por escena, con tiempos por carácter |
| `capturas/` | Capturas HD reales de la web (`cajas.json`: posición de cada botón) |
| `scripts/cortar_pista.py` | Corta una locución completa en escenas usando los tiempos por palabra |
| `scripts/descargar_pista.py` | Busca una locución en el historial de ElevenLabs y la transcribe |
| `scripts/generar_voz.py` | Genera la locución escena por escena con la API de ElevenLabs |
| `scripts/montar_video.py` | Monta el video (cursor, zooms, resaltados, subtítulos, audio) |

## El tutorial, por escrito

1. Entra a **ferialapantera.com**. En la sede **El Polo** reservas y pagas en
   la web. **Surquillo** se reserva por WhatsApp, **cada miércoles desde las
   10:00 a. m.**
2. En El Polo, las reservas abren **cada lunes a las 10:00 a. m.**, con dos
   semanas de anticipación: para el sábado y el domingo de la semana siguiente.
3. **Crea tu cuenta** (nombre, correo, celular y contraseña) o, si ya tienes,
   **inicia sesión**.
4. Elige el **sábado o el domingo** y toca un stand libre en el **mapa**. El
   domingo, los **rosados** son de una cara (**S/ 85**) y los **naranjas** de
   dos caras (**S/ 110**).
5. En el carrito pulsa **«Continuar»**: el stand queda **apartado 8 minutos**;
   si el tiempo se acaba, vuelve a quedar libre.
6. Completa **nombre, DNI, celular y lo que vas a vender** y pulsa **«Ir al
   pago»**. No se alquilan stands para venta de alimentos.
7. Acepta los términos y pulsa **«Pagar»**: tarjeta o Yape en el formulario
   seguro de Culqi.
8. Con el pago confirmado verás tu **código de reserva**; también está en
   **«Mi cuenta»**.

## La voz

La locución la generó la cuenta desde la web de ElevenLabs con la voz **Brian**
y el modelo **Eleven v4** (estabilidad 50, similitud 75), pegando
`guion/locucion-brian-v3.txt`, y se subió a la sesión. Se transcribió con la
*speech-to-text* de ElevenLabs para obtener el tiempo de cada palabra (coincide
con el guion en un 98,9 %; la única diferencia es cómo se escribe la URL), y
`cortar_pista.py` la divide en las pausas entre frases. Así cada pantalla, clic
y subtítulo ocurre justo cuando Brian lo dice.

Con el plan gratuito, la API de ElevenLabs no permite usar voces de la
biblioteca como Brian (ni para texto a voz ni para el cambiador de voz): por eso
la locución se genera desde la web. Con un plan de pago, `generar_voz.py` puede
hacerlo directamente.

## Cómo ponerlo en la web

El componente `HowToBook` ya espera el video (16:9, MP4):

1. Copia `salida/como-reservar.mp4` y `salida/como-reservar-poster.jpg` a
   `public/videos/` del proyecto de la web.
2. En `src/lib/site.ts`, dentro de `HOW_TO`, pon:
   `video: { src: "/videos/como-reservar.mp4", poster: "/videos/como-reservar-poster.jpg" }`.

(Así lo indica el README de `Totisex/pantera-pulguera`; la rama `main` de
GitHub está desactualizada respecto a producción, así que conviene comprobarlo
en el código desplegado).

## Cómo regenerarlo

Requisitos: Python 3 con Pillow y numpy, y ffmpeg.

```bash
# 1. Generar la locución en la web de ElevenLabs con guion/locucion-brian-v3.txt, y luego:
ELEVENLABS_API_KEY=tu_clave python3 scripts/descargar_pista.py --clave "cada lunes"
# (o copiar el MP3 a audio/brian_v4_v3.mp3 y transcribirlo con tiempos por palabra)
python3 scripts/cortar_pista.py                     # una pista por escena
python3 scripts/montar_video.py --frames 3,35,63    # fotogramas sueltos para revisar
python3 scripts/montar_video.py                     # video completo en salida/
```

Si cambias el texto de la locución, actualiza también el `tts` de cada escena en
`guion/guion.json`: las anclas (`at`) son trozos de ese texto.

## Cómo se grabó (y qué datos aparecen)

- Las capturas son de la web real. Los datos visibles son de ejemplo (María
  Rodríguez, `maria@ejemplo.com`, `999 888 777`, DNI `12345678`); el registro
  se rellenó pero **no se envió**.
- Los pasos con sesión se hicieron con la cuenta de administración. En las
  capturas se sustituyeron, solo en el navegador, el «Panel» de la cabecera y los
  datos de «Mi cuenta» por los de María, y se ocultó el historial.
- Para grabar se apartó el stand 91 del domingo (reserva `PP-7PB4CW`) y se llegó
  a la página de pago **sin pagar**; el apartado expiró solo a los 8 minutos.
  Versiones anteriores dejaron también `PP-C5G7VH` y `PP-SNK8PJ`, expiradas.
- La tarjeta «¡Reserva confirmada!» del video es un gráfico, no una captura:
  no se hizo ningún pago.

## Cosas que vi en la web y conviene revisar

1. **Paso 3 de «Cómo reservar»:** dice «Nombre, celular, DNI y correo», pero el
   formulario pide nombre de contacto, DNI, celular y ¿qué vas a vender?
2. **Precios del sábado:** la web dice «Los sábados, cualquier stand cuesta lo
   mismo», pero el sábado 14 el stand 90 cuesta S/ 80.00 y el resto S/ 60.00.
3. **GitHub desactualizado:** `main` de `Totisex/pantera-pulguera` sigue en el
   13 de octubre; los cambios de producción (carrito, Culqi, reservas los
   lunes) no están en el repositorio.
4. **Reservas de prueba** `PP-C5G7VH`, `PP-SNK8PJ` y `PP-7PB4CW`: quedan como
   expiradas a nombre de la cuenta de administración; puedes borrarlas desde el
   panel.
