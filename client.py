# Importamos Enum para poder definir un conjunto cerrado de valores,
# en este caso los códigos de retorno que usará el cliente.
from enum import Enum

# Importamos argparse para leer los argumentos que se pasan al ejecutar el programa.
import argparse

# Importamos socket porque toda la comunicación cliente-servidor
# y cliente-servidor-cliente se hace con sockets TCP.
import socket

# Importamos threading porque este cliente necesita varios hilos:
# uno principal para la consola y otro para escuchar mensajes entrantes.
import threading

# Importamos sys para poder acceder a sys.argv,
# es decir, a los argumentos de la línea de comandos.
import sys

# Importamos os para verificar existencia de ficheros (Parte 2.1).
import os

# Importamos re para procesamiento de expresiones regulares en comandos (Parte 2.1).
import re

# Importamos requests para comunicación con servicio web (Parte 2.2).
try:
    import requests
except ImportError:
    requests = None

# Definimos la clase principal del cliente.
class client:
    # Definimos una clase interna con los posibles códigos de retorno
    # que devolverán los métodos del cliente.
    class RC(Enum):
        # Este valor representa que la operación ha salido bien.
        OK = 0

        # Este valor representa un error general.
        ERROR = 1

        # Este valor representa un error relacionado con el usuario,
        # por ejemplo que no exista o que ya esté conectado.
        USER_ERROR = 2

    # Aquí guardaremos la IP o nombre del servidor.
    _server = None

    # Aquí guardaremos el puerto del servidor.
    _port = -1

    # Aquí guardaremos el nombre del usuario que está conectado actualmente
    # en esta instancia del cliente.
    _current_user = None

    # Este será el socket que usará el cliente para escuchar
    # mensajes asíncronos enviados por el servidor.
    _listener_socket = None

    # Aquí guardaremos el hilo que se queda escuchando esos mensajes.
    _listener_thread = None

    # Este evento sirve para indicarle al hilo de escucha cuándo debe parar.
    _listener_stop_event = threading.Event()

    # Este candado evita que dos hilos escriban a la vez en la consola
    # y se mezclen los mensajes.
    _print_lock = threading.Lock()

    # Cache de usuarios conectados con IP y puerto (Parte 2.1).
    _connected_users_cache = {}

    # URL del servicio web de normalización (Parte 2.2).
    _web_service_url = "http://localhost:5000"

    # Definimos un método estático para imprimir de forma segura.
    @staticmethod
    def _safe_print(message):
        # Entramos en una sección crítica para que solo un hilo imprima cada vez.
        with client._print_lock:
            # Imprimimos el mensaje y forzamos el vaciado del buffer con flush=True.
            print(message, flush=True)

    # Definimos un método auxiliar para conectarnos al servidor principal.
    @staticmethod
    def _connect_to_server():
        # Creamos un socket IPv4 de tipo TCP.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Nos conectamos al servidor usando la IP y el puerto almacenados en la clase.
        sock.connect((client._server, client._port))

        # Devolvemos el socket ya conectado.
        return sock

    # Definimos un método auxiliar para enviar cadenas siguiendo el protocolo.
    @staticmethod
    def _send_string(sock, value):
        # Si el valor es None, lo convertimos en cadena vacía
        # para no provocar errores al codificar.
        if value is None:
            value = ""

        # Si el valor no es ya una cadena, lo convertimos a string.
        if not isinstance(value, str):
            value = str(value)

        # Enviamos la cadena codificada en UTF-8 y le añadimos el byte nulo '\0'
        # porque el protocolo indica que todas las cadenas terminan así.
        sock.sendall(value.encode("utf-8") + b"\0")

    # Definimos un método para recibir exactamente un número concreto de bytes.
    @staticmethod
    def _recv_exact(sock, size):
        # Creamos un buffer vacío donde iremos acumulando los datos.
        data = bytearray()

        # Seguimos recibiendo hasta tener exactamente la cantidad pedida.
        while len(data) < size:
            # Pedimos justo los bytes que faltan.
            chunk = sock.recv(size - len(data))

            # Si no llega nada, significa que la conexión se ha cerrado antes de tiempo.
            if not chunk:
                raise ConnectionError("Socket closed unexpectedly")

            # Añadimos lo recibido al buffer.
            data.extend(chunk)

        # Devolvemos los datos finales convertidos a bytes.
        return bytes(data)

    # Definimos un método para recibir una cadena terminada en byte nulo.
    @staticmethod
    def _recv_string(sock, max_size=65536):
        # Creamos un buffer vacío para ir guardando la cadena.
        data = bytearray()

        # Leemos byte a byte hasta encontrar el final de cadena.
        while True:
            # Recibimos un solo byte.
            chunk = sock.recv(1)

            # Si no llega nada, la conexión se ha cortado antes de tiempo.
            if not chunk:
                raise ConnectionError("Socket closed unexpectedly")

            # Si el byte recibido es '\0', la cadena ha terminado.
            if chunk == b"\0":
                # Decodificamos todo lo acumulado y lo devolvemos como texto.
                return data.decode("utf-8", errors="replace")

            # Si no era el final, añadimos ese byte al buffer.
            data.extend(chunk)

            # Comprobamos que la cadena no crezca demasiado,
            # para evitar errores o bloqueos por datos incorrectos.
            if len(data) > max_size:
                raise ValueError("Received string is too large")

    # Definimos un método para leer el código de respuesta del servidor.
    @staticmethod
    def _recv_code(sock):
        # Leemos exactamente 1 byte y devolvemos su valor numérico.
        return client._recv_exact(sock, 1)[0]

    # Definimos un método para comprobar si el mensaje cumple el límite del protocolo.
    @staticmethod
    def _message_fits_protocol(message):
        # El mensaje debe ocupar como mucho 256 bytes contando también el '\0' final.
        return len(message.encode("utf-8") + b"\0") <= 256

    # Método auxiliar para normalizar mensajes con servicio web (Parte 2.2).
    @staticmethod
    def _normalize_message(message):
        # Si no está disponible el módulo requests, devolver sin cambios.
        if requests is None:
            return message

        try:
            # Enviar al servicio web
            response = requests.post(
                f"{client._web_service_url}/normalize",
                json={"message": message},
                timeout=2
            )
            
            # Si la respuesta es OK
            if response.status_code == 200:
                data = response.json()
                return data.get("normalized", message)
        except Exception:
            # Si hay error, devolver mensaje sin normalizar
            pass

        return message

    # Definimos el bucle que ejecutará el hilo de escucha.
    @staticmethod
    def _listener_loop():
        # Este bucle se mantiene activo mientras no se indique que debe parar.
        while not client._listener_stop_event.is_set():
            try:
                # Esperamos una conexión entrante en el socket de escucha del cliente.
                conn, _ = client._listener_socket.accept()

            # Si salta timeout, simplemente seguimos esperando.
            except socket.timeout:
                continue

            # Si ocurre un error con el socket...
            except OSError:
                # ...y además se nos ha pedido parar, salimos del bucle.
                if client._listener_stop_event.is_set():
                    break

                # Si no era por parada, seguimos escuchando.
                continue

            # Usamos with para que la conexión se cierre automáticamente al terminar.
            with conn:
                try:
                    # Ponemos un timeout por seguridad en esta conexión concreta.
                    conn.settimeout(3.0)

                    # Leemos la operación que nos envía el servidor.
                    operation = client._recv_string(conn)

                    # Si el servidor nos manda un mensaje de otro usuario...
                    if operation == "SEND MESSAGE":
                        # Leemos el nombre del remitente.
                        sender = client._recv_string(conn)

                        # Leemos el identificador del mensaje.
                        message_id = client._recv_string(conn)

                        # Leemos el texto del mensaje.
                        message = client._recv_string(conn, max_size=4096)

                        # Mostramos por pantalla la cabecera con el formato pedido.
                        client._safe_print(f"s> MESSAGE {message_id} FROM {sender}")

                        # Mostramos el contenido del mensaje.
                        client._safe_print(message)

                        # Mostramos END para cerrar el bloque visual del mensaje.
                        client._safe_print("END")

                    # Si el servidor nos manda un mensaje con fichero adjunto (Parte 2.1)...
                    elif operation == "SEND MESSAGE ATTACH":
                        # Leemos el nombre del remitente.
                        sender = client._recv_string(conn)

                        # Leemos el identificador del mensaje.
                        message_id = client._recv_string(conn)

                        # Leemos el texto del mensaje.
                        message = client._recv_string(conn, max_size=4096)

                        # Leemos el nombre del fichero adjunto (Parte 2.1).
                        filename = client._recv_string(conn)

                        # Mostramos por pantalla la cabecera.
                        client._safe_print(f"s> MESSAGE {message_id} FROM {sender}")

                        # Mostramos el contenido del mensaje.
                        client._safe_print(message)

                        # Mostramos END.
                        client._safe_print("END")

                        # Mostramos el fichero adjunto (Parte 2.1).
                        client._safe_print(f"FILE {filename}")

                    # Si el servidor nos manda la confirmación de entrega de un mensaje nuestro...
                    elif operation == "SEND MESS ACK":
                        # Leemos el identificador del mensaje entregado.
                        message_id = client._recv_string(conn)

                        # Informamos por pantalla de que ese mensaje se ha entregado bien.
                        client._safe_print(f"c> SEND MESSAGE {message_id} OK")

                    # Si el servidor nos manda ACK con fichero adjunto (Parte 2.1)...
                    elif operation == "SEND MESS ATTACH ACK":
                        # Leemos el identificador del mensaje.
                        message_id = client._recv_string(conn)

                        # Leemos el nombre del fichero (Parte 2.1).
                        filename = client._recv_string(conn)

                        # Informamos por pantalla (Parte 2.1).
                        client._safe_print(f"c> SENDATTACH MESSAGE {message_id} {filename} OK")

                    # Si nos piden descargar un fichero (Parte 2.1)...
                    elif operation == "GET FILE":
                        # Leemos quien lo solicita.
                        requester = client._recv_string(conn)

                        # Leemos el nombre del fichero solicitado.
                        requested_file = client._recv_string(conn)

                        try:
                            # Verificar que el fichero existe.
                            if not os.path.exists(requested_file):
                                # Enviar tamaño 0 = error
                                client._send_string(conn, "0")
                            else:
                                # Obtener tamaño del fichero.
                                file_size = os.path.getsize(requested_file)

                                # Enviar tamaño.
                                client._send_string(conn, str(file_size))

                                # Enviar contenido del fichero en chunks.
                                with open(requested_file, 'rb') as f:
                                    while True:
                                        chunk = f.read(4096)
                                        if not chunk:
                                            break
                                        conn.sendall(chunk)
                        except Exception:
                            # Si hay error, intentamos enviar 0.
                            try:
                                client._send_string(conn, "0")
                            except Exception:
                                pass

                # Si ocurre cualquier error al procesar esa notificación...
                except Exception:
                    # ...lo ignoramos para que el hilo siga vivo y pueda seguir recibiendo más.
                    continue

    # Definimos el método que arranca el socket y el hilo de escucha.
    @staticmethod
    def _start_listener():
        # Si ya existe un hilo de escucha y sigue vivo, no lo volvemos a crear.
        if client._listener_thread is not None and client._listener_thread.is_alive():
            # En ese caso devolvemos el puerto donde ya estaba escuchando.
            return client._listener_socket.getsockname()[1]

        # Creamos un socket TCP para escuchar conexiones entrantes del servidor.
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Permitimos reutilizar la dirección para evitar problemas al reiniciar rápido.
        listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Lo asociamos a cualquier interfaz local y al puerto 0,
        # lo que hace que el sistema elija un puerto libre automáticamente.
        listen_socket.bind(("", 0))

        # Ponemos el socket en modo escucha.
        listen_socket.listen()

        # Añadimos timeout para que accept no se quede bloqueado indefinidamente.
        listen_socket.settimeout(0.5)

        # Guardamos el socket en el atributo de la clase.
        client._listener_socket = listen_socket

        # Reiniciamos el evento de parada.
        client._listener_stop_event = threading.Event()

        # Creamos el hilo de escucha indicando qué función debe ejecutar.
        client._listener_thread = threading.Thread(
            target=client._listener_loop,
            daemon=True
        )

        # Arrancamos el hilo.
        client._listener_thread.start()

        # Devolvemos el puerto que el sistema ha asignado al socket.
        return listen_socket.getsockname()[1]

    # Definimos el método que detiene el hilo y cierra el socket de escucha.
    @staticmethod
    def _stop_listener():
        # Marcamos el evento para decirle al hilo que debe pararse.
        client._listener_stop_event.set()

        # Si el socket de escucha existe...
        if client._listener_socket is not None:
            try:
                # ...intentamos cerrarlo.
                client._listener_socket.close()
            except OSError:
                # Si da error al cerrar, lo ignoramos.
                pass

        # Si el hilo existe, sigue vivo y además no somos nosotros mismos ese hilo...
        if (
            client._listener_thread is not None
            and client._listener_thread.is_alive()
            and threading.current_thread() is not client._listener_thread
        ):
            # ...esperamos un poco a que termine correctamente.
            client._listener_thread.join(timeout=1.0)

        # Dejamos las referencias a None porque ya no hay escucha activa.
        client._listener_socket = None
        client._listener_thread = None

    # Método para registrar un usuario en el sistema.
    @staticmethod
    def register(user):
        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación REGISTER.
                client._send_string(sock, "REGISTER")

                # Enviamos el nombre del usuario a registrar.
                client._send_string(sock, user)

                # Recibimos el código de respuesta del servidor.
                code = client._recv_code(sock)

        # Si falla la conexión o cualquier parte del protocolo...
        except Exception:
            # Mostramos el mensaje de error correspondiente.
            client._safe_print("c> REGISTER FAIL")

            # Devolvemos código de error general.
            return client.RC.ERROR

        # Si el código es 0, el registro ha salido bien.
        if code == 0:
            client._safe_print("c> REGISTER OK")
            return client.RC.OK

        # Si el código es 1, el nombre ya estaba registrado.
        if code == 1:
            client._safe_print("c> USERNAME IN USE")
            return client.RC.USER_ERROR

        # Cualquier otro caso se trata como error general.
        client._safe_print("c> REGISTER FAIL")
        return client.RC.ERROR

    # Método para dar de baja un usuario.
    @staticmethod
    def unregister(user):
        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación UNREGISTER.
                client._send_string(sock, "UNREGISTER")

                # Enviamos el nombre del usuario que queremos borrar.
                client._send_string(sock, user)

                # Leemos el código de respuesta del servidor.
                code = client._recv_code(sock)

        # Si algo falla en la comunicación...
        except Exception:
            # Mostramos error.
            client._safe_print("c> UNREGISTER FAIL")

            # Devolvemos error general.
            return client.RC.ERROR

        # Si el código es 0, la baja se ha hecho bien.
        if code == 0:
            # Si justo ese usuario era el que estaba conectado en este cliente...
            if client._current_user == user:
                # ...paramos el hilo de escucha...
                client._stop_listener()

                # ...y borramos el usuario actual.
                client._current_user = None

            # Mostramos mensaje de éxito.
            client._safe_print("c> UNREGISTER OK")

            # Devolvemos OK.
            return client.RC.OK

        # Si el código es 1, el usuario no existía.
        if code == 1:
            client._safe_print("c> USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        # Cualquier otro caso es error general.
        client._safe_print("c> UNREGISTER FAIL")
        return client.RC.ERROR

    # Método para conectar un usuario al sistema.
    @staticmethod
    def connect(user):
        # Si ya hay un usuario conectado en este cliente, no permitimos otro.
        if client._current_user is not None:
            client._safe_print("c> USER ALREADY CONNECTED")
            return client.RC.USER_ERROR

        try:
            # Primero arrancamos el hilo de escucha,
            # porque el servidor podría mandar mensajes en cuanto conectemos.
            listen_port = client._start_listener()

        # Si no se puede arrancar la escucha, fallamos directamente.
        except Exception:
            client._safe_print("c> CONNECT FAIL")
            return client.RC.ERROR

        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación CONNECT.
                client._send_string(sock, "CONNECT")

                # Enviamos el nombre del usuario.
                client._send_string(sock, user)

                # Enviamos el puerto donde este cliente escuchará mensajes.
                client._send_string(sock, str(listen_port))

                # Leemos el código de respuesta.
                code = client._recv_code(sock)

        # Si falla la comunicación con el servidor...
        except Exception:
            # ...paramos la escucha porque realmente no se ha conectado.
            client._stop_listener()

            # Mostramos error.
            client._safe_print("c> CONNECT FAIL")

            # Devolvemos error general.
            return client.RC.ERROR

        # Si el código es 0, la conexión se ha hecho correctamente.
        if code == 0:
            # Guardamos el usuario actual.
            client._current_user = user

            # Mostramos mensaje de éxito.
            client._safe_print("c> CONNECT OK")

            # Devolvemos OK.
            return client.RC.OK

        # Si el código es 1, el usuario no existe.
        if code == 1:
            # Como no hubo conexión real, cerramos la escucha.
            client._stop_listener()

            # Mostramos el error específico.
            client._safe_print("c> CONNECT FAIL, USER DOES NOT EXIST")

            # Devolvemos error de usuario.
            return client.RC.USER_ERROR

        # Si el código es 2, el usuario ya estaba conectado.
        if code == 2:
            # También cerramos la escucha porque no se va a usar.
            client._stop_listener()

            # Mostramos el mensaje correspondiente.
            client._safe_print("c> USER ALREADY CONNECTED")

            # Devolvemos error de usuario.
            return client.RC.USER_ERROR

        # Cualquier otro código lo tratamos como error general.
        client._stop_listener()
        client._safe_print("c> CONNECT FAIL")
        return client.RC.ERROR

    # Método para pedir la lista de usuarios conectados.
    @staticmethod
    def users():
        # Si no hay usuario conectado en este cliente, no tiene sentido pedir la lista.
        if client._current_user is None:
            client._safe_print("c> CONNECTED USERS FAIL, USER IS NOT CONNECTED")
            return client.RC.USER_ERROR

        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación USERS.
                client._send_string(sock, "USERS")

                # Enviamos también el nombre del usuario que hace la petición,
                # porque el protocolo actualizado lo exige.
                client._send_string(sock, client._current_user)

                # Leemos el código de respuesta.
                code = client._recv_code(sock)

                # Si el código es 0, la operación ha ido bien.
                if code == 0:
                    # Recibimos primero la cantidad de usuarios conectados como texto.
                    count_text = client._recv_string(sock)

                    # Convertimos ese texto a entero.
                    count = int(count_text)

                    # Recibimos exactamente tantos datos como indique count.
                    users_info = []
                    for _ in range(count):
                        user_data = client._recv_string(sock)
                        users_info.append(user_data)

                        # Parseamos formato "usuario::IP::puerto" (Parte 2.1)
                        parts = user_data.split("::")
                        if len(parts) == 3:
                            username = parts[0]
                            ip = parts[1]
                            port = int(parts[2])

                            # Guardamos en cache (Parte 2.1)
                            client._connected_users_cache[username] = (ip, port)
                else:
                    # Si no fue bien, dejamos la cuenta a cero...
                    count = 0

                    # ...y la lista vacía.
                    users_info = []

        # Si algo falla al comunicar con el servidor...
        except Exception:
            # ...mostramos error general.
            client._safe_print("c> CONNECTED USERS FAIL")

            # Y devolvemos error general.
            return client.RC.ERROR

        # Si el código es 0, mostramos la lista.
        if code == 0:
            # Mostramos la cabecera con el formato que pide el enunciado.
            client._safe_print(f"c> CONNECTED USERS ({count} users connected) OK")

            # Recorremos la lista de usuarios...
            for user_data in users_info:
                # Parseamos "usuario::IP::puerto"
                parts = user_data.split("::")
                if len(parts) == 3:
                    # Mostramos con formato completo (Parte 2.1)
                    client._safe_print(f"{parts[0]} :: {parts[1]} :: {parts[2]}")
                else:
                    # Si no tiene formato, mostrar tal cual
                    client._safe_print(user_data)

            # Devolvemos OK.
            return client.RC.OK

        # Si el código es 1, el usuario no está conectado.
        if code == 1:
            client._safe_print("c> CONNECTED USERS FAIL, USER IS NOT CONNECTED")
            return client.RC.USER_ERROR

        # Cualquier otro caso es error general.
        client._safe_print("c> CONNECTED USERS FAIL")
        return client.RC.ERROR

    # Método para desconectar un usuario.
    @staticmethod
    def disconnect(user):
        # Si el usuario pedido no coincide con el que está conectado,
        # devolvemos error directamente.
        if client._current_user != user:
            client._safe_print("c> DISCONNECT FAIL, USER NOT CONNECTED")
            return client.RC.USER_ERROR

        # Inicializamos la variable donde guardaremos el código de respuesta.
        code = None

        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación DISCONNECT.
                client._send_string(sock, "DISCONNECT")

                # Enviamos el nombre del usuario a desconectar.
                client._send_string(sock, user)

                # Leemos el código de respuesta.
                code = client._recv_code(sock)

        # Si ocurre cualquier error en la comunicación...
        except Exception:
            # ...dejamos code como None.
            code = None

        # Este bloque se ejecuta siempre, haya ido bien o mal.
        finally:
            # El enunciado dice que el hilo de escucha debe pararse igualmente.
            client._stop_listener()

            # También dejamos de considerar que hay usuario conectado.
            client._current_user = None

        # Si el código es 0, la desconexión salió bien.
        if code == 0:
            client._safe_print("c> DISCONNECT OK")
            return client.RC.OK

        # Si el código es 1, el usuario no existe.
        if code == 1:
            client._safe_print("c> DISCONNECT FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        # Si el código es 2, el usuario no estaba conectado.
        if code == 2:
            client._safe_print("c> DISCONNECT FAIL, USER NOT CONNECTED")
            return client.RC.USER_ERROR

        # Cualquier otro caso es error general.
        client._safe_print("c> DISCONNECT FAIL")
        return client.RC.ERROR

    # Método para enviar un mensaje a otro usuario.
    @staticmethod
    def send(user, message):
        # Si no hay usuario conectado, no se puede enviar ningún mensaje.
        if client._current_user is None:
            client._safe_print("c> SEND FAIL")
            return client.RC.ERROR

        # Normalizar mensaje si está disponible el servicio web (Parte 2.2)
        message = client._normalize_message(message)

        # Comprobamos que el mensaje cumple el tamaño máximo del protocolo.
        if not client._message_fits_protocol(message):
            client._safe_print("c> SEND FAIL")
            return client.RC.ERROR

        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación SEND.
                client._send_string(sock, "SEND")

                # Enviamos el nombre del remitente, que es el usuario actual.
                client._send_string(sock, client._current_user)

                # Enviamos el nombre del destinatario.
                client._send_string(sock, user)

                # Enviamos el contenido del mensaje.
                client._send_string(sock, message)

                # Recibimos el código de respuesta del servidor.
                code = client._recv_code(sock)

                # Si el envío fue aceptado, el servidor también manda el ID del mensaje.
                message_id = client._recv_string(sock) if code == 0 else None

        # Si algo falla en la comunicación...
        except Exception:
            # ...mostramos error.
            client._safe_print("c> SEND FAIL")

            # Devolvemos error general.
            return client.RC.ERROR

        # Si el código es 0, el servidor aceptó el mensaje.
        if code == 0:
            client._safe_print(f"c> SEND OK - MESSAGE {message_id}")
            return client.RC.OK

        # Si el código es 1, el destinatario no existe.
        if code == 1:
            client._safe_print("c> SEND FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        # Cualquier otro caso es error general.
        client._safe_print("c> SEND FAIL")
        return client.RC.ERROR

    # Método para enviar un mensaje con fichero adjunto (Parte 2.1).
    @staticmethod
    def sendAttach(user, file_name, message):
        # Si no hay usuario conectado, no se puede enviar ningún adjunto.
        if client._current_user is None:
            client._safe_print("c> SENDATTACH FAIL (no current user)")
            return client.RC.ERROR

        # Comprobamos que el fichero existe en la máquina donde corre este cliente.
        if not os.path.exists(file_name):
            client._safe_print(f"c> SENDATTACH FAIL (file not found: {file_name})")
            return client.RC.ERROR

        # Normalizamos el mensaje usando el servicio web si está disponible.
        message = client._normalize_message(message)

        # Comprobamos el tamaño máximo permitido por el protocolo.
        if not client._message_fits_protocol(message):
            client._safe_print("c> SENDATTACH FAIL (message too large)")
            return client.RC.ERROR

        try:
            # Abrimos conexión con el servidor principal.
            with client._connect_to_server() as sock:
                # Enviamos la operación SENDATTACH.
                client._send_string(sock, "SENDATTACH")

                # Enviamos remitente, destinatario, mensaje y nombre del fichero.
                client._send_string(sock, client._current_user)
                client._send_string(sock, user)
                client._send_string(sock, message)
                client._send_string(sock, file_name)

                # Recibimos el código de respuesta del servidor.
                code = client._recv_code(sock)

                # Si el servidor aceptó el mensaje, también devuelve el ID.
                message_id = client._recv_string(sock) if code == 0 else None

        except Exception as e:
            client._safe_print(f"c> SENDATTACH FAIL (exception: {e})")
            return client.RC.ERROR

        if code == 0:
            client._safe_print(f"c> SENDATTACH OK - MESSAGE {message_id}")
            return client.RC.OK

        if code == 1:
            client._safe_print("c> SENDATTACH FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        client._safe_print(f"c> SENDATTACH FAIL (server code: {code})")
        return client.RC.ERROR

    @staticmethod
    def getFile(user, remote_filename, local_filename):
        # Si no estamos conectados
        if client._current_user is None:
            client._safe_print("c> FILE TRANSFER FAILED, user not connected.")
            return client.RC.ERROR

        # Buscar en cache primero
        if user not in client._connected_users_cache:
            # Actualizar cache
            client.users()

        # Si sigue sin estar, user no conectado
        if user not in client._connected_users_cache:
            client._safe_print("c> FILE TRANSFER FAILED, user not connected.")
            return client.RC.USER_ERROR

        ip, port = client._connected_users_cache[user]

        try:
            # Conectar al listener del usuario remoto
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, port))
            sock.settimeout(10.0)

            # Protocolo: GET FILE (Parte 2.1)
            client._send_string(sock, "GET FILE")
            client._send_string(sock, client._current_user)  # Quien soy
            client._send_string(sock, remote_filename)  # Fichero que quiero

            # Recibir fichero en chunks
            with open(local_filename, 'wb') as f:
                # Primero recibimos el tamaño (como número en cadena)
                size_text = client._recv_string(sock)
                file_size = int(size_text)

                # Si tamaño es 0, hubo error en el servidor
                if file_size == 0:
                    sock.close()
                    client._safe_print("c> FILE TRANSFER FAILED, file not found.")
                    return client.RC.ERROR

                # Luego recibimos los datos
                bytes_received = 0
                while bytes_received < file_size:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_received += len(chunk)

            sock.close()

            if bytes_received == file_size:
                client._safe_print(f"c> FILE TRANSFER OK")
                return client.RC.OK
            else:
                client._safe_print(f"c> FILE TRANSFER FAILED, incomplete.")
                return client.RC.ERROR

        except Exception as e:
            client._safe_print(f"c> FILE TRANSFER FAILED, {str(e)}")
            return client.RC.ERROR

    # Método que interpreta los comandos que escribe el usuario.
    @staticmethod
    def shell():
        # Bucle principal de la consola del cliente.
        while True:
            try:
                # Leemos una línea de entrada mostrando el prompt c>.
                command = input("c> ")

                # Eliminamos espacios al principio y al final.
                stripped = command.strip()

                # Si el usuario no ha escrito nada, volvemos a pedir entrada.
                if not stripped:
                    continue

                # Sacamos la operación principal y la pasamos a mayúsculas.
                op = stripped.split(maxsplit=1)[0].upper()

                # Si la operación es REGISTER...
                if op == "REGISTER":
                    # Partimos la línea por espacios.
                    parts = stripped.split()

                    # Comprobamos que tenga exactamente 2 partes.
                    if len(parts) == 2:
                        # Llamamos a register con el nombre de usuario.
                        client.register(parts[1])
                    else:
                        # Si no, mostramos la sintaxis correcta.
                        print("Syntax error. Usage: REGISTER <userName>")

                # Si la operación es UNREGISTER...
                elif op == "UNREGISTER":
                    # Volvemos a dividir la línea.
                    parts = stripped.split()

                    # Debe tener exactamente 2 partes.
                    if len(parts) == 2:
                        # Llamamos a unregister.
                        client.unregister(parts[1])
                    else:
                        # Si no, avisamos del formato correcto.
                        print("Syntax error. Usage: UNREGISTER <userName>")

                # Si la operación es CONNECT...
                elif op == "CONNECT":
                    # Dividimos la línea.
                    parts = stripped.split()

                    # Debe llevar exactamente un nombre de usuario.
                    if len(parts) == 2:
                        # Llamamos a connect.
                        client.connect(parts[1])
                    else:
                        # Si no, mostramos la ayuda.
                        print("Syntax error. Usage: CONNECT <userName>")

                # Si la operación es DISCONNECT...
                elif op == "DISCONNECT":
                    # Dividimos la línea.
                    parts = stripped.split()

                    # También debe tener exactamente 2 partes.
                    if len(parts) == 2:
                        # Llamamos a disconnect.
                        client.disconnect(parts[1])
                    else:
                        # Si no, mostramos la sintaxis correcta.
                        print("Syntax error. Usage: DISCONNECT <userName>")

                # Si la operación es USERS...
                elif op == "USERS":
                    # Dividimos la línea.
                    parts = stripped.split()

                    # USERS no debe llevar argumentos.
                    if len(parts) == 1:
                        # Llamamos al método users.
                        client.users()
                    else:
                        # Si sobran argumentos, avisamos.
                        print("Syntax error. Usage: USERS")

                # Si la operación es SEND...
                elif op == "SEND":
                    # Dividimos la línea como mucho en tres partes:
                    # comando, usuario y mensaje completo.
                    parts = stripped.split(maxsplit=2)

                    # Deben salir exactamente tres elementos.
                    if len(parts) == 3:
                        # Llamamos a send pasando destinatario y mensaje.
                        client.send(parts[1], parts[2])
                    else:
                        # Si no, mostramos la sintaxis correcta.
                        print("Syntax error. Usage: SEND <userName> <message>")

                # Si la operación es SENDATTACH (Parte 2.1)...
                elif op == "SENDATTACH":
                    # Dividimos la línea como mucho en cuatro partes (Parte 2.1).
                    # SENDATTACH <usuario> <fichero> <mensaje>
                    parts = stripped.split(maxsplit=3)

                    # Deben existir comando, usuario, nombre de fichero y mensaje.
                    if len(parts) == 4:
                        # Llamamos a sendAttach (Parte 2.1).
                        client.sendAttach(parts[1], parts[2], parts[3])
                    else:
                        # Si no, mostramos la ayuda.
                        print("Syntax error. Usage: SENDATTACH <userName> <fileName> <message>")

                # Si la operación es GETFILE (Parte 2.1)...
                elif op == "GETFILE":
                    # GETFILE <usuario> <fichero_remoto> <fichero_local>
                    parts = stripped.split()

                    # Deben haber exactamente 4 partes.
                    if len(parts) == 4:
                        # Llamamos a getFile (Parte 2.1).
                        client.getFile(parts[1], parts[2], parts[3])
                    else:
                        # Si no, mostramos la sintaxis (Parte 2.1).
                        print("Syntax error. Usage: GETFILE <userName> <remoteFile> <localFile>")

                # Si la operación es QUIT...
                elif op == "QUIT":
                    # Dividimos la línea.
                    parts = stripped.split()

                    # QUIT no debe llevar argumentos.
                    if len(parts) == 1:
                        # Salimos del bucle principal.
                        break
                    else:
                        # Si no, mostramos la forma correcta.
                        print("Syntax error. Use: QUIT")

                # Si no coincide con ningún comando conocido...
                else:
                    # ...avisamos de que el comando no es válido.
                    print("Error: command " + op + " not valid.")

            # Si el usuario manda EOF, por ejemplo con Ctrl+D, salimos.
            except EOFError:
                break

            # Si el usuario pulsa Ctrl+C, hacemos salto de línea y salimos.
            except KeyboardInterrupt:
                print()
                break

            # Cualquier otro error inesperado se muestra por pantalla.
            except Exception as e:
                print("Exception: " + str(e))

    # Método para mostrar el uso correcto del programa.
    @staticmethod
    def usage():
        # Imprimimos la forma correcta de ejecutar el cliente.
        print("Usage: python3 client.py -s <server> -p <port>")

    # Método para leer y validar los argumentos de entrada.
    @staticmethod
    def parseArguments(argv):
        # Creamos el parser de argumentos.
        parser = argparse.ArgumentParser()

        # Añadimos el argumento -s para la IP o nombre del servidor.
        parser.add_argument("-s", type=str, required=True, help="Server IP")

        # Añadimos el argumento -p para el puerto del servidor.
        parser.add_argument("-p", type=int, required=True, help="Server Port")

        # Parseamos los argumentos recibidos.
        args = parser.parse_args(argv)

        # Si por alguna razón no hay servidor, mostramos error.
        if args.s is None:
            parser.error("Usage: python3 client.py -s <server> -p <port>")
            return False

        # Comprobamos que el puerto esté dentro del rango permitido.
        if args.p < 1024 or args.p > 65535:
            parser.error("Error: Port must be in the range 1024 <= port <= 65535")
            return False

        # Guardamos la IP o nombre del servidor.
        client._server = args.s

        # Guardamos el puerto del servidor.
        client._port = args.p

        # Devolvemos True indicando que todo es correcto.
        return True

    # Método principal del programa.
    @staticmethod
    def main(argv):
        # Primero validamos los argumentos.
        if not client.parseArguments(argv):
            # Si no son válidos, mostramos la ayuda.
            client.usage()

            # Y terminamos el programa.
            return

        try:
            # Si todo es correcto, arrancamos la shell del cliente.
            client.shell()
        finally:
            # Al salir, paramos el hilo de escucha por seguridad.
            client._stop_listener()

            # Y limpiamos el usuario actual.
            client._current_user = None

        # Mostramos mensaje final de terminación.
        print("+++ FINISHED +++")


# Este bloque solo se ejecuta si lanzamos este archivo directamente.
if __name__ == "__main__":
    # Llamamos al método main pasándole todos los argumentos excepto el nombre del archivo.
    client.main(sys.argv[1:])