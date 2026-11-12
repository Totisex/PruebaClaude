# Tutorial: cómo reservar un stand en ferialapantera.com

Video tutorial con voz en off de ElevenLabs del flujo de reserva de la **Feria
La Pantera Pulguera**, grabado sobre la web en producción
(<https://ferialapantera.com>) el 12 de noviembre de 2026, con la fecha del
**domingo 15 de noviembre** (precios y colores de domingo).

| Archivo | Qué es |
|---|---|
| `salida/como-reservar.mp4` | Video final, 1920×1080, 30 fps, **1:09 min**, ~8 MB (optimizado para web) |
| `salida/como-reservar-poster.jpg` | Portada (fotograma del título) |
| `salida/como-reservar.vtt` | Subtítulos en formato WebVTT |
| `guion/guion.json` | Guion por escenas: texto narrado, capturas, clics, resaltados y rótulos |
| `guion/guion.md` | El texto de la locución, para leer |
| `audio/brian_v4.mp3` | Locución completa: voz **Brian - Social Media**, modelo **eleven_v4** |
| `audio/brian_v4_stt.json` | Tiempos por palabra (speech-to-text de ElevenLabs) |
| `audio/<escena>.mp3/.json` | La locución cortada por escena, con tiempos por carácter |
| `capturas/` | Capturas HD reales de la web (`cajas.json`: posición de cada botón) |
| `scripts/cortar_pista.py` | Corta una locución completa en escenas usando los tiempos por palabra |
| `scripts/generar_voz.py` | Genera la locución escena por escena con la API de ElevenLabs |
| `scripts/montar_video.py` | Monta el video (cursor, zooms, resaltados, subtítulos, audio) |

## La voz

Es la locución que la cuenta generó en ElevenLabs el 30 de octubre de 2026 con la
voz **Brian - Social Media** (masculina, latinoamericana) y el modelo
**eleven_v4** (historial `VITSWkG4mueK9n6Jn6nj`). Se descargó del historial, se
transcribió con la *speech-to-text* de ElevenLabs para obtener el tiempo de cada
palabra, y `cortar_pista.py` la divide en las pausas entre frases. Así cada
pantalla, clic y subtítulo ocurre justo cuando Brian lo dice; en dos pausas se
alargó el silencio para mostrar los precios del domingo y el paso al carrito.

Por qué no se generó una locución nueva: con el plan gratuito, la API de
ElevenLabs no permite usar voces de la biblioteca como Brian (error
`paid_plan_required`); desde la web de ElevenLabs sí se puede. Con un plan de
pago, `generar_voz.py` puede generar cualquier guion nuevo con Brian y
`eleven_v4` (poner `voice_id` y `model_id` en `guion/guion.json`).

## El tutorial, por escrito

1. Entra a **ferialapantera.com**. En la sede **El Polo** reservas y pagas en
   línea; para **Surquillo**, pulsa el botón de WhatsApp de esa sede.
2. Las reservas abren cada **martes a las 9:00 a. m.** para el sábado y el
   domingo.
3. **Crea tu cuenta** (nombre, correo, celular y contraseña) o, si ya tienes,
   **inicia sesión**.
4. Elige el **sábado o el domingo** y toca un stand libre en el **mapa**: verás
   su número y su precio. El domingo, los **rosados** son de una cara
   (**S/ 85**) y los **naranjas** de dos caras (**S/ 110**).
5. En el carrito pulsa **«Continuar»**: el stand queda **apartado 8 minutos**;
   si el tiempo se acaba, vuelve a quedar libre.
6. Completa **nombre, DNI, celular y lo que vas a vender** y pulsa **«Ir al pago»**.
7. Acepta los términos y pulsa **«Pagar»**: tarjeta o Yape en el formulario
   seguro de Culqi.
8. Con el pago confirmado verás tu **código de reserva**; tus reservas están en
   tu cuenta.

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
python3 scripts/cortar_pista.py                     # locución completa -> una pista por escena
python3 scripts/montar_video.py --frames 3,30,48    # fotogramas sueltos para revisar
python3 scripts/montar_video.py                     # video completo en salida/
```

Para usar otra locución completa: ponla en `audio/`, transcríbela con la
speech-to-text de ElevenLabs con tiempos por palabra, apunta `voice.pista` y
`voice.palabras` en el guion y ajusta el texto de cada escena (`tts`) a lo que
dice la voz.

## Cómo se grabó (y qué datos aparecen)

- Las capturas son de la web real. Los datos visibles son de ejemplo (María
  Rodríguez, `maria@ejemplo.com`, `999 888 777`, DNI `12345678`); el registro
  se rellenó pero **no se envió**.
- Los pasos con sesión se hicieron con la cuenta de administración. En las
  capturas se sustituyeron, solo en el navegador, el «Panel» de la cabecera y los
  datos de «Mi cuenta» por los de María, y se tapó el historial.
- Se apartaron stands para grabar (sábado 14: `PP-C5G7VH`; domingo 15:
  `PP-SNK8PJ`, stand 91) y se llegó a la página de pago **sin pagar**. Los
  apartados expiran solos a los 8 minutos.
- La tarjeta «¡Reserva confirmada!» del video es un gráfico, no una captura:
  no se hizo ningún pago.

## Cosas que vi en la web y conviene revisar

1. **Paso 3 de «Cómo reservar»:** dice «Nombre, celular, DNI y correo», pero el
   formulario pide nombre de contacto, DNI, celular y ¿qué vas a vender?
2. **Precios del sábado:** la web dice «Los sábados, cualquier stand cuesta lo
   mismo», pero el sábado 14 el stand 90 cuesta S/ 80.00 y el resto S/ 60.00.
3. **Locución vs. web:** la voz dice «para el sábado y el domingo de esa
   semana» (la web: «de la semana siguiente») y «Mis reservas» (en la web es
   «Mi cuenta → Reservas activas»).
4. **GitHub desactualizado:** `main` de `Totisex/pantera-pulguera` (13 de
   octubre) no tiene `/el-polo`, `/carrito` ni Culqi.
5. **Reservas de prueba** `PP-C5G7VH` y `PP-SNK8PJ`: quedan como expiradas a
   nombre de la cuenta de administración; puedes borrarlas desde el panel.
