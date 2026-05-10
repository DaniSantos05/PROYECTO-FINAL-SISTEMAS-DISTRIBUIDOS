/*
 * Servidor RPC para Auditoría de Mensajería 
 *
 * Este programa implementa el servidor RPC que recibe notificaciones
 * del servidor de mensajería sobre operaciones de usuarios.
 *
 * Compilación:
 *   rpcgen -S tcp rpc_service.x
 *   gcc -Wall -Wextra -std=c11 -pthread \
 *       rpc_service_svc.c rpc_service_xdr.c rpc_server.c -o rpc_server
 *
 * Ejecución:
 *   export LOG_RPC_IP=localhost
 *   ./rpc_server
 */

/* Incluimos el archivo generado por rpcgen */
#include "rpc_service.h"

/* Incluimos librerías estándar */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <rpc/rpc.h>

/**
 * Implementación del procedimiento RPC: LOG_OPERATION
 *
 * Esta función se ejecuta en el servidor RPC cuando un cliente
 * (en este caso, el servidor de mensajería) quiere registrar
 * una operación de un usuario
 *
 * Parámetros:
 *   user      - Nombre del usuario
 *   operation - Nombre de la operación (REGISTER, SEND, CONNECT, etc.)
 *   filename  - Nombre del fichero (NULL para operaciones sin fichero)
 *
 * Retorna:
 *   1 si la operación fue registrada exitosamente
 *   0 si ocurrió un error
 */
int *log_operation_1_svc(char *user, char *operation, char *filename,
                         struct svc_req *rqstp) {
    /* Variable para almacenar el resultado */
    static int result = 1;  /* Por defecto, éxito */

    /* Verificamos que recibimos parámetros válidos */
    if (user == NULL || operation == NULL) {
        fprintf(stderr, "Error: Parámetros NULL\n");
        result = 0;
        return &result;
    }

    /* Obtenemos la hora actual para el timestamp */
    time_t now = time(NULL);
    struct tm *timeinfo = localtime(&now);
    char timestamp[32];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", timeinfo);

    /* Formateamos y mostramos el registro en pantalla */
    printf("[%s] %s %s", timestamp, user, operation);

    /* Si hay fichero adjunto, también lo mostramos */
    if (filename != NULL && strlen(filename) > 0) {
        printf(" %s", filename);
    }

    /* Completamos la línea */
    printf("\n");

    /* Forzamos la salida para asegurar que se ve inmediatamente */
    fflush(stdout);

    /* Retornamos 1 (éxito) */
    return &result;
}
