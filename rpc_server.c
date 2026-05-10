/*
 * Servidor RPC para registrar operaciones del sistema de mensajería.
 */

#include "rpc_service.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

/*
 * Procedimiento remoto LOG_OPERATION.
 *
 * Esta firma es la que espera rpcgen cuando se genera el código con:
 * rpcgen -N -M -s tcp
 */
bool_t log_operation_1_svc(
    char *user,
    char *operation,
    char *filename,
    int *result,
    struct svc_req *rqstp
) {
    time_t now;
    struct tm *timeinfo;
    char timestamp[32];

    (void)rqstp;

    if (result == NULL) {
        return FALSE;
    }

    *result = 0;

    if (user == NULL || operation == NULL) {
        fprintf(stderr, "RPC LOG ERROR: invalid parameters\n");
        return TRUE;
    }

    now = time(NULL);
    timeinfo = localtime(&now);

    if (timeinfo == NULL) {
        fprintf(stderr, "RPC LOG ERROR: could not get current time\n");
        return TRUE;
    }

    strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", timeinfo);

    printf("[%s] USER=%s OPERATION=%s", timestamp, user, operation);

    if (filename != NULL && strlen(filename) > 0) {
        printf(" FILE=%s", filename);
    }

    printf("\n");
    fflush(stdout);

    *result = 1;
    return TRUE;
}

/*
 * rpcgen espera esta función para liberar resultados del programa RPC.
 * En este caso el resultado es un int, así que realmente no hay memoria dinámica
 * que liberar, pero la función debe existir para que el enlace no falle.
 */
int msgaudit_prog_1_freeresult(
    SVCXPRT *transp,
    xdrproc_t xdr_result,
    caddr_t result
) {
    (void)transp;
    (void)xdr_result;
    (void)result;

    return TRUE;
}
