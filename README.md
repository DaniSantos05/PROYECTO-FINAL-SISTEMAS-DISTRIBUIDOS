# PROYECTO-FINAL-SISTEMAS-DISTRIBUIDOS

Práctica final de **Sistemas Distribuidos** en la que estamos desarrollando un servicio de envío de mensajes entre usuarios registrados.  
En el estado actual del proyecto tenemos implementada la **parte 1**, que consiste en un **servidor concurrente y multihilo en C** y un **cliente concurrente y multihilo en Python**. :contentReference[oaicite:0]{index=0}

El sistema permite registrar usuarios, conectarlos al servicio, consultar qué usuarios están conectados, enviar mensajes, desconectarlos y darlos de baja.

Actualmente están implementadas las siguientes operaciones:
- `REGISTER`
- `UNREGISTER`
- `CONNECT`
- `DISCONNECT`
- `USERS`
- `SEND`
- `QUIT`

Además, el servidor guarda los mensajes pendientes cuando el destinatario está desconectado y se los envía cuando vuelve a conectarse. Una vez que un mensaje se entrega correctamente, se elimina del servidor. :contentReference[oaicite:1]{index=1}

## Requisitos

Para ejecutar el proyecto hace falta:
- Sistema operativo Linux o entorno compatible
- `gcc`
- `make`
- `python3`
- soporte para `pthreads`

## Instalación

1. Clonar o descargar el repositorio del proyecto
2. Compilar el servidor:
   - `make`
3. Limpiar archivos compilados si hace falta:
   - `make clean`

## Ejecución

### Servidor
Para arrancar el servidor hay que ejecutar en una terminal:

```bash
./server -p 8888