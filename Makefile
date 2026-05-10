.RECIPEPREFIX := >

CC = gcc
CFLAGS = -Wall -Wextra -pedantic -std=c11 -pthread -g -I/usr/include/tirpc
RPC_CFLAGS = -Wall -Wextra -pedantic -std=c11 -pthread -g -I/usr/include/tirpc -Wno-cast-function-type -Wno-unused-parameter
RPC_LIBS = -ltirpc

TARGET = server
SRC = server.c

RPC_X = rpc_service.x
RPC_SERVER = rpc_server

RPC_ALL_GEN = rpc_service.h rpc_service_clnt.c rpc_service_svc.c rpc_service_xdr.c

all: $(TARGET)

$(TARGET): $(SRC) $(RPC_X)
>rm -f rpc_service.h rpc_service_clnt.c rpc_service_xdr.c server_tmp
>rpcgen -N -M -h -o rpc_service.h $(RPC_X)
>rpcgen -N -M -c -o rpc_service_xdr.c $(RPC_X)
>rpcgen -N -M -l -o rpc_service_clnt.c $(RPC_X)
>$(CC) $(CFLAGS) $(SRC) rpc_service_clnt.c rpc_service_xdr.c -o server_tmp $(RPC_LIBS)
>mv -f server_tmp $(TARGET)

run-server: $(TARGET)
>./$(TARGET) -p 8888

run-client:
>python3 client.py -s localhost -p 8888

rpc-compile: $(RPC_X)
>rm -f $(RPC_SERVER) rpc_server_tmp rpc_service.h rpc_service_svc.c rpc_service_xdr.c rpc_service_clnt.c rpc_service_svc.o rpc_service_xdr.o
>rpcgen -N -M -h -o rpc_service.h $(RPC_X)
>rpcgen -N -M -c -o rpc_service_xdr.c $(RPC_X)
>rpcgen -N -M -s tcp -o rpc_service_svc.c $(RPC_X)
>$(CC) $(RPC_CFLAGS) -c rpc_service_svc.c -o rpc_service_svc.o
>$(CC) $(RPC_CFLAGS) -c rpc_service_xdr.c -o rpc_service_xdr.o
>$(CC) $(CFLAGS) rpc_service_svc.o rpc_service_xdr.o rpc_server.c -o rpc_server_tmp $(RPC_LIBS)
>mv -f rpc_server_tmp $(RPC_SERVER)

run-rpc: rpc-compile
>./$(RPC_SERVER)

run-web:
>python3 web_service.py --host 127.0.0.1 --port 5000

clean:
>rm -f $(TARGET) $(RPC_SERVER) server_tmp rpc_server_tmp *.o $(RPC_ALL_GEN)
