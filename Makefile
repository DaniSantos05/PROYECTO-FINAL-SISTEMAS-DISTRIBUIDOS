CC = gcc
CFLAGS = -Wall -Wextra -pedantic -std=c11 -pthread
TARGET = server
SRC = server.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $(SRC) -o $(TARGET)

run-server: $(TARGET)
	./$(TARGET) -p 8888

run-client:
	python3 client.py -s localhost -p 8888

clean:
	rm -f $(TARGET)