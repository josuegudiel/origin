# Manual de Origin v0.3

Bienvenido. Este manual te lleva desde "acabo de descargar la app" hasta "estoy gritándole comandos a mi nave en Stanton". Si te trabás en algún paso, saltá directo a la sección de diagnóstico o a las preguntas frecuentes al final.

---

## 1. ¿Qué es Origin?

Origin es un asistente de voz pensado para Star Citizen. Vos hablás (en español o en inglés), Origin entiende lo que dijiste y ejecuta las teclas correspondientes dentro del juego. Todo el procesamiento de audio ocurre en tu PC: no manda nada a Internet, no tiene cuentas, no tiene suscripciones. Cero pagos, cero servidores externos.

---

## 2. Antes de empezar

Antes de instalar, asegurate de tener todo esto a mano:

- **Windows 10 u 11**. Por ahora no hay versión para Mac ni para Linux.
- **Un micrófono** conectado y funcionando. Probalo en cualquier app (la Grabadora de Windows sirve) para confirmar que captura tu voz.
- **Star Citizen instalado**, en cualquier parche de la rama 4.x.
- Opcional: si querés usar el botón de un **HOTAS** como push-to-talk, conectalo antes de abrir Origin.
- Opcional: si querés activar el "modo IA" para comandos más libres, instalá **Ollama** desde https://ollama.com (lo explico más abajo).

---

## 3. Instalación

1. Entrá a la pestaña **Releases** del repositorio de Origin en GitHub.
2. Descargá el archivo `OriginSetup-0.3.X-small-v3.exe` (la X es el número de revisión actual).
3. Doble click. Si Windows SmartScreen te muestra un cartel azul, tocá **Más información** y después **Ejecutar de todas formas**. Pasa porque el instalador todavía no está firmado, no es nada raro.
4. El instalador copia los archivos en `%LOCALAPPDATA%\Programs\Origin\`. No pide permisos de administrador.
5. Te va a preguntar si querés que Origin se inicie con Windows. Te lo recomiendo si vas a usarlo seguido: arranca minimizado al tray y no molesta.
6. Cuando termina, vas a tener un acceso directo en el Escritorio y otro en el menú Inicio.

---

## 4. Primer arranque

1. Click en el acceso directo de Origin.
2. Aparece la ventana principal con una barra lateral a la izquierda (Panel, Comandos, Ajustes, Registros).
3. En el encabezado vas a ver el estado: durante los primeros ~5 segundos dice **"Cargando modelo…"** porque Whisper (el motor de reconocimiento de voz) está calentando.
4. Cuando termina, el estado cambia a **"Listo"**. A partir de ese momento Origin ya está escuchándote (cuando apretes el PTT).
5. El header tiene, de izquierda a derecha: el indicador de **estado**, los botones **ES / EN** para elegir idioma, el **dropdown de perfil** y el botón **Pausar**.

---

## 5. Importante: lanzá Origin como administrador

Star Citizen corre con Easy Anti-Cheat, que por seguridad ignora teclas mandadas por aplicaciones con menos privilegios que el juego. Si Origin reconoce tu voz pero el juego no reacciona, este es casi siempre el motivo.

Cómo arreglarlo (lo hacés una sola vez):

1. Click derecho en el acceso directo de Origin.
2. **Propiedades** → pestaña **Compatibilidad**.
3. Marcá **"Ejecutar este programa como administrador"**.
4. **Aceptar**.

A partir de ahora, cada vez que abras Origin va a pedir confirmación de UAC. Decí que sí.

---

## 6. Tu primer comando por voz

Hagamos una prueba simple antes de meternos en personalización.

1. Abrí Star Citizen y quedate en el menú principal (no entres en juego todavía, así no te explota nada si algo sale mal).
2. Volvé a la ventana de Origin un momento, verificá que diga **"Listo"** y que el perfil activo sea **Flight** (o el que vayas a probar).
3. Alt-tab de vuelta al juego.
4. **Mantené apretada la tecla F12.**
5. Decí claramente: **"pide hangar"**.
6. Soltá F12.

Si todo está bien, el juego debería abrir el panel de ATC pidiendo aterrizaje. Si no pasó nada, no te preocupes, andá a la próxima sección.

---

## 7. ¿Y si no funcionó? Diagnóstico

Recorré la lista de arriba hacia abajo, parando en el primer síntoma que coincida con el tuyo.

- **El estado nunca pasa de "Cargando modelo…" a "Listo"**: andá a la pestaña **Registros** y buscá errores relacionados con Whisper. Lo más común es que tu placa no tenga CUDA disponible y Origin esté cargando el modelo en CPU, lo que puede tardar bastante la primera vez. Esperá un minuto más antes de matarlo.
- **Mantengo F12 pero el VU meter del Panel no se mueve cuando hablo**: el micrófono no te está captando. Andá a **Ajustes → Audio** y elegí otro dispositivo de entrada. El VU meter de la pestaña Panel tiene que reaccionar en tiempo real cuando hablás.
- **El VU meter se mueve, dice "Grabando…" pero no matchea ningún comando**: el reconocimiento te escuchó pero no encontró una frase parecida. Bajá `fuzz_threshold` en **Ajustes → Reconocimiento** (default 75, probá 65). También revisá que la frase del preset coincida con cómo la decís vos.
- **Matchea el comando pero Star Citizen no responde**: dos posibilidades. La más probable es que Origin no esté corriendo como administrador (volvé a la sección 5). La otra es que las teclas del preset no coincidan con tus binds reales del juego (revisalas en la pestaña Comandos).
- **Origin se cierra solo o se cuelga**: abrí `%APPDATA%\Origin\logs\origin.log` y mirá las últimas líneas. Reportalo en el repo (sección 18).

---

## 8. El idioma (ES / EN)

En el header tenés dos botones, **ES** y **EN**. El que está prendido es el activo. Tocá el otro para cambiar.

El preset incluido cubre todos los comandos en los dos idiomas, así que podés alternar libremente sin perder funcionalidad. Si jugás con amigos angloparlantes y querés que ellos te escuchen dar comandos en inglés, pasalo a EN; si preferís sentirte cómodo, dejalo en ES.

---

## 9. Los perfiles

Origin trae estos perfiles preconfigurados:

- **Flight**: navegación, escudos, armas, modos de vuelo.
- **Mobiglas**: mapa estelar, journal, contactos, inventario.
- **FPS**: armas, granadas, equipo a pie.
- **EVA**: maniobras en gravedad cero.
- **Mining**: cabezal minero, modos del láser.
- **Quantum**: calibración y salto cuántico.
- **Combat**: combate aire-aire específico.
- **Salvage**: herramientas de salvamento.
- **Refuel**: operaciones de reabastecimiento.
- **Misc**: emotes, chat, capturas, miscelánea.

¿Por qué existen los perfiles? Porque la misma tecla puede significar cosas distintas según el contexto. Por ejemplo, "M" en Flight es modo misiles, pero "M" en Mining es modo minero. Al separarlos por perfiles, evitamos confusiones y mantenemos las frases más cortas.

Cambialo desde el **dropdown** del header, o con el atajo global **Ctrl+F12** que cicla al siguiente perfil sin que tengas que sacar las manos del HOTAS.

---

## 10. Personalizar comandos

Andá a la pestaña **Comandos**. Vas a ver una tabla editable con cada comando del perfil activo.

- **Frases**: lo que vos decís en voz alta. Podés tener varias para el mismo comando, separadas por coma. Por ejemplo, para "engage quantum" podés poner `engage quantum, salta, andá, hacé el salto`.
- **Teclas**: lo que Origin manda al juego cuando matchea. Si en tus binds de SC cambiaste "B" por "Q" para el salto cuántico, actualizalo acá.

Cuando edites algo, no te olvides de guardar (botón al pie de la tabla).

**Botón "Probar comando"**: hace una cuenta regresiva de 3 segundos y después ejecuta las teclas como si lo hubieras activado por voz. Te da tiempo de alt-tab al juego. Si no querés abrir SC para probar, abrí el Bloc de notas y mirá si las teclas aparecen ahí.

**Botón "Editar script"**: para usuarios avanzados. Permite escribir secuencias con pausas, variables y condiciones. Si solo necesitás "digo X → apreta esto", la columna Teclas ya alcanza. No te metas en scripts a menos que quieras orquestar secuencias largas (tipo "preparar nave para combate" que activa armas + escudos + modo SCM en orden).

---

## 11. TTS: Origin te contesta

Por default está activado. Cada vez que Origin matchea un comando, te lo confirma con voz natural usando Piper TTS, que también corre 100% local (no Internet).

Desde **Ajustes → TTS** podés:

- Subir o bajar el **volumen**.
- Cambiar la **velocidad** (si te parece muy lenta o muy apurada).
- Elegir **voz en español** y **voz en inglés** por separado.
- Tocar el botón **"Probar"** para escuchar una frase de muestra ("hola capitán") y confirmar que la voz elegida te gusta.

**Agregar voces nuevas**:

1. Entrá a https://huggingface.co/rhasspy/piper-voices.
2. Descargá el par de archivos: uno `.onnx` (el modelo) y uno `.onnx.json` (la configuración).
3. Copialos a `%APPDATA%\Origin\voices\`.
4. En Ajustes → TTS, click en **"Refrescar voces"**. La voz nueva debería aparecer en el dropdown.

Si en algún momento te molesta que Origin te conteste cada cosa que decís, desactivá el toggle **"Activar TTS"** y listo.

---

## 12. HOTAS: push-to-talk con joystick

Si usás un HOTAS y preferís dejar el teclado tranquilo:

1. Andá a **Ajustes → HOTAS**.
2. Activá el toggle **"Activar"**.
3. Click en **"Capturar botón"**. Tenés 5 segundos.
4. Apretá el botón del joystick que querés usar como PTT.
5. Origin lo bindea automáticamente. A partir de ahora, ese botón funciona igual que F12.

Funciona en paralelo con el teclado: podés usar F12 o el botón del HOTAS, los dos sirven. Útil si a veces estás con las manos en el HOTAS y a veces no.

---

## 12b. Head tracking: mover la cabeza para mirar en el juego

Origin puede usar tu **webcam** como head-tracker (parecido a Beam o TrackIR): movés la cabeza y el juego mira para ese lado. Ideal para mirar los espejos o la cabina de tu nave sin sacar las manos de los controles.

**Qué necesitás:** una webcam (la integrada de la laptop sirve). En Windows, Origin instala solo lo necesario; no hace falta hardware especial.

**Para el head-look en el juego (recomendado), necesitás OpenTrack** (gratis, https://github.com/opentrack/opentrack):

1. Instalá y abrí **OpenTrack**.
2. En OpenTrack, elegí **Input: "UDP over network"** y dejá el puerto en **4242**.
3. Elegí **Output: "freetrack 2.0 Enhanced"** (el que usa Star Citizen).
4. En Origin, andá a la página **"Cabeza"**, activá **"Activar head tracking"** y dejá **"Enviar a OpenTrack"** tildado.
5. Poné la cabeza derecha y mirando al frente, y apretá **"Centrar (calibrar)"**.
6. Dale **Start** en OpenTrack. Movés la cabeza y deberías ver la pose moverse en Origin y en OpenTrack.
7. En Star Citizen, activá TrackIR en las opciones y ya deberías tener head-look.

**Ajustes útiles** (página "Cabeza"):
- **Sensibilidad por eje**: subí el yaw/pitch si querés mirar más lejos con menos movimiento.
- **Invertir**: si un eje va al revés de lo que esperás, tildá "invert".
- **Zona muerta (deadzone)**: subila si tu cabeza tiembla un poco en reposo y no querés que el juego se mueva.
- **Suavizado**: más alto = más suave pero con un pelín de retraso.

**Gestos de cabeza → comandos** (opcional): además del head-look, podés hacer que un gesto dispare un comando. En la sección "Gestos → comandos" agregás filas: elegís el gesto (cabecear, negar, inclinar a un lado, acercarte/alejarte) y escribís el **ID del comando** de tu perfil que querés ejecutar. Por ejemplo: cabecear → `request_landing`.

**Privacidad:** el video de la webcam se procesa **localmente** en tu PC para estimar la pose; no se graba ni se envía a ningún lado. Lo único que sale por la red es la pose (6 números) por UDP a OpenTrack, en tu propia máquina (127.0.0.1) por default.

---

## 13. LLM: el "modo IA" opcional

Esto es para usuarios que quieren ir más allá del preset fijo. Requiere Ollama instalado.

**¿Para qué sirve?**: para frases libres que no están en la lista de comandos. Por ejemplo, si decís *"preparame para entrar a Crusader"*, el matcher fuzzy normal no va a encontrar nada que coincida exactamente, pero el LLM entiende la intención y arma una secuencia (target Crusader + activar quantum + engage) en base al catálogo del perfil activo.

**Setup**:

1. Instalá Ollama desde https://ollama.com (instalador estándar de Windows).
2. Abrí un terminal (PowerShell, cmd, lo que prefieras) y corré:
   ```
   ollama pull llama3.1:8b
   ```
   Esto descarga el modelo (~5 GB la primera vez, después queda cacheado).
3. Dejá `ollama serve` corriendo en background (en la mayoría de las instalaciones arranca solo).

**Activarlo en Origin**:

1. **Ajustes → LLM** → toggle **"Activar"**.
2. Click en **"Probar conexión"**. Si Ollama está corriendo, te va a decir **"Conexión OK"**.

**Cómo se dispara**: cuando el matcher fuzzy normal no llega al threshold pero hay algo de coincidencia parcial (te entendió palabras sueltas pero no una frase completa). En ese momento, Origin le pasa al LLM la transcripción más el catálogo de comandos del perfil activo, y el LLM decide qué ejecutar.

Si solo querés usar comandos fijos del preset, dejá esta sección desactivada y ahorrate la complicación.

---

## 14. Tray (bandeja del sistema)

Cuando cerrás la ventana de Origin con la X, **no se cierra**: se minimiza al tray (íconos junto al reloj de Windows). Sigue funcionando y escuchándote en background.

- **Click izquierdo** en el ícono: vuelve a abrir la ventana.
- **Click derecho** en el ícono: menú rápido con opciones de pausar, cambiar perfil, cambiar idioma, abrir ajustes o salir definitivamente.

Si querés cerrar Origin del todo, usá **Salir** desde el menú del tray.

---

## 15. Hotkeys globales

Estos atajos funcionan aunque la ventana esté minimizada o no tenga foco:

- **F12** (configurable en Ajustes): **PTT**. Apretá y mantené mientras hablás, soltá cuando terminás.
- **Ctrl+F12** (configurable): **cicla al siguiente perfil** sin tener que volver a la ventana.

Si F12 te choca con otra cosa (por ejemplo, screenshots de Steam), cambialo en **Ajustes → Hotkeys** por la tecla que prefieras.

---

## 16. Ajustes recomendados según uso

Te dejo tres "presets de tunning" según cómo planees usar Origin:

**Casual** (jugás a la noche, sin micrófono carísimo, no querés líos):
- `fuzz_threshold`: 70
- LLM: OFF
- TTS: ON

**Streamer o audio claro** (tenés un buen micrófono y querés precisión alta):
- `fuzz_threshold`: 80
- TTS volume: 0.5 (para que no tape tu voz en el stream)
- `cancel_on_ptt`: ON (cancela TTS apenas apretás PTT de vuelta)

**Power user con HOTAS** (querés todo, incluyendo IA):
- `fuzz_threshold`: 75
- HOTAS PTT activo, con F12 como backup
- LLM: ON

Probá uno, ajustá a gusto. Los valores no son sagrados.

---

## 17. Preguntas frecuentes

**¿Funciona offline?**
Sí, 100%. La única excepción es el fallback de LLM si activaste Ollama (y Ollama también corre local, así que tampoco necesita Internet una vez descargado el modelo).

**¿Origin manda mi audio a algún servidor?**
No. Todo el procesamiento (Whisper, matcher, TTS, LLM si lo activás) corre en tu PC. No hay telemetría.

**¿Funciona con VR?**
Sí. Origin no toca el output gráfico ni el audio del juego, solo manda teclas. Es transparente para SteamVR.

**¿Funciona con el push-to-talk de Discord al mismo tiempo?**
Sí, son hotkeys distintos. Asignale a Origin una tecla que no uses para Discord y los dos pueden convivir.

**¿Funciona en otros juegos además de Star Citizen?**
El motor sí, no hay nada atado al juego en sí. Lo que es específico de SC es el preset de comandos. Podés crear perfiles para otros juegos editando `%APPDATA%\Origin\commands.yaml` y armando tus propios comandos + teclas.

**¿Cómo respaldo mis perfiles personalizados?**
Copiá el archivo `%APPDATA%\Origin\commands.yaml`. Ahí está todo lo que editaste. Para restaurar, pegá el archivo en la misma ubicación de otra PC con Origin instalado.

**¿Cómo lo desinstalo?**
**Programas y características** del Panel de Control → **Origin** → **Desinstalar**. Eso borra `%LOCALAPPDATA%\Programs\Origin\` pero **deja intacta** la carpeta `%APPDATA%\Origin\` con tu configuración y voces, por si reinstalás más adelante. Si querés borrar absolutamente todo, eliminá esa carpeta a mano después.

---

## 18. Si encontrás un bug

El log completo de Origin vive en:

```
%APPDATA%\Origin\logs\origin.log
```

Ahí están todos los eventos, errores y trazas que necesitamos para diagnosticar. Cuando reportes un bug en el repo de GitHub:

1. Abrí un issue describiendo qué hacías, qué esperabas que pasara y qué pasó.
2. Adjuntá el log (o copiá y pegá las últimas 50 líneas si es muy grande).
3. Mencioná tu versión de Origin (la ves en **Ajustes → Acerca de**) y tu versión de Windows.

Cuanta más info pongas al principio, más rápido se resuelve. Gracias por ayudar a mejorar Origin.

---

¡Listo! Ya tenés todo para arrancar. Si seguís el manual hasta acá, deberías estar gritándole a tu Cutlass en menos de diez minutos. Buena cacería, capitán.
