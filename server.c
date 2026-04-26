// Esta macro activa ciertas funciones POSIX que vamos a usar en el servidor,
// por ejemplo algunas relacionadas con sockets y red.
#define _POSIX_C_SOURCE 200112L

// Librería para trabajar con direcciones IP y conversiones como inet_pton e inet_ntop.
#include <arpa/inet.h>

// Librería para consultar errores del sistema con errno.
#include <errno.h>

// Librería para funciones de red como getaddrinfo.
#include <netdb.h>

// Librería con estructuras de red como sockaddr_in.
#include <netinet/in.h>

// Librería para crear y manejar hilos en C.
#include <pthread.h>

// Librería para trabajar con señales, como SIGINT.
#include <signal.h>

// Librería con tipos enteros de tamaño fijo, como uint8_t.
#include <stdint.h>

// Librería estándar de entrada y salida, para usar printf, fprintf, etc.
#include <stdio.h>

// Librería estándar para memoria dinámica, atoi, EXIT_SUCCESS, etc.
#include <stdlib.h>

// Librería para trabajar con cadenas, strcmp, strlen, strncpy, etc.
#include <string.h>

// Librería principal para sockets.
#include <sys/socket.h>

// Librería con tipos generales del sistema.
#include <sys/types.h>

// Librería para funciones como close y gethostname.
#include <unistd.h>


// Longitud máxima permitida para un nombre de usuario.
#define MAX_USERNAME_LEN 255

// Tamaño máximo permitido para un mensaje, contando también el byte final '\0'.
#define MAX_MESSAGE_BYTES 256

// Número máximo de conexiones pendientes que aceptará listen.
#define LISTEN_BACKLOG 50


// Esta estructura representa un mensaje pendiente de entrega.
typedef struct Message {
    // Nombre del usuario que envió el mensaje.
    char *sender;

    // Identificador numérico del mensaje.
    unsigned int id;

    // Texto del mensaje.
    char *text;

    // Puntero al siguiente mensaje pendiente de la cola.
    struct Message *next;
} Message;


// Esta estructura representa a un usuario registrado en el sistema.
typedef struct User {
    // Nombre del usuario.
    char *username;

    // Indica si el usuario está conectado o no.
    int connected;

    // IP del cliente cuando está conectado.
    char ip[INET_ADDRSTRLEN];

    // Puerto del hilo de escucha del cliente.
    int port;

    // Último identificador de mensaje asignado a este usuario como remitente.
    unsigned int last_message_id;

    // Primer mensaje pendiente de entrega para este usuario.
    Message *pending_head;

    // Último mensaje pendiente de entrega para este usuario.
    Message *pending_tail;

    // Puntero al siguiente usuario de la lista enlazada.
    struct User *next;
} User;


// Lista global de usuarios registrados.
static User *g_users = NULL;

// Mutex global para proteger el acceso concurrente a usuarios y mensajes.
static pthread_mutex_t g_users_mutex = PTHREAD_MUTEX_INITIALIZER;

// Variable global para saber si el servidor debe seguir funcionando.
static volatile sig_atomic_t g_running = 1;

// Descriptor del socket principal del servidor.
static int g_server_socket = -1;


// Esta estructura auxiliar se usa para pasar datos al hilo que atiende a cada cliente.
typedef struct ClientThreadArgs {
    // Descriptor del socket del cliente aceptado por el servidor.
    int client_fd;

    // IP del cliente remoto que se ha conectado al servidor.
    char peer_ip[INET_ADDRSTRLEN];
} ClientThreadArgs;


/* ========================= FUNCIONES AUXILIARES DE MEMORIA ========================= */


// Esta función crea una copia dinámica de una cadena.
static char *dup_string(const char *src) {
    // Aquí guardaremos la copia.
    char *copy = NULL;

    // Solo seguimos si la cadena de entrada no es NULL.
    if (src != NULL) {
        // Calculamos la longitud de la cadena.
        size_t len = strlen(src);

        // Reservamos memoria para copiarla, incluyendo el byte final '\0'.
        copy = (char *)malloc(len + 1);

        // Si la reserva salió bien...
        if (copy != NULL) {
            // ...copiamos la cadena completa.
            memcpy(copy, src, len + 1);
        }
    }

    // Devolvemos la copia, o NULL si falló algo.
    return copy;
}


// Esta función libera toda la memoria asociada a un mensaje.
static void free_message(Message *msg) {
    // Solo liberamos si el puntero es válido.
    if (msg != NULL) {
        // Liberamos el nombre del remitente.
        free(msg->sender);

        // Liberamos el texto del mensaje.
        free(msg->text);

        // Liberamos la propia estructura del mensaje.
        free(msg);
    }
}


// Esta función libera todos los mensajes de una lista enlazada.
static void free_all_messages(Message *head) {
    // Empezamos por el primer mensaje.
    Message *current = head;

    // Recorremos toda la lista.
    while (current != NULL) {
        // Guardamos el siguiente antes de liberar el actual.
        Message *next = current->next;

        // Liberamos el mensaje actual.
        free_message(current);

        // Avanzamos al siguiente.
        current = next;
    }
}


// Esta función libera toda la memoria asociada a un usuario.
static void free_user(User *user) {
    // Solo actuamos si el puntero es válido.
    if (user != NULL) {
        // Liberamos el nombre del usuario.
        free(user->username);

        // Liberamos todos sus mensajes pendientes.
        free_all_messages(user->pending_head);

        // Liberamos la propia estructura del usuario.
        free(user);
    }
}


/* ========================= FUNCIONES AUXILIARES DE RED ========================= */


// Esta función envía exactamente "length" bytes por el socket.
static ssize_t send_all(int fd, const void *buffer, size_t length) {
    // Convertimos el buffer a puntero a bytes.
    const char *ptr = (const char *)buffer;

    // Contador de bytes enviados en total.
    size_t sent_total = 0;

    // Mientras queden bytes por enviar...
    while (sent_total < length) {
        // Intentamos enviar lo que todavía falta.
        ssize_t sent_now = send(fd, ptr + sent_total, length - sent_total, 0);

        // Si send falla o devuelve 0...
        if (sent_now <= 0) {
            // ...devolvemos error.
            return -1;
        }

        // Sumamos lo enviado en esta iteración.
        sent_total += (size_t)sent_now;
    }

    // Si se envió todo correctamente, devolvemos el total.
    return (ssize_t)sent_total;
}


// Esta función envía un código de respuesta de 1 byte.
static int send_code(int fd, uint8_t code) {
    // Si se consiguió enviar exactamente 1 byte...
    if (send_all(fd, &code, 1) == 1) {
        // ...devolvemos éxito.
        return 0;
    }

    // Si no, devolvemos error.
    return -1;
}


// Esta función envía una cadena terminada en '\0'.
static int send_cstring(int fd, const char *text) {
    // Usaremos este puntero para decidir qué texto enviar realmente.
    const char *value = text;

    // Si la cadena es NULL...
    if (value == NULL) {
        // ...enviamos cadena vacía.
        value = "";
    }

    // Si conseguimos enviar toda la cadena incluyendo el byte '\0'...
    if (send_all(fd, value, strlen(value) + 1) == (ssize_t)(strlen(value) + 1)) {
        // ...devolvemos éxito.
        return 0;
    }

    // Si no, devolvemos error.
    return -1;
}


// Esta función recibe una cadena terminada en '\0' desde un socket.
static char *recv_cstring(int fd) {
    // Tamaño inicial del buffer.
    size_t capacity = 64;

    // Número de caracteres útiles ya leídos.
    size_t length = 0;

    // Reservamos memoria inicial para el buffer.
    char *buffer = (char *)malloc(capacity);

    // Si la reserva falla, devolvemos NULL.
    if (buffer == NULL) {
        return NULL;
    }

    // Bucle principal de lectura.
    while (1) {
        // Aquí guardaremos el byte recibido.
        char ch = '\0';

        // Recibimos exactamente 1 byte.
        ssize_t received = recv(fd, &ch, 1, 0);

        // Si recv falla o devuelve 0...
        if (received <= 0) {
            // ...liberamos el buffer y devolvemos NULL.
            free(buffer);
            return NULL;
        }

        // Si el buffer está a punto de llenarse...
        if (length + 1 >= capacity) {
            // ...duplicamos su capacidad.
            size_t new_capacity = capacity * 2;

            // Intentamos redimensionar el buffer.
            char *new_buffer = (char *)realloc(buffer, new_capacity);

            // Si realloc falla...
            if (new_buffer == NULL) {
                // ...liberamos el buffer anterior.
                free(buffer);

                // Y devolvemos NULL.
                return NULL;
            }

            // Si salió bien, actualizamos el buffer.
            buffer = new_buffer;

            // Actualizamos la capacidad disponible.
            capacity = new_capacity;
        }

        // Guardamos el byte recibido en el buffer.
        buffer[length] = ch;

        // Si ese byte es '\0'...
        if (ch == '\0') {
            // ...la cadena ha terminado y la devolvemos.
            return buffer;
        }

        // Si no era el final, avanzamos la longitud útil.
        length++;
    }
}


// Esta función se conecta al hilo de escucha de un cliente concreto.
static int connect_to_client_listener(const char *ip, int port) {
    // Descriptor del socket que usaremos.
    int fd = -1;

    // Dirección destino.
    struct sockaddr_in addr;

    // Creamos un socket TCP IPv4.
    fd = socket(AF_INET, SOCK_STREAM, 0);

    // Si socket falla...
    if (fd < 0) {
        // ...devolvemos error.
        return -1;
    }

    // Inicializamos la estructura de dirección a cero.
    memset(&addr, 0, sizeof(addr));

    // Indicamos que usaremos IPv4.
    addr.sin_family = AF_INET;

    // Guardamos el puerto en formato de red.
    addr.sin_port = htons((uint16_t)port);

    // Convertimos la IP de texto a formato binario.
    if (inet_pton(AF_INET, ip, &addr.sin_addr) != 1) {
        // Si la IP no es válida, cerramos el socket...
        close(fd);

        // ...y devolvemos error.
        return -1;
    }

    // Intentamos conectar con el cliente.
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        // Si falla la conexión, cerramos el socket...
        close(fd);

        // ...y devolvemos error.
        return -1;
    }

    // Si todo salió bien, devolvemos el socket conectado.
    return fd;
}


/* ========================= FUNCIONES AUXILIARES DE USUARIOS ========================= */


// Esta función busca un usuario por nombre.
// Ojo: se asume que el mutex global ya está bloqueado.
static User *find_user_locked(const char *username) {
    // Empezamos por el primer usuario de la lista.
    User *current = g_users;

    // Recorremos toda la lista enlazada.
    while (current != NULL) {
        // Si encontramos coincidencia, devolvemos ese usuario.
        if (strcmp(current->username, username) == 0) {
            return current;
        }

        // Si no coincide, avanzamos.
        current = current->next;
    }

    // Si no se encontró, devolvemos NULL.
    return NULL;
}


// Esta función calcula el siguiente identificador de mensaje para un remitente.
// Ojo: se asume que el mutex global ya está bloqueado.
static unsigned int next_message_id_locked(User *sender) {
    // Incrementamos el último ID asignado.
    sender->last_message_id++;

    // Si al incrementar se desbordó y volvió a 0...
    if (sender->last_message_id == 0) {
        // ...lo ponemos a 1, como pide el enunciado.
        sender->last_message_id = 1;
    }

    // Devolvemos el nuevo identificador.
    return sender->last_message_id;
}


// Esta función añade un mensaje a la cola de pendientes de un receptor.
// Ojo: se asume que el mutex global ya está bloqueado.
static int append_pending_message_locked(User *receiver, const char *sender, unsigned int id, const char *text) {
    // Reservamos memoria para el nuevo mensaje.
    Message *msg = (Message *)malloc(sizeof(Message));

    // Si la reserva falla, devolvemos error.
    if (msg == NULL) {
        return -1;
    }

    // Copiamos dinámicamente el nombre del remitente.
    msg->sender = dup_string(sender);

    // Copiamos dinámicamente el texto del mensaje.
    msg->text = dup_string(text);

    // Guardamos el identificador.
    msg->id = id;

    // Inicialmente no apunta a ningún siguiente.
    msg->next = NULL;

    // Si alguna de las copias falló...
    if (msg->sender == NULL || msg->text == NULL) {
        // ...liberamos todo lo reservado...
        free_message(msg);

        // ...y devolvemos error.
        return -1;
    }

    // Si la cola estaba vacía...
    if (receiver->pending_tail == NULL) {
        // ...este mensaje pasa a ser el primero...
        receiver->pending_head = msg;

        // ...y también el último.
        receiver->pending_tail = msg;
    } else {
        // Si ya había mensajes, lo añadimos al final.
        receiver->pending_tail->next = msg;

        // Actualizamos el puntero al último.
        receiver->pending_tail = msg;
    }

    // Devolvemos éxito.
    return 0;
}


// Esta función elimina de la cola un mensaje ya entregado.
// Ojo: se asume que el mutex global ya está bloqueado.
static void remove_pending_message_locked(User *receiver, const char *sender, unsigned int id) {
    // Puntero al mensaje anterior.
    Message *prev = NULL;

    // Empezamos por la cabeza de la cola.
    Message *current = receiver->pending_head;

    // Recorremos la cola.
    while (current != NULL) {
        // Si coinciden el ID y el remitente...
        if (current->id == id && strcmp(current->sender, sender) == 0) {
            // Si era el primero de la lista...
            if (prev == NULL) {
                // ...la nueva cabeza pasa a ser el siguiente.
                receiver->pending_head = current->next;
            } else {
                // Si no era el primero, enlazamos el anterior con el siguiente.
                prev->next = current->next;
            }

            // Si además era el último...
            if (receiver->pending_tail == current) {
                // ...actualizamos el final de la cola.
                receiver->pending_tail = prev;
            }

            // Liberamos el mensaje eliminado.
            free_message(current);

            // Ya hemos terminado.
            return;
        }

        // Avanzamos en la lista.
        prev = current;
        current = current->next;
    }
}


// Esta función cuenta cuántos usuarios hay conectados.
// Ojo: se asume que el mutex global ya está bloqueado.
static int count_connected_users_locked(void) {
    // Inicializamos el contador.
    int count = 0;

    // Empezamos por el primer usuario.
    User *current = g_users;

    // Recorremos toda la lista.
    while (current != NULL) {
        // Si el usuario actual está conectado...
        if (current->connected) {
            // ...sumamos uno.
            count++;
        }

        // Avanzamos al siguiente.
        current = current->next;
    }

    // Devolvemos el total.
    return count;
}


// Esta función crea una copia dinámica con los nombres de los usuarios conectados.
// Ojo: se asume que el mutex global ya está bloqueado.
static char **copy_connected_users_locked(int *count_out) {
    // Primero contamos cuántos conectados hay.
    int count = count_connected_users_locked();

    // Aquí guardaremos el array de cadenas.
    char **list = NULL;

    // Índice para ir rellenando la lista.
    int index = 0;

    // Empezamos por el primer usuario.
    User *current = g_users;

    // Inicializamos la salida.
    *count_out = 0;

    // Si hay al menos un usuario conectado...
    if (count > 0) {
        // ...reservamos memoria para el array de punteros.
        list = (char **)calloc((size_t)count, sizeof(char *));
    }

    // Si no había usuarios, o si la reserva salió bien...
    if (count == 0 || list != NULL) {
        // Recorremos la lista de usuarios.
        while (current != NULL) {
            // Si el usuario actual está conectado...
            if (current->connected) {
                // ...duplicamos su nombre y lo guardamos.
                list[index] = dup_string(current->username);

                // Si falló la copia de ese nombre...
                if (list[index] == NULL) {
                    // ...liberamos todo lo reservado hasta ahora.
                    int i;
                    for (i = 0; i < index; i++) {
                        free(list[i]);
                    }

                    // Liberamos también el array principal.
                    free(list);

                    // Dejamos la lista a NULL.
                    list = NULL;

                    // Dejamos el contador a 0.
                    count = 0;

                    // Terminamos saliendo de la función.
                    *count_out = 0;
                    return NULL;
                }

                // Si salió bien, avanzamos el índice.
                index++;
            }

            // Pasamos al siguiente usuario.
            current = current->next;
        }
    }

    // Guardamos el número de usuarios conectados.
    *count_out = count;

    // Devolvemos la lista.
    return list;
}


// Esta función libera un array de cadenas dinámicas.
static void free_string_array(char **list, int count) {
    // Variable de bucle.
    int i;

    // Si la lista es NULL, no hay nada que hacer.
    if (list == NULL) {
        return;
    }

    // Liberamos cada cadena individual.
    for (i = 0; i < count; i++) {
        free(list[i]);
    }

    // Liberamos el array principal.
    free(list);
}


/* ========================= ENVÍO ASÍNCRONO A CLIENTES ========================= */


// Esta función envía un mensaje normal al hilo de escucha de un cliente.
static int send_message_to_listener(const char *ip, int port, const char *sender, unsigned int id, const char *text) {
    // Socket conectado con el cliente destino.
    int fd = -1;

    // Cadena temporal para convertir el ID a texto.
    char id_text[32];

    // Convertimos el identificador numérico en cadena.
    snprintf(id_text, sizeof(id_text), "%u", id);

    // Intentamos conectarnos al hilo de escucha del cliente.
    fd = connect_to_client_listener(ip, port);

    // Si no se pudo conectar, devolvemos error.
    if (fd < 0) {
        return -1;
    }

    // Enviamos la operación y sus campos según el protocolo.
    if (send_cstring(fd, "SEND MESSAGE") != 0 ||
        send_cstring(fd, sender) != 0 ||
        send_cstring(fd, id_text) != 0 ||
        send_cstring(fd, text) != 0) {
        // Si algo falla, cerramos el socket...
        close(fd);

        // ...y devolvemos error.
        return -1;
    }

    // Cerramos la conexión con el cliente.
    close(fd);

    // Devolvemos éxito.
    return 0;
}


// Esta función envía al remitente el ACK de que su mensaje se ha entregado.
static int send_ack_to_listener(const char *ip, int port, unsigned int id) {
    // Socket conectado con el remitente.
    int fd = -1;

    // Cadena temporal para el identificador.
    char id_text[32];

    // Convertimos el ID a texto.
    snprintf(id_text, sizeof(id_text), "%u", id);

    // Intentamos conectar con el hilo de escucha del remitente.
    fd = connect_to_client_listener(ip, port);

    // Si no se pudo conectar, devolvemos error.
    if (fd < 0) {
        return -1;
    }

    // Enviamos la operación SEND MESS ACK y el identificador.
    if (send_cstring(fd, "SEND MESS ACK") != 0 ||
        send_cstring(fd, id_text) != 0) {
        // Si algo falla, cerramos el socket...
        close(fd);

        // ...y devolvemos error.
        return -1;
    }

    // Cerramos la conexión.
    close(fd);

    // Devolvemos éxito.
    return 0;
}


// Esta función marca a un usuario como desconectado si falla la entrega.
static void mark_user_disconnected_by_name(const char *username) {
    // Bloqueamos el mutex global.
    pthread_mutex_lock(&g_users_mutex);

    {
        // Buscamos al usuario.
        User *user = find_user_locked(username);

        // Si existe...
        if (user != NULL) {
            // ...lo marcamos como desconectado.
            user->connected = 0;

            // Borramos su IP.
            user->ip[0] = '\0';

            // Borramos su puerto.
            user->port = 0;
        }
    }

    // Desbloqueamos el mutex global.
    pthread_mutex_unlock(&g_users_mutex);
}


// Esta función intenta entregar todos los mensajes pendientes de un usuario.
static void deliver_pending_messages_for_user(const char *receiver_username) {
    // Esta variable controla si seguimos intentando entregar más mensajes.
    int keep_working = 1;

    // Bucle principal de entrega de mensajes pendientes.
    while (keep_working) {
        // Aquí guardaremos la IP del receptor.
        char receiver_ip[INET_ADDRSTRLEN];

        // Aquí guardaremos el puerto del receptor.
        int receiver_port = 0;

        // Aquí guardaremos el nombre del remitente.
        char sender_name[MAX_USERNAME_LEN + 1];

        // Aquí guardaremos una copia local del texto del mensaje.
        char *message_text = NULL;

        // Aquí guardaremos el ID del mensaje.
        unsigned int message_id = 0;

        // Indica si el receptor sigue conectado.
        int receiver_is_connected = 0;

        // Indica si el remitente sigue conectado para poder mandarle ACK.
        int sender_is_connected = 0;

        // Aquí guardaremos la IP del remitente.
        char sender_ip[INET_ADDRSTRLEN];

        // Aquí guardaremos el puerto del remitente.
        int sender_port = 0;

        // Indica si realmente encontramos un mensaje para entregar.
        int have_message = 0;

        // Inicializamos las cadenas a vacío.
        receiver_ip[0] = '\0';
        sender_name[0] = '\0';
        sender_ip[0] = '\0';

        // Bloqueamos el mutex para consultar la estructura global.
        pthread_mutex_lock(&g_users_mutex);

        {
            // Buscamos al usuario receptor.
            User *receiver = find_user_locked(receiver_username);

            // Solo seguimos si existe, está conectado y tiene mensajes pendientes.
            if (receiver != NULL && receiver->connected && receiver->pending_head != NULL) {
                // Tomamos el primer mensaje pendiente de su cola.
                Message *msg = receiver->pending_head;

                // Buscamos al remitente de ese mensaje.
                User *sender = find_user_locked(msg->sender);

                // Marcamos que el receptor estaba conectado.
                receiver_is_connected = 1;

                // Copiamos su IP.
                strncpy(receiver_ip, receiver->ip, sizeof(receiver_ip) - 1);
                receiver_ip[sizeof(receiver_ip) - 1] = '\0';

                // Copiamos su puerto.
                receiver_port = receiver->port;

                // Copiamos el nombre del remitente.
                strncpy(sender_name, msg->sender, sizeof(sender_name) - 1);
                sender_name[sizeof(sender_name) - 1] = '\0';

                // Copiamos el identificador del mensaje.
                message_id = msg->id;

                // Hacemos una copia local del texto.
                message_text = dup_string(msg->text);

                // Si el remitente existe y sigue conectado...
                if (sender != NULL && sender->connected) {
                    // ...marcamos que podremos enviarle ACK.
                    sender_is_connected = 1;

                    // Copiamos su IP.
                    strncpy(sender_ip, sender->ip, sizeof(sender_ip) - 1);
                    sender_ip[sizeof(sender_ip) - 1] = '\0';

                    // Copiamos su puerto.
                    sender_port = sender->port;
                }

                // Si conseguimos copiar el texto, ya hay mensaje listo.
                if (message_text != NULL) {
                    have_message = 1;
                }
            }
        }

        // Desbloqueamos el mutex.
        pthread_mutex_unlock(&g_users_mutex);

        // Si no había mensaje o el receptor ya no estaba conectado...
        if (!have_message || !receiver_is_connected) {
            // Liberamos la copia local del texto por si existe.
            free(message_text);

            // Y dejamos de trabajar.
            keep_working = 0;
        } else {
            // Si conseguimos enviar el mensaje al receptor...
            if (send_message_to_listener(receiver_ip, receiver_port, sender_name, message_id, message_text) == 0) {
                // ...y el remitente sigue conectado...
                if (sender_is_connected) {
                    // ...le enviamos el ACK de entrega.
                    send_ack_to_listener(sender_ip, sender_port, message_id);
                }

                // Volvemos a bloquear para eliminar el mensaje ya entregado.
                pthread_mutex_lock(&g_users_mutex);

                {
                    // Buscamos de nuevo al receptor.
                    User *receiver = find_user_locked(receiver_username);

                    // Si sigue existiendo...
                    if (receiver != NULL) {
                        // ...eliminamos el mensaje entregado de su cola.
                        remove_pending_message_locked(receiver, sender_name, message_id);
                    }
                }

                // Desbloqueamos el mutex.
                pthread_mutex_unlock(&g_users_mutex);

                // Mostramos por pantalla el envío real del mensaje.
                printf("s> SEND MESSAGE %u FROM %s TO %s\n", message_id, sender_name, receiver_username);

                // Forzamos la salida en consola.
                fflush(stdout);
            } else {
                // Si falló la entrega al receptor...
                mark_user_disconnected_by_name(receiver_username);

                // ...dejamos de intentar más entregas por ahora.
                keep_working = 0;
            }

            // Liberamos la copia local del texto.
            free(message_text);
        }
    }
}


/* ========================= GESTIÓN DE PETICIONES ========================= */


// Esta función atiende una petición REGISTER.
static void handle_register_request(int fd) {
    // Leemos el nombre del usuario que quiere registrarse.
    char *username = recv_cstring(fd);

    // Por defecto asumimos error general.
    uint8_t code = 2;

    // Solo seguimos si el nombre se recibió correctamente.
    if (username != NULL) {
        // Bloqueamos el mutex global.
        pthread_mutex_lock(&g_users_mutex);

        {
            // Comprobamos si ya existe ese usuario.
            User *existing = find_user_locked(username);

            // Si ya existe...
            if (existing != NULL) {
                // ...devolvemos código 1.
                code = 1;
            } else {
                // Si no existe, reservamos memoria para el nuevo usuario.
                User *new_user = (User *)calloc(1, sizeof(User));

                // Solo seguimos si la reserva salió bien.
                if (new_user != NULL) {
                    // Duplicamos su nombre.
                    new_user->username = dup_string(username);

                    // Si la copia del nombre salió bien...
                    if (new_user->username != NULL) {
                        // ...lo dejamos como desconectado inicialmente.
                        new_user->connected = 0;

                        // Inicializamos su IP vacía.
                        new_user->ip[0] = '\0';

                        // Inicializamos su puerto a 0.
                        new_user->port = 0;

                        // Su contador de mensajes empieza en 0.
                        new_user->last_message_id = 0;

                        // No tiene mensajes pendientes al principio.
                        new_user->pending_head = NULL;
                        new_user->pending_tail = NULL;

                        // Lo insertamos al principio de la lista global.
                        new_user->next = g_users;
                        g_users = new_user;

                        // Marcamos éxito.
                        code = 0;
                    } else {
                        // Si falló la copia del nombre, liberamos la estructura.
                        free(new_user);
                    }
                }
            }
        }

        // Desbloqueamos el mutex.
        pthread_mutex_unlock(&g_users_mutex);

        // Enviamos el código de respuesta al cliente.
        send_code(fd, code);

        // Mostramos por consola el resultado.
        if (code == 0) {
            printf("s> REGISTER %s OK\n", username);
        } else {
            printf("s> REGISTER %s FAIL\n", username);
        }

        // Forzamos la salida por consola.
        fflush(stdout);
    }

    // Liberamos la memoria del nombre recibido.
    free(username);
}


// Esta función atiende una petición UNREGISTER.
static void handle_unregister_request(int fd) {
    // Leemos el nombre del usuario que se quiere borrar.
    char *username = recv_cstring(fd);

    // Por defecto asumimos error general.
    uint8_t code = 2;

    // Solo seguimos si el nombre se recibió bien.
    if (username != NULL) {
        // Aquí guardaremos el usuario a borrar para liberarlo fuera del mutex.
        User *to_delete = NULL;

        // Bloqueamos el mutex global.
        pthread_mutex_lock(&g_users_mutex);

        {
            // Puntero al usuario anterior.
            User *prev = NULL;

            // Empezamos por el primero de la lista.
            User *current = g_users;

            // Variable para saber si se encontró.
            int found = 0;

            // Recorremos la lista buscando el nombre.
            while (current != NULL && !found) {
                // Si coincide el nombre...
                if (strcmp(current->username, username) == 0) {
                    // ...marcamos encontrado.
                    found = 1;
                } else {
                    // Si no coincide, avanzamos.
                    prev = current;
                    current = current->next;
                }
            }

            // Si no se encontró...
            if (!found) {
                // ...devolvemos código 1.
                code = 1;
            } else {
                // Si era el primero de la lista...
                if (prev == NULL) {
                    // ...la cabeza pasa a ser el siguiente.
                    g_users = current->next;
                } else {
                    // Si no era el primero, enlazamos el anterior con el siguiente.
                    prev->next = current->next;
                }

                // Lo desacoplamos de la lista.
                current->next = NULL;

                // Guardamos el puntero para liberarlo después.
                to_delete = current;

                // Marcamos éxito.
                code = 0;
            }
        }

        // Desbloqueamos el mutex.
        pthread_mutex_unlock(&g_users_mutex);

        // Si realmente había usuario a borrar...
        if (to_delete != NULL) {
            // ...liberamos toda su memoria.
            free_user(to_delete);
        }

        // Enviamos el código de respuesta al cliente.
        send_code(fd, code);

        // Mostramos por consola el resultado.
        if (code == 0) {
            printf("s> UNREGISTER %s OK\n", username);
        } else {
            printf("s> UNREGISTER %s FAIL\n", username);
        }

        // Forzamos la salida por consola.
        fflush(stdout);
    }

    // Liberamos el nombre recibido.
    free(username);
}


// Esta función atiende una petición CONNECT.
static void handle_connect_request(int fd, const char *peer_ip) {
    // Leemos el nombre del usuario.
    char *username = recv_cstring(fd);

    // Leemos el puerto de escucha del cliente.
    char *port_text = recv_cstring(fd);

    // Por defecto usamos código 3, que representa error general en CONNECT.
    uint8_t code = 3;

    // Aquí guardaremos el puerto convertido a entero.
    int port = 0;

    // Solo seguimos si ambas cadenas se recibieron bien.
    if (username != NULL && port_text != NULL) {
        // Convertimos el puerto de texto a entero.
        port = atoi(port_text);

        // Bloqueamos el mutex global.
        pthread_mutex_lock(&g_users_mutex);

        {
            // Buscamos al usuario.
            User *user = find_user_locked(username);

            // Si no existe...
            if (user == NULL) {
                // ...devolvemos código 1.
                code = 1;
            } else if (user->connected) {
                // Si ya estaba conectado, devolvemos código 2.
                code = 2;
            } else if (port <= 0 || port > 65535) {
                // Si el puerto es inválido, lo tratamos como error general.
                code = 3;
            } else {
                // Si todo está bien, lo marcamos como conectado.
                user->connected = 1;

                // Guardamos la IP desde la que llegó la conexión.
                strncpy(user->ip, peer_ip, sizeof(user->ip) - 1);
                user->ip[sizeof(user->ip) - 1] = '\0';

                // Guardamos el puerto de escucha del cliente.
                user->port = port;

                // Marcamos éxito.
                code = 0;
            }
        }

        // Desbloqueamos el mutex.
        pthread_mutex_unlock(&g_users_mutex);

        // Enviamos el código al cliente.
        send_code(fd, code);

        // Si la conexión fue correcta...
        if (code == 0) {
            // ...mostramos CONNECT OK.
            printf("s> CONNECT %s OK\n", username);

            // Forzamos la salida.
            fflush(stdout);

            // E intentamos entregarle todos sus mensajes pendientes.
            deliver_pending_messages_for_user(username);
        } else {
            // Si falló, mostramos CONNECT FAIL.
            printf("s> CONNECT %s FAIL\n", username);

            // Forzamos la salida.
            fflush(stdout);
        }
    }

    // Liberamos las cadenas recibidas.
    free(username);
    free(port_text);
}


// Esta función atiende una petición DISCONNECT.
static void handle_disconnect_request(int fd, const char *peer_ip) {
    // Leemos el nombre del usuario a desconectar.
    char *username = recv_cstring(fd);

    // Por defecto usamos código 3, que representa error general en DISCONNECT.
    uint8_t code = 3;

    // Solo seguimos si el nombre se recibió bien.
    if (username != NULL) {
        // Bloqueamos el mutex global.
        pthread_mutex_lock(&g_users_mutex);

        {
            // Buscamos al usuario.
            User *user = find_user_locked(username);

            // Si no existe...
            if (user == NULL) {
                // ...devolvemos código 1.
                code = 1;
            } else if (!user->connected) {
                // Si existe pero no estaba conectado, devolvemos código 2.
                code = 2;
            } else if (strcmp(user->ip, peer_ip) != 0) {
                // Si la IP no coincide con la que estaba conectada, error general.
                code = 3;
            } else {
                // Si todo está bien, lo marcamos como desconectado.
                user->connected = 0;

                // Borramos su IP.
                user->ip[0] = '\0';

                // Borramos su puerto.
                user->port = 0;

                // Marcamos éxito.
                code = 0;
            }
        }

        // Desbloqueamos el mutex.
        pthread_mutex_unlock(&g_users_mutex);

        // Enviamos el código de respuesta al cliente.
        send_code(fd, code);

        // Mostramos por consola el resultado.
        if (code == 0) {
            printf("s> DISCONNECT %s OK\n", username);
        } else {
            printf("s> DISCONNECT %s FAIL\n", username);
        }

        // Forzamos la salida.
        fflush(stdout);
    }

    // Liberamos el nombre recibido.
    free(username);
}


// Esta función atiende una petición SEND.
static void handle_send_request(int fd, const char *peer_ip) {
    // Leemos el nombre del remitente.
    char *sender_name = recv_cstring(fd);

    // Leemos el nombre del destinatario.
    char *receiver_name = recv_cstring(fd);

    // Leemos el texto del mensaje.
    char *message_text = recv_cstring(fd);

    // Por defecto asumimos error general.
    uint8_t code = 2;

    // Aquí guardaremos el identificador asignado al mensaje.
    unsigned int message_id = 0;

    // Esta variable indica si el receptor estaba conectado.
    int receiver_connected = 0;

    // Solo seguimos si se recibieron bien las tres cadenas.
    if (sender_name != NULL && receiver_name != NULL && message_text != NULL) {
        // Calculamos el tamaño del mensaje contando también el '\0'.
        size_t message_size = strlen(message_text) + 1;

        // Si el mensaje se pasa del tamaño máximo permitido...
        if (message_size > MAX_MESSAGE_BYTES) {
            // ...mantenemos error general.
            code = 2;
        } else {
            // Bloqueamos el mutex global.
            pthread_mutex_lock(&g_users_mutex);

            {
                // Buscamos al remitente.
                User *sender = find_user_locked(sender_name);

                // Buscamos al destinatario.
                User *receiver = find_user_locked(receiver_name);

                // Si alguno de los dos no existe...
                if (sender == NULL || receiver == NULL) {
                    // ...devolvemos código 1.
                    code = 1;
                } else if (!sender->connected || strcmp(sender->ip, peer_ip) != 0) {
                    // Si el remitente no estaba conectado o la IP no coincide, error general.
                    code = 2;
                } else {
                    // Si todo está bien, obtenemos el siguiente ID para este remitente.
                    message_id = next_message_id_locked(sender);

                    // Intentamos guardar el mensaje en la cola del destinatario.
                    if (append_pending_message_locked(receiver, sender_name, message_id, message_text) == 0) {
                        // Guardamos si el destinatario estaba conectado.
                        receiver_connected = receiver->connected;

                        // Marcamos éxito.
                        code = 0;
                    } else {
                        // Si no se pudo guardar, dejamos error general.
                        code = 2;
                    }
                }
            }

            // Desbloqueamos el mutex.
            pthread_mutex_unlock(&g_users_mutex);
        }

        // Enviamos el código de respuesta al cliente.
        send_code(fd, code);

        // Si todo fue bien...
        if (code == 0) {
            // ...convertimos el ID a texto...
            char id_text[32];

            // ...lo guardamos en la cadena temporal...
            snprintf(id_text, sizeof(id_text), "%u", message_id);

            // ...y se lo enviamos al remitente.
            send_cstring(fd, id_text);
        }

        // Si el mensaje fue aceptado...
        if (code == 0) {
            // ...y el destinatario estaba conectado...
            if (receiver_connected) {
                // ...intentamos entregarlo inmediatamente.
                //
                // OJO:
                // Aquí NO imprimimos "SEND MESSAGE ..." para no duplicarlo.
                // La impresión correcta se hace dentro de deliver_pending_messages_for_user()
                // cuando el mensaje se entrega de verdad.
                deliver_pending_messages_for_user(receiver_name);
            } else {
                // Si el destinatario no estaba conectado, dejamos el mensaje almacenado.
                printf("s> MESSAGE %u FROM %s TO %s STORED\n", message_id, sender_name, receiver_name);

                // Forzamos la salida en consola.
                fflush(stdout);
            }
        }
    }

    // Liberamos las cadenas recibidas.
    free(sender_name);
    free(receiver_name);
    free(message_text);
}


// Esta función atiende una petición USERS.
static void handle_users_request(int fd, const char *peer_ip) {
    // Leemos el nombre del usuario que hace la petición.
    char *requester = recv_cstring(fd);

    // Por defecto asumimos error general.
    uint8_t code = 2;

    // Aquí guardaremos la lista de usuarios conectados.
    char **connected_users = NULL;

    // Aquí guardaremos cuántos conectados hay.
    int count = 0;

    // Solo seguimos si el nombre se recibió bien.
    if (requester != NULL) {
        // Bloqueamos el mutex global.
        pthread_mutex_lock(&g_users_mutex);

        {
            // Buscamos al usuario que hace la petición.
            User *user = find_user_locked(requester);

            // Si no existe...
            if (user == NULL) {
                // ...devolvemos error general.
                code = 2;
            } else if (!user->connected || strcmp(user->ip, peer_ip) != 0) {
                // Si no está conectado o la IP no coincide, devolvemos código 1.
                code = 1;
            } else {
                // Si todo está bien, copiamos la lista de conectados.
                connected_users = copy_connected_users_locked(&count);

                // Si no hubo error al copiar...
                if (count == 0 || connected_users != NULL) {
                    // ...marcamos éxito.
                    code = 0;
                } else {
                    // Si falló la reserva de memoria, error general.
                    code = 2;
                }
            }
        }

        // Desbloqueamos el mutex.
        pthread_mutex_unlock(&g_users_mutex);

        // Enviamos el código de respuesta.
        send_code(fd, code);

        // Si fue éxito...
        if (code == 0) {
            // ...preparamos una cadena para enviar cuántos conectados hay...
            char count_text[32];

            // ...y una variable para recorrer la lista.
            int i;

            // Convertimos el número a texto.
            snprintf(count_text, sizeof(count_text), "%d", count);

            // Enviamos primero la cantidad de usuarios conectados.
            send_cstring(fd, count_text);

            // Luego enviamos los nombres, uno por uno.
            for (i = 0; i < count; i++) {
                send_cstring(fd, connected_users[i]);
            }

            // Mostramos por consola que la operación fue bien.
            printf("s> CONNECTEDUSERS OK\n");
        } else {
            // Si no fue bien, mostramos FAIL.
            printf("s> CONNECTEDUSERS FAIL\n");
        }

        // Forzamos la salida.
        fflush(stdout);
    }

    // Liberamos la lista de nombres copiados.
    free_string_array(connected_users, count);

    // Liberamos el nombre del solicitante.
    free(requester);
}


// Esta es la función principal del hilo que atiende a un cliente.
static void *client_thread_main(void *arg) {
    // Convertimos el puntero genérico al tipo correcto.
    ClientThreadArgs *thread_args = (ClientThreadArgs *)arg;

    // Aquí guardaremos el descriptor del socket del cliente.
    int fd = -1;

    // Aquí guardaremos la IP del cliente remoto.
    char peer_ip[INET_ADDRSTRLEN];

    // Aquí guardaremos la operación recibida.
    char *operation = NULL;

    // Si los argumentos del hilo son válidos...
    if (thread_args != NULL) {
        // ...copiamos el descriptor del cliente.
        fd = thread_args->client_fd;

        // Copiamos la IP remota.
        strncpy(peer_ip, thread_args->peer_ip, sizeof(peer_ip) - 1);
        peer_ip[sizeof(peer_ip) - 1] = '\0';

        // Liberamos la estructura auxiliar.
        free(thread_args);
    } else {
        // Si no había argumentos válidos, terminamos el hilo.
        pthread_exit(NULL);
    }

    // Leemos la operación enviada por el cliente.
    operation = recv_cstring(fd);

    // Si la operación se recibió correctamente...
    if (operation != NULL) {
        // Si la operación es REGISTER...
        if (strcmp(operation, "REGISTER") == 0) {
            // ...atendemos REGISTER.
            handle_register_request(fd);

        // Si la operación es UNREGISTER...
        } else if (strcmp(operation, "UNREGISTER") == 0) {
            // ...atendemos UNREGISTER.
            handle_unregister_request(fd);

        // Si la operación es CONNECT...
        } else if (strcmp(operation, "CONNECT") == 0) {
            // ...atendemos CONNECT.
            handle_connect_request(fd, peer_ip);

        // Si la operación es DISCONNECT...
        } else if (strcmp(operation, "DISCONNECT") == 0) {
            // ...atendemos DISCONNECT.
            handle_disconnect_request(fd, peer_ip);

        // Si la operación es SEND...
        } else if (strcmp(operation, "SEND") == 0) {
            // ...atendemos SEND.
            handle_send_request(fd, peer_ip);

        // Si la operación es USERS...
        } else if (strcmp(operation, "USERS") == 0) {
            // ...atendemos USERS.
            handle_users_request(fd, peer_ip);
        }
    }

    // Liberamos la cadena con el nombre de la operación.
    free(operation);

    // Cerramos el socket del cliente.
    close(fd);

    // Terminamos el hilo.
    pthread_exit(NULL);
}


/* ========================= SEÑALES Y ARRANQUE ========================= */


// Esta función maneja Ctrl+C.
static void handle_sigint(int signum) {
    // Indicamos que no vamos a usar el parámetro signum.
    (void)signum;

    // Marcamos que el servidor debe dejar de funcionar.
    g_running = 0;

    // Si el socket principal sigue abierto...
    if (g_server_socket >= 0) {
        // ...lo cerramos.
        close(g_server_socket);

        // Y lo invalidamos.
        g_server_socket = -1;
    }
}


// Esta función intenta obtener una IP local del servidor en formato texto.
static void get_local_ip_string(char *buffer, size_t size) {
    // Aquí guardaremos el nombre del host.
    char hostname[256];

    // Estructura de configuración para getaddrinfo.
    struct addrinfo hints;

    // Puntero al primer resultado de getaddrinfo.
    struct addrinfo *result = NULL;

    // Puntero para recorrer los resultados.
    struct addrinfo *current = NULL;

    // Variable para saber si ya encontramos una IP válida.
    int done = 0;

    // Por defecto ponemos 127.0.0.1.
    strncpy(buffer, "127.0.0.1", size - 1);
    buffer[size - 1] = '\0';

    // Si conseguimos obtener el nombre del host...
    if (gethostname(hostname, sizeof(hostname)) == 0) {
        // Inicializamos hints a cero.
        memset(&hints, 0, sizeof(hints));

        // Pedimos direcciones IPv4.
        hints.ai_family = AF_INET;

        // Pedimos sockets stream, es decir, TCP.
        hints.ai_socktype = SOCK_STREAM;

        // Si getaddrinfo encuentra resultados...
        if (getaddrinfo(hostname, NULL, &hints, &result) == 0) {
            // Empezamos por el primer resultado.
            current = result;

            // Recorremos resultados hasta encontrar una IP válida.
            while (current != NULL && !done) {
                // Interpretamos la dirección como sockaddr_in.
                struct sockaddr_in *addr = (struct sockaddr_in *)current->ai_addr;

                // Intentamos convertir la IP a texto.
                if (inet_ntop(AF_INET, &addr->sin_addr, buffer, (socklen_t)size) != NULL) {
                    // Si salió bien, terminamos.
                    done = 1;
                } else {
                    // Si no, probamos con el siguiente resultado.
                    current = current->ai_next;
                }
            }

            // Liberamos la memoria devuelta por getaddrinfo.
            freeaddrinfo(result);
        }
    }
}


// Esta función extrae el puerto a partir de los argumentos de la línea de comandos.
static int parse_port_from_args(int argc, char *argv[]) {
    // Inicializamos el puerto a un valor inválido.
    int port = -1;

    // Empezamos en 1 porque argv[0] es el nombre del programa.
    int i = 1;

    // Recorremos todos los argumentos.
    while (i < argc) {
        // Si encontramos "-p" y además hay un valor detrás...
        if (strcmp(argv[i], "-p") == 0 && (i + 1) < argc) {
            // ...convertimos ese valor a entero.
            port = atoi(argv[i + 1]);

            // Saltamos ambos argumentos.
            i += 2;
        } else {
            // Si no era "-p", seguimos con el siguiente.
            i++;
        }
    }

    // Devolvemos el puerto encontrado, o -1 si no había.
    return port;
}


// Esta es la función principal del servidor.
int main(int argc, char *argv[]) {
    // Leemos el puerto desde los argumentos.
    int port = parse_port_from_args(argc, argv);

    // Variable para setsockopt.
    int opt = 1;

    // Dirección del servidor.
    struct sockaddr_in server_addr;

    // Estructura para configurar SIGINT.
    struct sigaction sa;

    // Cadena donde guardaremos una IP local del servidor para mostrarla por pantalla.
    char local_ip[INET_ADDRSTRLEN];

    // Si el puerto no es válido...
    if (port < 1024 || port > 65535) {
        // ...mostramos el uso correcto...
        fprintf(stderr, "Usage: ./server -p <port>\n");

        // ...y terminamos con error.
        return EXIT_FAILURE;
    }

    // Inicializamos la estructura de señales a cero.
    memset(&sa, 0, sizeof(sa));

    // Indicamos qué función manejará SIGINT.
    sa.sa_handler = handle_sigint;

    // Inicializamos su máscara de señales vacía.
    sigemptyset(&sa.sa_mask);

    // Registramos el manejador de SIGINT.
    sigaction(SIGINT, &sa, NULL);

    // Ignoramos SIGPIPE para que el servidor no se caiga al escribir en un socket roto.
    signal(SIGPIPE, SIG_IGN);

    // Creamos el socket principal del servidor.
    g_server_socket = socket(AF_INET, SOCK_STREAM, 0);

    // Si socket falla...
    if (g_server_socket < 0) {
        // ...mostramos el error del sistema...
        perror("socket");

        // ...y terminamos.
        return EXIT_FAILURE;
    }

    // Permitimos reutilizar la dirección del socket.
    setsockopt(g_server_socket, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    // Inicializamos la dirección del servidor a cero.
    memset(&server_addr, 0, sizeof(server_addr));

    // Indicamos que usaremos IPv4.
    server_addr.sin_family = AF_INET;

    // Escucharemos en cualquier interfaz local.
    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);

    // Guardamos el puerto en formato de red.
    server_addr.sin_port = htons((uint16_t)port);

    // Asociamos el socket a esa dirección y puerto.
    if (bind(g_server_socket, (struct sockaddr *)&server_addr, sizeof(server_addr)) < 0) {
        // Si falla, mostramos el error.
        perror("bind");

        // Cerramos el socket principal.
        close(g_server_socket);

        // Terminamos con error.
        return EXIT_FAILURE;
    }

    // Ponemos el socket en modo escucha.
    if (listen(g_server_socket, LISTEN_BACKLOG) < 0) {
        // Si falla, mostramos el error.
        perror("listen");

        // Cerramos el socket principal.
        close(g_server_socket);

        // Terminamos con error.
        return EXIT_FAILURE;
    }

    // Obtenemos una IP local en texto para mostrarla al arrancar.
    get_local_ip_string(local_ip, sizeof(local_ip));

    // Mostramos el mensaje de inicio pedido por el enunciado.
    printf("s> init server %s:%d\n", local_ip, port);

    // Mostramos el prompt del servidor.
    printf("s>\n");

    // Forzamos la salida por pantalla.
    fflush(stdout);

    // Bucle principal del servidor mientras siga activo.
    while (g_running) {
        // Dirección del cliente que se conecta.
        struct sockaddr_in client_addr;

        // Longitud de la estructura anterior.
        socklen_t client_len = sizeof(client_addr);

        // Aceptamos una nueva conexión entrante.
        int client_fd = accept(g_server_socket, (struct sockaddr *)&client_addr, &client_len);

        // Si accept falla...
        if (client_fd < 0) {
            // ...y el servidor sigue corriendo...
            if (g_running) {
                // ...si no fue simplemente una interrupción, mostramos el error.
                if (errno != EINTR) {
                    perror("accept");
                }
            }
        } else {
            // Si la conexión se aceptó bien, reservamos memoria para los argumentos del hilo.
            ClientThreadArgs *args = (ClientThreadArgs *)malloc(sizeof(ClientThreadArgs));

            // Si la reserva salió bien...
            if (args != NULL) {
                // Identificador del nuevo hilo.
                pthread_t tid;

                // Guardamos el descriptor del cliente.
                args->client_fd = client_fd;

                // Intentamos convertir la IP del cliente a texto.
                if (inet_ntop(AF_INET, &client_addr.sin_addr, args->peer_ip, sizeof(args->peer_ip)) == NULL) {
                    // Si falla la conversión, ponemos una IP por defecto.
                    strncpy(args->peer_ip, "0.0.0.0", sizeof(args->peer_ip) - 1);
                    args->peer_ip[sizeof(args->peer_ip) - 1] = '\0';
                }

                // Creamos el hilo que atenderá a este cliente.
                if (pthread_create(&tid, NULL, client_thread_main, args) == 0) {
                    // Si el hilo se creó bien, lo dejamos detached.
                    pthread_detach(tid);
                } else {
                    // Si falla la creación del hilo, cerramos el socket del cliente...
                    close(client_fd);

                    // ...y liberamos la estructura auxiliar.
                    free(args);
                }
            } else {
                // Si no se pudo reservar memoria para args, cerramos la conexión.
                close(client_fd);
            }
        }
    }

    // Al salir del bucle principal, limpiamos toda la lista de usuarios.
    pthread_mutex_lock(&g_users_mutex);

    {
        // Empezamos por el primer usuario.
        User *current = g_users;

        // Recorremos toda la lista.
        while (current != NULL) {
            // Guardamos el siguiente antes de liberar el actual.
            User *next = current->next;

            // Liberamos el usuario actual.
            free_user(current);

            // Avanzamos al siguiente.
            current = next;
        }

        // Dejamos la lista global vacía.
        g_users = NULL;
    }

    // Desbloqueamos el mutex.
    pthread_mutex_unlock(&g_users_mutex);

    // Destruimos el mutex global.
    pthread_mutex_destroy(&g_users_mutex);

    // Terminamos el programa correctamente.
    return EXIT_SUCCESS;
}
