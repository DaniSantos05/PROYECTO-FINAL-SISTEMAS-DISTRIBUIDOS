# Usamos el prefijo '>' para las recetas en lugar de tabulaciones
.RECIPEPREFIX := >

# Definimos nuestro compilador y las banderas generales que utilizaremos
CC = gcc
CFLAGS = -Wall -Wextra -pedantic -std=c11 -pthread -g -I/usr/include/tirpc

# Establecemos banderas específicas para el código generado por RPC
# Así evitamos que los avisos por castings o parámetros sin usar nos ensucien la salida
RPC_CFLAGS = -Wall -Wextra -pedantic -std=c11 -pthread -g -I/usr/include/tirpc -Wno-cast-function-type -Wno-unused-parameter

# Incluimos la librería necesaria para el transporte RPC independiente (TIRPC)
RPC_LIBS = -ltirpc

# Definimos los nombres de nuestros archivos y ejecutables principales
TARGET = server
SRC = server.c
RPC_X = rpc_service.x
RPC_SERVER = rpc_server

# Agrupamos los archivos que rpcgen generará para nosotros
RPC_ALL_GEN = rpc_service.h rpc_service_clnt.c rpc_service_svc.c rpc_service_xdr.c

# Nuestra regla por defecto: compilamos el servidor principal
all: $(TARGET)

# Aquí gestionamos la construcción del servidor
$(TARGET): $(SRC) $(RPC_X)
># Primero, eliminamos archivos antiguos para asegurar una compilación limpia
>rm -f rpc_service.h rpc_service_clnt.c rpc_service_xdr.c server_tmp
# Generamos los archivos de cabecera y el cliente RPC de forma segura (multi-thread)
>rpcgen -N -M -h -o rpc_service.h $(RPC_X)
>rpcgen -N -M -c -o rpc_service_xdr.c $(RPC_X)
>rpcgen -N -M -l -o rpc_service_clnt.c $(RPC_X)
# Compilamos y enlazamos nuestro servidor con el cliente RPC para la auditoría
>$(CC) $(CFLAGS) $(SRC) rpc_service_clnt.c rpc_service_xdr.c -o server_tmp $(RPC_LIBS)
# Movemos el temporal al nombre final del ejecutable
>mv -f server_tmp $(TARGET)

# Comando rápido para que pongamos en marcha nuestro servidor
run-server: $(TARGET)
>./$(TARGET) -p 8888

# Atajo para lanzar nuestro cliente de Python
run-client:
>python3 client.py -s localhost -p 8888

# Proceso para compilar específicamente el servicio de auditoría RPC
rpc-compile: $(RPC_X)
# Limpiamos los restos de compilaciones RPC anteriores
>rm -f $(RPC_SERVER) rpc_server_tmp rpc_service.h rpc_service_svc.c rpc_service_xdr.c rpc_service_clnt.c rpc_service_svc.o rpc_service_xdr.o
# Generamos la infraestructura del servidor RPC
>rpcgen -N -M -h -o rpc_service.h $(RPC_X)
>rpcgen -N -M -c -o rpc_service_xdr.c $(RPC_X)
>rpcgen -N -M -s tcp -o rpc_service_svc.c $(RPC_X)
# Compilamos los objetos intermedios
>$(CC) $(RPC_CFLAGS) -c rpc_service_svc.c -o rpc_service_svc.o
>$(CC) $(RPC_CFLAGS) -c rpc_service_xdr.c -o rpc_service_xdr.o
# Creamos el ejecutable final del servidor de logs/auditoría
>$(CC) $(CFLAGS) rpc_service_svc.o rpc_service_xdr.o rpc_server.c -o rpc_server_tmp $(RPC_LIBS)
>mv -f rpc_server_tmp $(RPC_SERVER)

# Ejecutamos nuestro servidor RPC
run-rpc: rpc-compile
>./$(RPC_SERVER)

# Lanzamos nuestro servicio web Flask para la normalización de mensajes
run-web:
>python3 web_service.py --host 127.0.0.1 --port 5000

# Limpiamos absolutamente todo para dejar el directorio impecable
clean:
>rm -f $(TARGET) $(RPC_SERVER) server_tmp rpc_server_tmp *.o $(RPC_ALL_GEN)