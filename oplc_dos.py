import socket
import struct
import threading
import time

# Common request data
REQUEST = struct.pack('>HHHBBHH',
                      1,  # Transaction ID
                      0,  # Protocol ID
                      6,  # Length (bytes after this)
                      1,  # Unit ID (slave address)
                      3,  # Function code 3 = read holding registers
                      5,  # Starting address
                      5)  # Number of registers

count = 0
status = 'Checking... '
run = True


def fire_and_forget():
    global count
    while run:
        try:
            sock = socket.socket()
            sock.settimeout(0.01)
            sock.connect(('localhost', 502))
            sock.send(REQUEST)
            count = count + 1
            sock.close()
        except Exception as e:
            pass


def timed_requests():
    global status
    while run:
        try:
            sock = socket.socket()
            sock.settimeout(1.0)
            sock.connect(('localhost', 502))
            sock.send(REQUEST)

            response = sock.recv(256)
            sock.close()

            if len(response) >= 9:
                func_code = response[7]
                if func_code == 3:
                    if len(response) >= 19:
                        registers = struct.unpack('>5H', response[9:19])
                        status = f"[V] Valid: {registers}"
                    else:
                        status = "[V] Valid response (wrong size)"
                elif func_code == 0x83:  # 0x83 = exception (function code + 0x80)
                    status = "[X] Exception response"
                else:
                    status = f"? Unexpected function code: {func_code}"
            else:
                status = "[X] No/partial response"

        except socket.timeout:
            status = "[X] Timeout"
        except ConnectionRefusedError:
            status = "[X] Connection refused"
        except:
            status = "[X] Error"
        time.sleep(1)


# Start threads
threading.Thread(target=fire_and_forget, daemon=True).start()
threading.Thread(target=timed_requests, daemon=True).start()

try:
    while True:
        print(f"\rRequests: {count:<8} | Status: {status:<20}" + " " * 10, end="", flush=True)
        time.sleep(0.5)
except KeyboardInterrupt:
    run = False
    print(f"\n\nTotal: Sent {count} requests")
    print(f"Last status: {status}")
