# Compilador de C y flags de compilación
CC = gcc
CFLAGS = -Wall -Wextra -pedantic -std=c11 -pthread -g
TARGET = server
SRC = server.c

# Por defecto, compilamos el servidor
all: $(TARGET)

# Regla para compilar el servidor
$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $(SRC) -o $(TARGET)

# Target para ejecutar el servidor en puerto 8888
run-server: $(TARGET)
	./$(TARGET) -p 8888

# Target para ejecutar el cliente con servidor local
run-client:
	python3 client.py -s localhost -p 8888

# Target para lanzar servidor y cliente simultáneamente (requiere tmux)
run-both: $(TARGET)
	@echo "Asegúrate de tener tmux instalado"
	tmux new-session -d -s messaging -x 180 -y 50
	tmux send-keys -t messaging "make run-server" Enter
	tmux split-window -t messaging -h
	tmux send-keys -t messaging "sleep 1 && make run-client" Enter
	tmux attach-session -t messaging

# Target para compilar el servidor RPC
rpc-compile: rpc_service.x
	rpcgen -S tcp rpc_service.x
	$(CC) $(CFLAGS) -c rpc_service_svc.c -o rpc_service_svc.o
	$(CC) $(CFLAGS) -c rpc_service_xdr.c -o rpc_service_xdr.o
	$(CC) $(CFLAGS) rpc_service_svc.o rpc_service_xdr.o rpc_server.c -o rpc_server

# Target para ejecutar el servicio RPC
run-rpc: rpc-compile
	./rpc_server

# Target para ejecutar el servicio web
run-web:
	python3 web_service.py --port 5000 --host 127.0.0.1

# Target para limpiar archivos compilados
clean:
	rm -f $(TARGET) rpc_server *.o rpc_service_svc.c rpc_service_xdr.c rpc_service_svc.h rpc_service_clnt.c

# Target para ayuda
help:
	@echo "================================"
	@echo "Targets disponibles:"
	@echo "================================"
	@echo "  make                - Compila el servidor (Parte 1)"
	@echo "  make run-server     - Ejecuta el servidor en puerto 8888"
	@echo "  make run-client     - Ejecuta el cliente (requiere servidor activo)"
	@echo "  make run-both       - Ejecuta servidor y cliente en tmux"
	@echo "  make rpc-compile    - Compila servidor RPC (Parte 2.3)"
	@echo "  make run-rpc        - Ejecuta servidor RPC"
	@echo "  make run-web        - Ejecuta servicio web (Parte 2.2)"
	@echo "  make clean          - Elimina archivos compilados"
	@echo "  make help           - Muestra esta ayuda"
	@echo "================================"

# Evitar que make intente compilar archivos llamados como estos targets
.PHONY: all run-server run-client run-both rpc-compile run-rpc run-web clean help