#!/bin/bash
# mitm_iptables.sh

# Clear existing rules
iptables -t nat -F

# Redirect ALL localhost traffic on port 502 to 2502
iptables -t nat -A OUTPUT -p tcp -d 127.0.0.1 --dport 502 -j REDIRECT --to-port 2502

# BUT: Exclude traffic coming FROM port 2502 (our MITM proxy)
# This allows MITM to connect to real server on 502
iptables -t nat -I OUTPUT 1 -p tcp -d 127.0.0.1 --sport 25002:25010 --dport 502 -j ACCEPT

echo "Rules set:"
echo "1. Redirect 127.0.0.1:502 -> 127.0.0.1:2502"
echo "2. Allow 127.0.0.1:25002-25010 -> 127.0.0.1:502 (for MITM)"
iptables -t nat -L OUTPUT -n