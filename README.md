# PROYECTO-FINAL-SISTEMAS-DISTRIBUIDOS

## Descripción General

Práctica final de **Sistemas Distribuidos** en la que se desarrolla un **servicio de envío de mensajes entre usuarios registrados**, similar en concepto a aplicaciones como WhatsApp pero con funcionalidad simplificada

El proyecto está dividido en **dos partes**:

- **Parte 1**: Servidor concurrente multihilo en C + Cliente multihilo en Python
- **Parte 2**: Transferencia de ficheros, Servicio Web de normalización, y RPC para auditoría

En el estado actual del proyecto tenemos implementadas **todas las funcionalidades**

## Características Implementadas

### Parte 1 - Mensajería Básica 

El sistema permite:
- **REGISTER**: Registrar un nuevo usuario en el sistema
- **UNREGISTER**: Dar de baja un usuario del sistema
- **CONNECT**: Conectar un usuario y recibir mensajes asincronamente
- **DISCONNECT**: Desconectar un usuario
- **USERS**: Ver lista de usuarios conectados (con IP y puerto)
- **SEND**: Enviar mensajes de texto a otros usuarios
- **QUIT**: Salir del cliente

**Características técnicas**:
- Servidor concurrente multihilo (un hilo por cliente)
- Cliente multihilo (hilo principal + hilo de escucha de mensajes)
- Almacenamiento de mensajes pendientes cuando el destinatario está desconectado
- Entrega de mensajes pendientes cuando el usuario se conecta
- Confirmación de entrega (ACK) de mensajes
- Identificadores únicos para cada mensaje
- Sincronización con mutex para acceso concurrente

### Parte 2.1 - Transferencia de Ficheros

Extensión que permite:
- **SENDATTACH**: Enviar mensaje con fichero adjunto
- **GETFILE**: Descargar fichero de otro usuario
- Protocolo `SEND MESSAGE ATTACH` para recibir mensajes con ficheros
- Protocolo `GET FILE` para transferencias de ficheros directas entre clientes
- Cache de usuarios conectados con IP y puerto

### Parte 2.2 - Servicio Web 

Servicio web desarrollado en Python con Flask que:
- Normaliza mensajes eliminando espacios en blanco redundantes
- Endpoints REST para integración
- Se ejecuta en puerto 5000 por defecto
- Se integra automáticamente en el cliente

### Parte 2.3 - RPC 

Servicio de auditoría basado en ONC-RPC que:
- Registra todas las operaciones de usuarios
- Servicio RPC para logging centralizado
- Interface definida en `rpc_service.x`
- Se conecta mediante variable de entorno `LOG_RPC_IP`

## Requisitos del Sistema

Para ejecutar el proyecto necesitas:

- **Sistema operativo**: Linux o entorno compatible (WSL, Docker, etc.)
- **Compilador**: `gcc` versión 5.0 o superior
- **Make**: `make` para automatizar compilación
- **Python**: Python 3.6 o superior
- **Librerías C**: soporte para `pthreads` (incluido en Linux)
- **Python packages**: 
  - `flask` (para servicio web)
  - `requests` (para cliente)
- **Herramientas RPC** (opcional):
  - `rpcgen` (Sun RPC tools)

### Instalación de dependencias

**En Ubuntu/Debian**:
```bash
sudo apt-get update
sudo apt-get install build-essential python3 python3-pip
sudo pip3 install flask requests
```

**RPC tools (opcional)**:
```bash
sudo apt-get install rpcbind sunrpc
```

## Compilación

### Compilar servidor

```bash
# Limpia las compilaciones anteriores
make clean

# Compilamos el servidor
make

# O directamente:
gcc -Wall -Wextra -pedantic -std=c11 -pthread server.c -o server
```

### Compilar RPC

```bash
make rpc-compile

# O manualmente:
rpcgen -S tcp rpc_service.x
gcc -Wall -Wextra -pedantic -std=c11 -pthread \
    rpc_service_svc.c rpc_service_xdr.c rpc_server.c -o rpc_server
```

## Ejecutar el Proyecto

### Opción 1: Ejecución Simple

**Terminal 1 - Servidor**:
```bash
./server -p 8888
# Salida esperada:
# s> init server 127.0.0.1:8888
# s>
```

**Terminal 2 - Cliente 1**:
```bash
python3 client.py -s localhost -p 8888
# Luego en el prompt:
# c> REGISTER alicia
# c> CONNECT alicia
```

**Terminal 3 - Cliente 2**:
```bash
python3 client.py -s localhost -p 8888
# c> REGISTER pepe
# c> CONNECT pepe
```

### Opción 2: Ejecución Automática (requiere tmux)

```bash
make run-both
```

### Opción 3: Con todas las partes

**Terminal 1 - Servicio Web**:
```bash
python3 web_service.py --port 5000 --host 127.0.0.1
# Salida: Starting Web Service on 127.0.0.1:5000
```

**Terminal 2 - Servidor RPC**:
```bash
export LOG_RPC_IP=localhost
make run-rpc
# O manualmente:
./rpc_server
```

**Terminal 3 - Servidor Principal**:
```bash
export LOG_RPC_IP=localhost
./server -p 8888
```

**Terminal 4 - Cliente**:
```bash
python3 client.py -s localhost -p 8888
```

## Ejemplo de Sesión Completa

### Escenario: Dos usuarios intercambian mensajes y ficheros

**Cliente 1 (Alicia)**:
```
c> REGISTER alicia
c> REGISTER OK
c> CONNECT alicia
c> CONNECT OK
c> USERS
c> CONNECTED USERS (1 users connected) OK
alice :: 127.0.0.1 :: 54321
```

**Cliente 2 (Pepe)**:
```
c> REGISTER pepe
c> REGISTER OK
c> CONNECT pepe
c> CONNECT OK
c> SEND alice Hola Alicia, esto es un mensaje de prueba
c> SEND OK - MESSAGE 1
```

**Cliente 1 (Alicia recibe)**:
```
s> MESSAGE 1 FROM pepe
Hola Alicia, esto es un mensaje de prueba
END
```

**Cliente 2 (Pepe envía fichero)**:
```
# Crear un fichero de prueba
$ echo "Contenido del fichero" > /tmp/documento.txt

c> SENDATTACH alicia Aquí va mi documento /tmp/documento.txt
c> SENDATTACH OK - MESSAGE 2
```

**Cliente 1 (Alicia recibe confirmación y descargar fichero)**:
```
s> MESSAGE 2 FROM pepe
Aquí va mi documento
END
FILE /tmp/documento.txt

c> GETFILE pepe /tmp/documento.txt /tmp/descargado.txt
c> FILE TRANSFER OK

# Verificar que los ficheros son idénticos:
$ diff /tmp/documento.txt /tmp/descargado.txt
# (Sin salida = ficheros iguales)
```

## Protocolo de Comunicación

### Estructura General

Todos los mensajes siguen el protocolo **TCP con cadenas terminadas en `\0`**:

1. **Cadena de operación**: `REGISTER`, `SEND`, `SENDATTACH`, etc.
2. **Parámetros**: Cada uno es una cadena terminada en `\0`
3. **Respuesta**: Byte de código (0=éxito, 1=error usuario, 2=error general)
4. **Datos opcionales**: Según la operación

### Ejemplo: Operación SEND

**Cliente → Servidor**:
```
SEND\0           (operación)
alicia\0          (remitente)
pepe\0            (destinatario)
Hola mundo\0     (mensaje)
```

**Servidor → Cliente**:
```
0                (código: éxito)
1\0              (ID del mensaje)
```

### Ejemplo: Operación SENDATTACH

**Cliente → Servidor**:
```
SENDATTACH\0                 (operación)
alicia\0                      (remitente)
pepe\0                        (destinatario)
Aquí va un fichero\0        (mensaje)
/tmp/documento.txt\0         (fichero adjunto)
```

### Operación GET FILE

**Cliente → Servidor (Cliente remoto)**:
```
GET FILE\0              (operación)
alicia\0                 (quien solicita)
/tmp/documento.txt\0    (fichero remoto)
```

**Servidor (Cliente remoto) → Cliente**:
```
1024\0           (tamaño del fichero)
[datos binarios del fichero...]
```

## API del Servicio Web 

### POST /normalize

Normaliza un mensaje eliminando espacios en blanco redundantes

**Request**:
```json
{
  "message": "Hola    mundo   de    Python"
}
```

**Response**:
```json
{
  "normalized": "Hola mundo de Python"
}
```

### GET /health

Verifica que el servicio está activo

**Response**:
```json
{
  "status": "ok"
}
```

## Códigos de Respuesta del Servidor

| Código | Significado |
|--------|------------|
| 0 | Operación exitosa |
| 1 | Error específico del usuario (no existe, ya existe, etc.) |
| 2 | Error general (problema de comunicación, etc.) |
| 3 | Error general en operaciones específicas (CONNECT, DISCONNECT) |

## Estructura de Archivos

```
proyecto/
├── server.c              # Servidor en C (Parte 1 + 2)
├── client.py            # Cliente en Python (Parte 1 + 2)
├── web_service.py       # Servicio web Flask (Parte 2.2)
├── rpc_service.x        # Interfaz RPC (Parte 2.3)
├── rpc_server.c         # Servidor RPC (Parte 2.3)
├── Makefile             # Automatización de compilación
├── README.md            # Este archivo
└── autores.txt          # Información de autores
```

## Pruebas y Validación

### Test 1: Registro y conexión básica

```bash
# Terminal 1
./server -p 8888

# Terminal 2
python3 client.py -s localhost -p 8888
c> REGISTER testuser
c> CONNECT testuser
c> USERS
# Debería listar testuser con IP y puerto
```

### Test 2: Envío de mensaje a usuario desconectado

```bash
# Terminal 2
c> REGISTER alicia
c> CONNECT alicia

# Terminal 3
python3 client.py -s localhost -p 8888
c> REGISTER pepe
c> SEND alicia Mensaje de prueba
# Esperado: c> SEND OK - MESSAGE 1

# Terminal 2
# Debería recibir el mensaje almacenado

# Terminal 3
c> CONNECT pepe
# Alicia recibe el mensaje
```

### Test 3: Transferencia de ficheros

```bash
# Crear ficheros de prueba
echo "Contenido test" > /tmp/test1.txt

# Terminal 2
c> REGISTER alicia
c> CONNECT alicia

# Terminal 3
python3 client.py -s localhost -p 8888
c> REGISTER pepe
c> CONNECT pepe
c> SENDATTACH alicia Enviando fichero /tmp/test1.txt
# Esperado: c> SENDATTACH OK - MESSAGE 1

# Terminal 2
c> GETFILE pepe /tmp/test1.txt /tmp/descargado.txt
# Esperado: c> FILE TRANSFER OK

# Verificar contenido
diff /tmp/test1.txt /tmp/descargado.txt
```

### Test 4: Normalización de mensajes

```bash
# Asegurarse que el servicio web está corriendo en terminal aparte
python3 web_service.py --port 5000 --host 127.0.0.1

# Terminal cliente
c> SEND pepe Hola    mundo   con   espacios
# El servidor normalizará a: "Hola mundo con espacios"
```

## Variables de Entorno

### LOG_RPC_IP

Para activar auditoría RPC:

```bash
export LOG_RPC_IP=localhost
./server -p 8888
```

El servidor intentará conectar con el servicio RPC en esa IP

## Resolución de Problemas

### Error: "Address already in use"

El puerto 8888 ya está en uso. Cambiar puerto:
```bash
./server -p 9999
# En otro terminal:
python3 client.py -s localhost -p 9999
```

### Error: "Connection refused"

El servidor no está corriendo. Verificar:
```bash
ps aux | grep server
# Si no aparece, lanzar el servidor
./server -p 8888
```

### Error: "ModuleNotFoundError: No module named 'flask'"

Instalar flask:
```bash
pip3 install flask requests
```

### Error: "rpcgen: command not found"

Instalar herramientas RPC:
```bash
# Ubuntu/Debian
sudo apt-get install rpcbind sunrpc
```

## Documentación Técnica

### Arquitectura del Servidor

El servidor mantiene:
- **Lista de usuarios**: Lista enlazada con sincronización mediante mutex
- **Cola de mensajes por usuario**: FIFO de mensajes pendientes
- **IDs de mensaje**: Unsigned int que incrementa por usuario
- **Conexión cliente-servidor**: Socket TCP para peticiones
- **Conexión servidor-cliente**: Socket TCP asincrónico para notificaciones

### Thread Safety

Todas las operaciones sobre la estructura global de usuarios usan:
- `pthread_mutex_t` para sincronización
- Secciones críticas claramente delimitadas
- Liberación de memoria fuera del mutex cuando es posible

### Protocolo de Entrega de Mensajes

1. Cliente A envía mensaje a Cliente B (puede estar desconectado)
2. Servidor almacena mensaje en cola de B
3. Si B está conectado: servidor lo entrega inmediatamente
4. Si B está desconectado: se almacena para entrega posterior
5. Cuando B se conecta: servidor entrega todos pendientes
6. Después de entregar: servidor elimina mensaje
