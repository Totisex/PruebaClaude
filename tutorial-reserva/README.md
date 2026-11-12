# Tutorial: cómo reservar un stand en ferialapantera.com

Video tutorial con voz en off (ElevenLabs) del flujo de reserva de la **Feria La
Pantera Pulguera**, grabado sobre la web en producción
(<https://ferialapantera.com>) el 12 de noviembre de 2026.

| Archivo | Qué es |
|---|---|
| `salida/como-reservar.mp4` | Video final, 1920×1080, 30 fps, 3:01 min, ~17 MB (optimizado para web) |
| `salida/como-reservar-poster.jpg` | Portada (fotograma del título) |
| `salida/como-reservar.vtt` | Subtítulos en formato WebVTT |
| `guion/guion.json` | Guion por escenas: texto narrado, capturas, clics y resaltados |
| `guion/guion.md` | El mismo guion, para leer |
| `audio/*.mp3` / `audio/*.json` | Locución de ElevenLabs por escena y sus tiempos por carácter |
| `capturas/` | Capturas HD reales de la web (`cajas.json`: posición de cada botón) |
| `scripts/generar_voz.py` | Genera la locución con la API de ElevenLabs |
| `scripts/montar_video.py` | Monta el video (cursor, zooms, resaltados, subtítulos, audio) |

## El tutorial, por escrito

1. Entra a **ferialapantera.com**. En la sede **El Polo** reservas y pagas en
   línea; **Surquillo** se reserva por WhatsApp.
2. Toca **«Ver fechas y reservar»** (o **«Reservar stand»**).
3. En **Próximas fechas** elige tu día y toca **«Reservar mi stand»**. Las
   reservas abren cada martes a las 9:00 a. m. para el sábado y el domingo de
   la semana siguiente.
4. En el **mapa**, los stands rosados son de una cara y los blancos de dos
   caras; los rayados en gris no están disponibles. Al tocar un stand ves su
   precio y se agrega al carrito. Puedes elegir más de uno.
5. Abre el **carrito**, revisa los stands y el total y toca **«Entrar para
   continuar»**. El carrito se arma sin cuenta, pero para apartar hace falta una.
6. **Crea tu cuenta** (nombre completo, correo, celular y contraseña de 8+
   caracteres con letras y números) o **entra** con tu correo y contraseña.
7. En el carrito toca **«Continuar»**: el stand queda **apartado 8 minutos**.
8. Completa **tus datos**: nombre de contacto, DNI, celular y qué vas a vender
   (de todo, menos alimentos y bebidas). Toca **«Ir al pago»**.
9. En **«Confirma y paga»** revisa el código de reserva, la fecha, la sede y
   los stands; marca la casilla de términos y toca **«Pagar»**. Se paga con
   tarjeta o Yape en el formulario seguro de Culqi.
10. Con el pago confirmado el stand queda a tu nombre. Tus reservas están en
    **«Mi cuenta»**. Si se acaba el tiempo antes de pagar, el stand se libera.
11. **Surquillo**: toca **«Escribir por WhatsApp»** (+51 922 388 277).

## Cómo ponerlo en la web

El componente `HowToBook` ya espera el video (16:9, MP4):

1. Copia `salida/como-reservar.mp4` y `salida/como-reservar-poster.jpg` a
   `public/videos/` del proyecto de la web.
2. En `src/lib/site.ts`, dentro de `HOW_TO`, pon:
   `video: { src: "/videos/como-reservar.mp4", poster: "/videos/como-reservar-poster.jpg" }`.

(Así lo indica el README de `Totisex/pantera-pulguera`; la rama `main` de
GitHub está desactualizada respecto a producción, así que conviene comprobarlo
en el código que está desplegado).

## Cómo regenerarlo

Requisitos: Python 3 con Pillow y numpy, y ffmpeg.

```bash
ELEVENLABS_API_KEY=tu_clave python3 scripts/generar_voz.py      # todas las escenas
ELEVENLABS_API_KEY=tu_clave python3 scripts/generar_voz.py --solo 11_pago
python3 scripts/montar_video.py --frames 3,45,128   # fotogramas sueltos para revisar
python3 scripts/montar_video.py                     # video completo en salida/
```

Voz: **Sarah** (voz *premade* de ElevenLabs) con `eleven_multilingual_v2`. El
plan gratuito no permite usar por API voces de la biblioteca (como «Brian -
Social Media», que es nativa latinoamericana); con un plan de pago basta con
cambiar `voice_id` en `guion/guion.json` y regenerar. La pronunciación se
verificó transcribiendo cada pista con la *speech-to-text* de ElevenLabs.
«Culqi» se escribe «Cúlqui» en el texto narrado para que suene en español; el
subtítulo muestra «Culqi».

## Cómo se grabó (y qué datos aparecen)

- Las capturas son de la web real. Los datos que se ven son de ejemplo
  (María Rodríguez, `maria@ejemplo.com`, `999 888 777`, DNI `12345678`):
  el registro se rellenó pero **no se envió**.
- Para los pasos con sesión se usó la cuenta de administración. En las capturas
  se sustituyeron, solo en el navegador, el «Panel» de la cabecera y los datos
  de «Mi cuenta» por los de María, para que se vea lo mismo que ve un feriante.
- Se apartó el stand 91 del sábado 14 de noviembre (reserva `PP-C5G7VH`) y se
  llegó a la página de pago **sin pagar**. El apartado expiró solo a los 8
  minutos y el stand volvió a estar disponible.
- La pantalla «¡Reserva confirmada!» del video es una tarjeta gráfica, no una
  captura: no se hizo ningún pago real.

## Cosas que vi en la web y conviene revisar

1. **El paso 3 de «Cómo reservar»** dice «Nombre, celular, DNI y correo», pero
   el formulario pide *nombre de contacto, DNI, celular y ¿qué vas a vender?*
   (el correo sale de la cuenta).
2. **Precios del sábado:** la web dice «Los sábados, cualquier stand cuesta lo
   mismo», pero en el mapa del sábado 14 de noviembre el stand 90 cuesta
   S/ 80.00 (dos caras) y el resto S/ 60.00.
3. **GitHub desactualizado:** `main` de `Totisex/pantera-pulguera` (13 de
   octubre) no tiene `/el-polo`, `/carrito` ni Culqi, que sí están en producción.
4. **Reserva de prueba `PP-C5G7VH`:** quedó registrada (expirada) a nombre de la
   cuenta de administración; puedes borrarla o ignorarla en el panel.
