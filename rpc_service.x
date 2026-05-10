/*
 * Interfaz RPC para Auditoría de Mensajería
 *
 * Este archivo define la interfaz RPC que se usa para auditar
 * todas las operaciones realizadas en el sistema de mensajería.
 * El servidor se conecta a un servidor RPC para registrar qué
 * operaciones realizan los usuarios y cuándo
 *
 * Esto genera:
 *   - rpc_service.h       (definiciones)
 *   - rpc_service_svc.c   (código del servidor)
 *   - rpc_service_clnt.c  (código del cliente, que no usamos)
 *   - rpc_service_xdr.c   (código de serialización)
 */

program MSGAUDIT_PROG {
    version MSGAUDIT_VERS {
        /* 
         * Procedimiento RPC: LOG_OPERATION
         * 
         * Registra que un usuario ha realizado una operación.
         * Devuelve un int (1 si éxito, 0 si error).
         * 
         * Parámetros:
         *   - string user    : Nombre del usuario que realiza la operación
         *   - string operation : Nombre de la operación (REGISTER, SEND, etc.)
         *   - string filename  : Nombre del fichero (NULL para ops sin fichero)
         */
        int LOG_OPERATION(string user, string operation, string filename) = 1;
    } = 1;
} = 0x20000001;
