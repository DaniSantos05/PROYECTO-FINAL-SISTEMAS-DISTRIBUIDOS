#!/usr/bin/env python3
# Importamos Flask para crear el servicio web
from flask import Flask, request, jsonify

# Importamos argparse para leer argumentos de línea de comandos
import argparse

# Importamos sys para manejo de salida
import sys

# Creamos la aplicación Flask
app = Flask(__name__)

# ENDPOINT: POST /normalize
@app.route("/normalize", methods=["POST"])
def normalize():
    """
    Normaliza un mensaje eliminando espacios en blanco redundantes
    
    Los espacios múltiples se convierten en un solo espacio
    
    Request:
      {
        "message": "Hola    mundo   de   Python"
      }
    
    Response:
      {
        "normalized": "Hola mundo de Python"
      }
    
    Errors:
      400 - Si la solicitud no es válida
    """
    try:
        # Obtenemos los datos JSON de la solicitud
        data = request.get_json()
        
        # Extrae el mensaje (por defecto cadena vacía si no existe)
        message = data.get('message', '')
        
        # Si el mensaje no es una cadena, convertimos
        if not isinstance(message, str):
            message = str(message)
        
        # Normalizamos el mensaje:
        # split() sin argumentos divide por cualquier espacio en blanco
        # y elimina espacios redundantes automáticamente
        # luego join() los vuelve a unir con un espacio simple
        normalized = ' '.join(message.split())
        
        # Retornamos el mensaje normalizado
        return jsonify({"normalized": normalized}), 200
    
    except Exception as e:
        # Si hay algún error, devolvemos un mensaje de error
        return jsonify({"error": str(e)}), 400


# ENDPOINT: GET /health - Verifica que el servicio está activo
@app.route("/health", methods=['GET'])
def health():
    """
    Verifica que el servicio web está activo y funcionando.
    
    Response:
      {
        "status": "ok"
      }
    """
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    # Creamos el parser de argumentos
    parser = argparse.ArgumentParser(
        description = "Servicio Web de Normalización de Mensajes"
    )
    
    # Argumento opcional para el puerto
    parser.add_argument(
        "--port",
        type = int,
        default = 5000,
        help = "Puerto en el que escuchar (por defecto 5000)"
    )
    
    # Argumento opcional para el host
    parser.add_argument(
        "--host",
        type = str,
        default = "127.0.0.1",
        help = "Dirección IP para escuchar (por defecto 127.0.0.1)"
    )
    
    # Parseamos los argumentos
    args = parser.parse_args()
    
    # Validamos que el puerto esté en rango válido
    if args.port < 1024 or args.port > 65535:
        print(f"Error: Puerto {args.port} fuera de rango (1024-65535)", file=sys.stderr)
        sys.exit(1)
    
    # Mostramos información del arranque
    print(f"═" * 60)
    print(f"Servicio Web de Normalización de Mensajes")
    print(f"═" * 60)
    print(f"Escuchando en: http://{args.host}:{args.port}")
    print(f"Endpoint:      POST http://{args.host}:{args.port}/normalize")
    print(f"Health check:  GET  http://{args.host}:{args.port}/health")
    print(f"═" * 60)
    print("Presiona Ctrl+C para detener...")
    print()
    
    # Ejecutamos la aplicación Flask
    # debug = False para producción, debug = True para desarrollo
    try:
        app.run(host = args.host, port = args.port, debug = False, use_reloader = False)
    except KeyboardInterrupt:
        print("\nServicio detenido por el usuario")
        sys.exit(0)
    except Exception as e:
        print(f"Error al iniciar el servicio: {e}", file=sys.stderr)
        sys.exit(1)